import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from ..schemas import HarnessTurnRequest, PlaceIds, PlanningChat, RequestPlan
from ..services import amap, analytics, planning, sse
from ..services.errors import ServiceError

logger = logging.getLogger(__name__)

router = APIRouter()

PLANNING_SSE_HEARTBEAT_SECONDS = 15.0  # 与行程流一致：模型思考超过 15 秒就发注释行保活

@router.get('/api/places')
async def places(city: str = Query(min_length=1, max_length=40), q: str = Query(min_length=1, max_length=80)):
    return await amap.search_places(city.strip(), q.strip())

@router.post('/api/places/details')
async def place_details(body: PlaceIds):
    return await amap.find_places(body.ids)

@router.get('/api/discover/nearby')
async def discover_nearby(lon: float = Query(ge=73, le=135), lat: float = Query(ge=3, le=54),
                          radius: int = Query(default=3000, ge=500, le=10000)):
    return await amap.discover_nearby(lon, lat, radius)

@router.get('/api/discover/city-center')
async def discover_city_center(city: str = Query(min_length=1, max_length=40)):
    center = await amap.city_center(city.strip())
    if not center:
        raise HTTPException(404, '没有找到这个城市，请换个名称试试。')
    return center

def _require_user_turn(body: PlanningChat) -> None:
    if body.messages[-1].role != 'user':
        raise HTTPException(422, '请先输入旅行需求。')


async def _planning_chat(body: PlanningChat, on_reply=None):
    _require_user_turn(body)
    messages = [m.model_dump() for m in body.messages]
    result = await planning.planning_chat(messages, body.current, on_reply=on_reply)
    updates = {k: v for k, v in result['updates'].items() if k in RequestPlan.model_fields}
    try:
        validated = RequestPlan.model_validate({'city': '待确定', 'days': 1, **updates})
    except ValidationError as exc:
        raise HTTPException(422, 'AI 识别到的条件不符合要求，请确认城市和1至5天的行程。') from exc
    city = updates.get('city') or (body.current or {}).get('city', '')
    places, notice = [], ''
    if isinstance(city, str) and city.strip():
        for keyword in result.get('place_keywords', []):
            try:
                matches = await amap.search_places(city.strip(), keyword)
                places.append({'keyword': keyword, 'matches': matches[:3]})
            except ServiceError:
                notice = '地图地点暂时无法查询，可稍后重试。'
                break
    return {'reply': result['reply'], 'updates': {k: validated.model_dump(mode='json')[k] for k in updates},
            'place_matches': places, 'place_notice': notice, 'intent': result.get('intent', 'chat')}


@router.post('/api/planning/chat')
async def planning_chat(body: PlanningChat):
    return await _planning_chat(body)


@router.post('/api/planning/chat/stream')
async def planning_chat_stream(body: PlanningChat):
    _require_user_turn(body)
    queue: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            result = await _planning_chat(body, on_reply=lambda text: queue.put_nowait({'kind':'delta','text':text}))
            await queue.put({'kind':'done', **result})
        except (ServiceError, HTTPException) as exc:
            await queue.put({'kind':'error','message':str(exc.detail if isinstance(exc, HTTPException) else exc)})
        except Exception:
            await queue.put({'kind':'error','message':'行程助手暂时不可用，请稍后再试。'})
        finally:
            await queue.put(None)

    return sse.sse_response(queue, run, heartbeat=PLANNING_SSE_HEARTBEAT_SECONDS)


@router.post('/api/planning/session/stream')
async def planning_session_stream(body: HarnessTurnRequest, request: Request):
    """规划会话的统一入口：模型提议、Harness 裁决，全过程用 SSE 事件汇报。

    匿名也能用；登录用户的 memory_enabled 打开时，后台会定期提炼长期记忆。
    这里不持有数据库 session：用户信息只取一次快照，长任务自己开短事务。
    """
    from ..services.harness import orchestrator
    from .dependencies import optional_user_snapshot

    user = optional_user_snapshot(request)
    queue: asyncio.Queue = asyncio.Queue()
    outcome = {'planned': False, 'failed': False}
    await asyncio.to_thread(analytics.record, 'generate_start')

    async def emit(event: dict) -> None:
        # 生成成败以服务端事件为准：有 plan 即成功，error 或 failed done 即失败。
        if event.get('kind') == 'plan':
            outcome['planned'] = True
        elif event.get('kind') == 'error' or (event.get('kind') == 'done' and event.get('failed')):
            outcome['failed'] = True
        await queue.put(event)

    async def run():
        try:
            await orchestrator.run_turn(body, user, emit)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 兜底事件，绝不让连接静默断开
            logger.exception('planning session failed')
            outcome['failed'] = True
            await queue.put({'kind': 'error', 'message': '这次没有排成功，已保留你的输入。可以重试或换个说法。'})
            await queue.put({'kind': 'done', 'reply': '', 'failed': True})
        finally:
            if outcome['planned']:
                await asyncio.to_thread(analytics.record, 'generate_success')
            elif outcome['failed']:
                await asyncio.to_thread(analytics.record, 'generate_failure')
            await queue.put(None)

    return sse.sse_response(queue, run, heartbeat=PLANNING_SSE_HEARTBEAT_SECONDS)

