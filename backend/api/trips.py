import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as DBSession
from ..auth import read_token
from ..db import ShareLink, Trip, TripCollaborator, TripInvite, User
from ..schemas import (CreateTrip, GuideAdopt, GuideText, JoinCodeRequest, JoinTripRequest, PreviewAssistant,
                       SavePreview, ShareAccess, StartDateUpdate, TripChat, UpdateDays, UpdateTrip, VisibilityUpdate)
from ..services import accounts, amap, analytics, join_codes, live, planning, preview, privacy, route_opt, sse, trip_places
from ..services.maintenance import PURGE_DAYS
from ..services.tokens import hash_token, new_token
from ..services.errors import ServiceError
from .dependencies import current_user, db_session, get_trip, get_trip_member

router = APIRouter()
log = logging.getLogger(__name__)

INVITE_TTL_DAYS = 7  # 协作邀请有效期：过期后只能由 owner 重新生成
SSE_HEARTBEAT_SECONDS = 15.0  # SSE 空转心跳间隔，避免代理/浏览器掐断长连接

def _parse_iso(value: str) -> datetime:
    """历史时间串可能没写时区，统一按 UTC 理解。"""
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

def _invite_expired(invite: TripInvite) -> bool:
    """旧库的邀请没有 expires_at：按 created_at + 7 天推算，不回填历史行。"""
    try:
        expires = _parse_iso(invite.expires_at) if invite.expires_at else _parse_iso(invite.created_at) + timedelta(days=INVITE_TTL_DAYS)
    except (TypeError, ValueError):
        return True  # 时间戳损坏的邀请按过期处理，宁可让 owner 重发
    return expires <= datetime.now(timezone.utc)

def _check_version(row: Trip, requested: int | None) -> int:
    version = row.version or 0
    if requested is not None and requested != version:
        raise HTTPException(409, '行程已在其他操作中更新，请重新打开行程后重试。未保存的修改仍在当前页面。')
    return version

def _load_data(raw: str) -> dict:
    """解析行程 JSON：单条数据损坏时给出可理解的错误，而不是把 JSONDecodeError 500 抛给用户。"""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.error('行程数据不是合法 JSON')
        raise HTTPException(500, '行程数据损坏，无法打开，请联系支持。')
    if not isinstance(data, dict):
        log.error('行程数据不是 JSON 对象：%s', type(data).__name__)
        raise HTTPException(500, '行程数据损坏，无法打开，请联系支持。')
    return data

def _user_memories(db: DBSession, user: User) -> list[dict]:
    """读取当前用户可用的长期记忆；记忆是增强，读失败不能影响改稿主流程。"""
    if not getattr(user, 'memory_enabled', True):
        return []
    try:
        from ..services.harness.memory.store import MemoryStore
        return MemoryStore(db).list_for_user(user.id, limit=8)
    except Exception as exc:  # noqa: BLE001 - 记忆失败只降级，不改稿照常进行
        log.warning('saved trip memory load failed: %s', type(exc).__name__)
        return []

def _detail(row: Trip, data: dict, user_id: int) -> dict:
    """统一「行程内容」响应形状：详情 + 归属/可见性；只新增字段，不改既有字段。"""
    return {'id': row.id, 'title': row.title, 'version': row.version or 0,
            'is_owner': row.user_id == user_id, 'is_public': bool(row.is_public),
            'last_edited_by': row.last_edited_by, 'last_edited_at': row.last_edited_at, **data}

def _save_data(db: DBSession, row: Trip, data: dict, version: int, editor: str | None = None) -> int:
    values = {'data': json.dumps(trip_places.for_storage(data, _load_data(row.data)), ensure_ascii=False),
              'version': version + 1}
    if editor:
        # 只记录最近一次保存，用于冲突提示“线上版本最近由谁保存”；不改变权限与 CAS 语义。
        values['last_edited_by'] = editor
        values['last_edited_at'] = amap.now()
    result = db.execute(update(Trip).where(
        Trip.id == row.id, Trip.user_id == row.user_id, Trip.deleted_at.is_(None),
        func.coalesce(Trip.version, 0) == version,
    ).values(**values)
      .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '行程已在其他操作中更新，请重新打开行程后重试。未保存的修改仍在当前页面。')
    db.commit()
    return version + 1

async def _drive_agent(agent, state: dict, data: dict, row: Trip, version: int, queue, editor: str | None = None) -> None:
    """消费 agent 事件按原顺序入队；done 之后即使没人读流也把对话保存完。

    agent 由端点传入而不是模块级导入，避免 api 层与 services.agent 形成循环依赖。
    保存必须新开短会话：请求 session 在开流前已 commit 归还连接，且流可能比请求活得久。
    """
    from .. import db as app_db  # 动态取模块，测试替换 app_db.Session 后仍然生效
    failed = False
    try:
        async for chunk in agent.run_stream(state):
            for item in chunk.get('events', []):
                if item.get('kind') == 'done':
                    state['completed'] = True
                await queue.put(item)
            if 'suggestion' in chunk:
                state['suggestion'] = chunk['suggestion']
            if 'reply' in chunk:
                state['reply'] = chunk['reply']
            if 'changed' in chunk:
                state['changed'] = chunk['changed']
    except HTTPException as exc:
        failed = True
        await queue.put({'kind': 'error', 'message': str(exc.detail)})
    except ServiceError as exc:
        failed = True
        await queue.put({'kind': 'error', 'message': str(exc)})
    except Exception:  # noqa: BLE001 —— 流内兜底，不让连接悬挂
        failed = True
        await queue.put({'kind': 'error', 'message': '行程助手暂时不可用，请稍后再试。'})
    finally:
        suggestion = state.get('suggestion')
        if suggestion and state.get('completed') and not failed:
            data['conversation'] = (data.get('conversation', []) + [
                {'role': 'user', 'content': state['message']},
                {'role': 'assistant', 'content': suggestion['reply']},
            ])[-100:]
            try:
                with app_db.Session() as session:
                    final_version = _save_data(session, row, data, version, editor)
                await queue.put({'kind': 'saved', 'version': final_version})
            except HTTPException as exc:
                await queue.put({'kind': 'error', 'message': str(exc.detail)})
            except Exception:  # noqa: BLE001 —— 保存失败也要给前端终态事件，不让流悬挂
                await queue.put({'kind': 'error', 'message': '对话保存失败，请稍后重新打开行程。'})
        await queue.put(None)

def _collaborator_counts(db: DBSession, trip_ids: list[int]) -> dict[int, int]:
    """一次 grouped count 数出多段行程的协作者（不含 owner），列表页据此避免 N+1。"""
    if not trip_ids:
        return {}
    rows = db.execute(
        select(TripCollaborator.trip_id, func.count(TripCollaborator.id))
        .where(TripCollaborator.trip_id.in_(trip_ids))
        .group_by(TripCollaborator.trip_id)
    ).all()
    return {trip_id: count for trip_id, count in rows}

def _require_places(data: dict) -> None:
    """地点详情刷新失败时统一 503：调用方不能继续读可能缺字段的 data。"""
    if data.get('place_notice'):
        raise HTTPException(503, data['place_notice'])

async def _refreshed_data(row: Trip, action: str) -> dict:
    """读行程并刷新地点详情；高德降级时回落到库内详情，让改稿链路继续。"""
    stored = _load_data(row.data)
    data = await trip_places.refresh(stored)
    if data.get('place_notice'):
        log.warning('高德地点暂不可用，使用已保存详情继续%s（trip_id=%s）', action, row.id)
        data = stored
    return data

def _assistant_inputs(days: list, backlog: list, history: list[dict], message: str) -> tuple[dict, str]:
    """把行程、待规划清单和对话压成 agent 需要的候选地点索引与文本上下文（正式流与预览流共用）。"""
    candidates = {stop['place']['id']: stop['place'] for day in days for stop in day['stops']}
    candidates.update({stop['place']['id']: stop['place'] for stop in backlog})
    context = '\n'.join([*(f"{'用户' if m['role'] == 'user' else '助手'}：{m['content']}" for m in history), f'用户最新要求：{message}'])
    return candidates, context


def _assistant_context(body: TripChat, data: dict) -> tuple[list, list, dict, str]:
    existing = data['days']
    backlog = data.get('backlog', [])
    candidates, context = _assistant_inputs(existing, backlog, [m.model_dump() for m in body.history], body.message)
    return existing, backlog, candidates, context

async def _lookup_places(city: str, names: list[str]) -> list[list[dict]]:
    """并发查高德（最多 AMAP_BATCH_CONCURRENCY 个在途），按输入顺序返回。"""
    semaphore = asyncio.Semaphore(amap.AMAP_BATCH_CONCURRENCY)

    async def lookup(name: str) -> list[dict]:
        async with semaphore:
            return await amap.search_places(city, name)

    return list(await asyncio.gather(*(lookup(name) for name in names)))

@router.get('/api/trips')
def trips(deleted: bool = False, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    query = select(Trip).where(Trip.user_id == user.id)
    query = query.where(Trip.deleted_at.is_not(None)) if deleted else query.where(Trip.deleted_at.is_(None))
    rows = db.scalars(query.order_by(Trip.id.desc())).all()
    if deleted:
        return [{'id': row.id, 'city': row.city, 'title': row.title, 'deleted_at': row.deleted_at,
                 'is_owner': True, 'is_public': bool(row.is_public)} for row in rows]
    # 协作人数一次 grouped count 覆盖整页，避免逐行查询（N+1）。
    counts = _collaborator_counts(db, [row.id for row in rows])
    result = []
    for row in rows:
        # 单条 data 损坏只影响自己：跳过并留下 trip id，不能让整页列表 500。
        try:
            # 列表/广场是容错读路径：坏行跳过，不能让 _load_data 的 500 打断整页。
            request = json.loads(row.data)['request']
        except (ValueError, TypeError, KeyError):
            log.warning('跳过数据损坏的行程列表行（trip_id=%s）', row.id)
            continue
        result.append({'id': row.id, 'city': row.city, 'title': row.title, 'is_owner': True,
                       'is_public': bool(row.is_public), 'request': request,
                       'collaborator_count': counts.get(row.id, 0)})
    return result

@router.get('/api/trips/shared')
async def shared_trips(user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """我是协作者且未删除的行程。注意：必须先于 /api/trips/{trip_id} 注册，避免 shared 被 int 参数吞掉。"""
    rows = db.execute(
        select(Trip, TripCollaborator.role, User.username)
        .join(TripCollaborator, TripCollaborator.trip_id == Trip.id)
        # 创建者可能已注销：外连接保证行程仍在列表里，用户名回退空串。
        .outerjoin(User, Trip.user_id == User.id)
        .where(TripCollaborator.user_id == user.id, Trip.deleted_at.is_(None))
        .order_by(Trip.id.desc())
    ).all()
    # 协作人数一次 grouped count 覆盖整页；在线人数并发读取 Redis/本地缓存，不查业务表。
    counts = _collaborator_counts(db, [row.id for row, _, _ in rows])
    online = await asyncio.gather(*(live.online_count_shared(row.id) for row, _, _ in rows))
    # role 取真实协作者记录（未来可能有只读角色），空值回落到历史默认值 edit。
    return {'trips': [{'id': row.id, 'title': row.title, 'city': row.city, 'role': role or 'edit',
                       'is_owner': False, 'is_public': bool(row.is_public),
                       'owner': owner or '', 'member_count': 1 + counts.get(row.id, 0),
                       'online': count}
                      for (row, role, owner), count in zip(rows, online)]}

# ---------------------------------------------------------------------------
# 分享码邀请 + 实时协同
# 统一放在所有 /api/trips/{trip_id} 路由之前注册：/api/trips/join 是字面路径，
# 若被带 int 路径参数的路由先匹配，会被当成 trip_id 解析而返回 422。
# ---------------------------------------------------------------------------

@router.post('/api/trips/join')
def join_trip(body: JoinTripRequest, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """用分享码加入别人的行程：无效码/已停用/行程已删统一 404，不泄露行程是否存在。"""
    code = join_codes.normalize(body.code)
    row = None
    if join_codes.is_well_formed(code):
        row = db.scalar(select(Trip).where(Trip.join_code == code, Trip.deleted_at.is_(None)))
    if row is None:
        raise HTTPException(404, join_codes.INVALID_MESSAGE)
    trip_id, title = row.id, row.title or ''
    already_member = row.user_id == user.id
    if not already_member:
        member = db.scalar(select(TripCollaborator).where(
            TripCollaborator.trip_id == trip_id, TripCollaborator.user_id == user.id))
        already_member = member is not None
    if not already_member:
        db.add(TripCollaborator(trip_id=trip_id, user_id=user.id, role='edit', created_at=amap.now()))
        try:
            db.commit()
        except IntegrityError:
            # 同一用户并发点两次「加入」：唯一约束拦住第二次，按已是协作者幂等返回。
            db.rollback()
            already_member = True
    return {'trip_id': trip_id, 'title': title, 'already_member': already_member}

@router.get('/api/trips/{trip_id}/join-code')
def get_join_code(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """读取分享码（仅 owner）：没有生成过返回 null，前端据此显示「生成分享码」。"""
    row = get_trip(trip_id, user, db)
    return {'code': row.join_code or None}

@router.post('/api/trips/{trip_id}/join-code')
def create_join_code(trip_id: int, body: JoinCodeRequest | None = None,
                     user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """生成或轮换分享码（仅 owner）：已有码且不轮换时幂等返回同一个码。"""
    row = get_trip(trip_id, user, db)
    if row.join_code and not (body and body.rotate):
        return {'code': row.join_code}
    code = join_codes.assign(db, row)
    if not code:
        raise HTTPException(503, '分享码生成失败，请稍后重试。')
    return {'code': code}

@router.delete('/api/trips/{trip_id}/join-code', status_code=204)
def delete_join_code(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """停用分享码（仅 owner）：只清分享码，已有链接分享不受影响。"""
    row = get_trip(trip_id, user, db)
    join_codes.clear(db, row)
    return Response(status_code=204)

def _live_user(websocket: WebSocket) -> tuple[int, str, str] | None:
    """WebSocket 版登录校验：token 规则与 dependencies.current_user 完全一致。

    WebSocket 不能走 Depends(HTTP 依赖) 的 401，所以自己读 cookie；失败由调用方 close(4401)。
    原始 token 一并返回给 Connection：握手后没有 HTTP 依赖可复核，心跳要凭它判断会话是否仍有效。
    """
    from .. import db as app_db  # 动态取模块：测试替换 app_db.Session 后仍然生效
    token = websocket.cookies.get(accounts.SESSION_COOKIE, '')
    parsed = read_token(token)
    if not parsed:
        return None
    user_id, session_version, session_nonce = parsed
    with app_db.Session() as db:
        user = db.get(User, user_id)
        if (user is None or user.session_version != session_version
                or (user.session_nonce or '') != session_nonce):
            return None
        return user.id, user.username, token

def _live_trip(trip_id: int, user_id: int) -> tuple[int, bool] | None:
    """实时入口的行程+成员校验：返回 (version, is_member)；行程不存在/已删返回 None。"""
    from .. import db as app_db
    with app_db.Session() as db:
        row = db.get(Trip, trip_id)
        if row is None or row.deleted_at:
            return None
        if row.user_id == user_id:
            return row.version or 0, True
        member = db.scalar(select(TripCollaborator).where(
            TripCollaborator.trip_id == trip_id, TripCollaborator.user_id == user_id))
        return row.version or 0, member is not None

def _live_still_allowed(trip_id: int, connection: live.Connection) -> int | None:
    """心跳时复核会话与成员资格：登出/被移出后一个心跳内断开，presence 不会留下幽灵成员。

    连接建立后 WebSocket 不再走 HTTP 依赖，服务端不会自动感知会话失效（退出登录会让
    session_version +1）；心跳是唯一可靠的复核点。返回要关闭的业务码，None 表示仍然有效。
    """
    from .. import db as app_db
    parsed = read_token(connection.token)
    if not parsed:
        return 4401
    user_id, session_version, session_nonce = parsed
    if user_id != connection.user_id:
        return 4401  # token 与连接身份不一致：属性异常，按未登录处理
    with app_db.Session() as db:
        user = db.get(User, user_id)
        if (user is None or user.session_version != session_version
                or (user.session_nonce or '') != session_nonce):
            return 4401
    state = _live_trip(trip_id, connection.user_id)
    if state is None:
        return 4404
    if not state[1]:
        return 4403
    return None

@router.websocket('/api/trips/{trip_id}/live')
async def trip_live(websocket: WebSocket, trip_id: int):
    """同一行程的实时协同：在线 presence + 版本变化推送，让多人能看到彼此正在规划。"""
    user = await asyncio.to_thread(_live_user, websocket)
    if user is None:
        # 先 accept 再 close：握手前关闭只能给出 403，前端拿不到 4401 这个业务码。
        await websocket.accept()
        await websocket.close(code=4401)
        return
    state = await asyncio.to_thread(_live_trip, trip_id, user[0])
    if state is None:
        await websocket.accept()
        await websocket.close(code=4404)
        return
    version, is_member = state
    if not is_member:
        await websocket.accept()
        await websocket.close(code=4403)
        return
    await websocket.accept()
    user_id, username, token = user
    connection = live.Connection(websocket, user_id, username, token)
    room = await live.join(trip_id, connection, version)
    try:
        await live.send(connection, {
            'type': 'hello', 'trip_id': trip_id, 'version': room.version,
            'presence': live.presence(room),
            'you': {'user_id': user_id, 'username': username},
        })
        # 新人加入也要让房间里其他人看到人数变化。
        await live.broadcast_presence(room)
        while True:
            message = await websocket.receive()
            if message.get('type') == 'websocket.disconnect':
                break
            text = message.get('text')
            if not text:
                continue  # 二进制帧/空帧静默忽略
            try:
                payload = json.loads(text)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get('type') == 'ping':
                # 心跳顺带复核会话与成员资格：登出/被移出后主动踢掉连接，presence 不会留下幽灵成员。
                close_code = await asyncio.to_thread(_live_still_allowed, trip_id, connection)
                if close_code is not None:
                    await websocket.close(code=close_code)
                    break
                # 心跳同时续约 Redis 在线状态：20 秒一次，远小于 45 秒的过期窗口。
                await live.touch(connection, trip_id)
                await live.send(connection, {'type': 'pong'})
            # 其它消息类型静默忽略：协议只保留 ping，客户端乱发不应影响连接。
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        # 断线、取消、异常都必须清理房间并广播 presence，否则别人会看到幽灵在线成员。
        # remove 内部完成 Redis 清理与广播；shield 保证即使本协程已被取消也能走完。
        try:
            await asyncio.shield(live.remove(room, connection))
        except asyncio.CancelledError:
            raise

@router.get('/api/trips/{trip_id}/version')
def trip_version(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """轻量版本探测：供 10 秒协作轮询使用，不刷新高德地点详情。"""
    row = get_trip_member(trip_id, user, db)
    return {'version': row.version or 0}

@router.get('/api/trips/{trip_id}')
async def trip_detail(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    data = await trip_places.refresh(_load_data(row.data))
    data.setdefault('backlog', [])
    return _detail(row, data, user.id)

@router.patch('/api/trips/{trip_id}')
def rename_trip(trip_id: int, body: UpdateTrip, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip(trip_id, user, db)
    title = body.title.strip()
    if not title:
        raise HTTPException(422, '请输入行程名称。')
    row.title = title
    db.commit()
    return {'id': row.id, 'title': row.title}

@router.put('/api/trips/{trip_id}/start-date')
def update_start_date(trip_id: int, body: StartDateUpdate, user: User = Depends(current_user),
                      db: DBSession = Depends(db_session)):
    """改出发日期：复制别人的行程后按自己的假期重排，不需要重新规划。

    day 数、地点顺序与路线都不变；日期只影响日期标签和行前检查。
    """
    row = get_trip_member(trip_id, user, db)
    version = _check_version(row, body.version)
    data = _load_data(row.data)
    data.setdefault('request', {})['start_date'] = body.start_date.isoformat() if body.start_date else None
    _save_data(db, row, data, version, user.username)
    db.refresh(row)
    return _detail(row, data, user.id)

@router.delete('/api/trips/{trip_id}')
def delete_trip(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip(trip_id, user, db)
    now = amap.now()
    row.deleted_at = now
    # 删除即撤销对外授权：恢复行程不会把旧分享、旧邀请和广场公开状态一起复活。
    db.execute(update(ShareLink).where(ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None))
               .values(revoked_at=now))
    db.execute(delete(TripInvite).where(TripInvite.trip_id == row.id))
    # 分享码同样是「对外授权」：留着它等于恢复后用旧码还能把人放进来，与撤销链接的语义
    # 相矛盾。这里只清字段、不调用 join_codes.clear（它内部 commit 会打断本次事务）。
    row.join_code = None
    row.is_public = 0
    db.commit()
    return {'ok': True, 'deleted_at': row.deleted_at, 'purge_days': PURGE_DAYS}

@router.post('/api/trips/{trip_id}/restore')
def restore_trip(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.user_id == user.id))
    if not row or not row.deleted_at:
        raise HTTPException(404, '没有找到可恢复的行程。')
    try:
        deleted_at = _parse_iso(row.deleted_at)
    except (TypeError, ValueError):
        # 历史脏数据（乱码/空串）按不可恢复处理：时间戳坏了也不该 500。
        log.warning('恢复行程失败：deleted_at 无法解析（trip_id=%s）', row.id)
        raise HTTPException(404, '没有找到可恢复的行程。')
    if deleted_at < datetime.now(timezone.utc) - timedelta(days=PURGE_DAYS):
        raise HTTPException(404, '该行程已超过 7 天，无法找回。')
    row.deleted_at = None
    db.commit()
    return {'ok': True, 'id': row.id}

@router.post('/api/trips/{trip_id}/assistant')
async def suggest_trip_change(trip_id: int, body: TripChat, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    version = _check_version(row, body.version)
    data = await _refreshed_data(row, '改稿')
    existing, backlog, candidates, context = _assistant_context(body, data)
    keywords = await planning.adjustment_keywords(context, existing, backlog)
    # 关键词之间互不依赖：并发查询高德，再按原顺序校验，保持原来的 422 文案。
    keyword_matches = await asyncio.gather(*(amap.search_places(row.city, keyword) for keyword in keywords))
    for keyword, matches in zip(keywords, keyword_matches):
        if not matches:
            raise HTTPException(422, f'没有找到地点“{keyword}”，请换个名称再试。')
        for place in matches:
            candidates[place['id']] = place
    memories = _user_memories(db, user)
    result = await planning.suggest_edits(
        data['request'], list(candidates.values()), context, existing, backlog,
        mode='trip', trip_id=row.id, version=version, memories=memories,
        history=[m.model_dump() for m in body.history],
    )
    if result['changed']:
        await amap.update_routes(result['days'], data['request']['transport'], row.city, existing)
    data['conversation'] = (data.get('conversation', []) + [
        {'role': 'user', 'content': body.message},
        {'role': 'assistant', 'content': result['reply']},
    ])[-100:]
    result['version'] = _save_data(db, row, data, version, user.username)
    return result

@router.post('/api/trips/{trip_id}/assistant/stream')
async def suggest_trip_change_stream(trip_id: int, body: TripChat, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """LangGraph agent 的 SSE 端点：同步校验后开流，节点事件实时推送（生命感 A 类）。"""
    from ..services import agent
    row = get_trip_member(trip_id, user, db)
    version = _check_version(row, body.version)
    data = await _refreshed_data(row, '流式改稿')
    existing, backlog, candidates, context = _assistant_context(body, data)
    state = {
        'message': body.message, 'history': [m.model_dump() for m in body.history],
        'trip_id': row.id, 'version': version, 'memories': _user_memories(db, user),
        'city': row.city, 'transport': data['request']['transport'],
        'request': data['request'], 'days': existing, 'backlog': backlog,
        'candidates': candidates, 'context': context,
    }
    # 长时间流式生成期间不占用数据库连接：结束读事务后把连接归还连接池，
    # 保存对话时再按需取一条短连接。否则每个 SSE 客户端都会占住一条连接。
    db.commit()
    queue: asyncio.Queue = asyncio.Queue()

    async def drive() -> None:
        # 保存逻辑在 _drive_agent 里：客户端读到 done 后断开，task 仍会自行完成保存。
        await _drive_agent(agent, state, data, row, version, queue, user.username)

    # done 已发出时不再取消，让 task 把 saved 事件与落库都做完；否则关流即取消。
    return sse.sse_response(queue, drive, heartbeat=SSE_HEARTBEAT_SECONDS,
                            should_cancel=lambda: not state.get('completed'))


@router.post('/api/trips/{trip_id}/guide')
async def parse_guide(trip_id: int, body: GuideText, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, '请输入攻略文字。')
    found = await planning.guide_places(text)
    # 逐个地名查高德互不依赖：一次并发发起，再按原顺序组装结果。
    all_matches = await _lookup_places(row.city, [item['name'] for item in found])
    results = [{**item, 'matches': matches[:5]} for item, matches in zip(found, all_matches)]
    return {'results': results}

@router.post('/api/trips/{trip_id}/guide/outline')
async def guide_outline(trip_id: int, body: GuideText, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """攻略一键成稿：AI 按行程天数拆解大纲，地点名逐个经高德核对（精确命中直接给 place，否则给候选）。"""
    row = get_trip_member(trip_id, user, db)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, '请输入攻略文字。')
    request = _load_data(row.data).get('request') or {}
    try:
        day_count = int(request['days'])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(503, '行程数据损坏，无法打开，请联系支持。')
    outline = await planning.guide_outline(text, day_count)
    # 大纲里的地名一次性并发核对（最多 4 个在途），再按原顺序回填，避免逐条串行等待。
    entries = [(day_index, item) for day_index, day in enumerate(outline) for item in day['stops']]
    all_matches = await _lookup_places(row.city, [item['name'] for _, item in entries])
    matched = iter(all_matches)
    days = []
    for day in outline:
        stops = []
        for item in day['stops']:
            matches = next(matched)
            place = next((m for m in matches if m['name'] == item['name']), None)
            stops.append({**item, 'place': place, 'matches': matches[:5]})
        days.append({'summary': day['summary'], 'stops': stops})
    return {'days': days}

@router.post('/api/trips/{trip_id}/guide/adopt')
async def guide_adopt(trip_id: int, body: GuideAdopt, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """把成稿勾选的地点追加到对应天的末尾，读时版本 CAS 立即持久化。"""
    row = get_trip_member(trip_id, user, db)
    version = _check_version(row, body.version)
    data = await trip_places.refresh(_load_data(row.data))
    _require_places(data)
    existing = data['days']
    backlog = data.get('backlog', [])
    taken = {s['place']['id'] for day in existing for s in day['stops']} | {s['place']['id'] for s in backlog}
    ids = list(dict.fromkeys(a.place_id for a in body.assignments))
    known = await amap.find_places(ids)
    missing = [pid for pid in ids if pid not in known]
    if missing:
        raise HTTPException(422, '部分地点暂时无法从高德核实，请刷新大纲后重试。')
    for item in body.assignments:
        index = item.day - 1
        if not 0 <= index < len(existing):
            raise HTTPException(422, '天数超出行程范围。')
        if item.place_id in taken:
            raise HTTPException(422, f'“{known[item.place_id]["name"]}”已在行程中，请取消勾选或先移除。')
        if len(existing[index]['stops']) >= 12:
            raise HTTPException(422, f'第 {item.day} 天已有 12 个地点，请先调整当天安排。')
        existing[index]['stops'].append({'place': known[item.place_id], 'duration': item.duration or 90, 'reason': ''})
        taken.add(item.place_id)
    await amap.update_routes(existing, data['request']['transport'], row.city, data['days'])
    _save_data(db, row, data, version, user.username)
    db.refresh(row)
    return _detail(row, data, user.id)

@router.post('/api/trips/{trip_id}/days/{day_index}/optimize')
async def optimize_day(trip_id: int, day_index: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    data = await trip_places.refresh(_load_data(row.data))
    _require_places(data)
    if not 0 <= day_index < len(data['days']):
        raise HTTPException(404, '行程日期不存在。')
    return await route_opt.suggest_route(data['days'][day_index], data['request']['transport'], row.city)

@router.get('/api/trips/{trip_id}/days/{day_index}/nearby')
async def nearby(trip_id: int, day_index: int, place_id: str = Query(min_length=1, max_length=100),
                 category: str = Query(pattern='^(餐厅|咖啡|景点)$'),
                 user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    data = await trip_places.refresh(_load_data(row.data))
    _require_places(data)
    if not 0 <= day_index < len(data['days']):
        raise HTTPException(404, '行程日期不存在。')
    anchor = next((s['place'] for s in data['days'][day_index]['stops'] if s['place']['id'] == place_id), None)
    if anchor is None:
        raise HTTPException(404, '请先保存当前行程，再选择已安排的地点。')
    return await amap.nearby_places(row.city, anchor['location'], category)

@router.post('/api/trips/{trip_id}/days/{day_index}/routes')
async def refresh_day_routes(trip_id: int, day_index: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    data = await trip_places.refresh(_load_data(row.data))
    _require_places(data)
    if not 0 <= day_index < len(data['days']):
        raise HTTPException(404, '行程日期不存在。')
    day = data['days'][day_index]
    await amap.update_routes([day], data['request']['transport'], row.city, data['days'])
    return {'day': day}

@router.put('/api/trips/{trip_id}/visibility')
def set_visibility(trip_id: int, body: VisibilityUpdate, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """三级可见性（仅 owner）：private 私密 / link 仅链接 / public 公开到广场。

    mode 缺省时保持旧的 {is_public} 行为与返回结构，老客户端不受影响。
    """
    row = get_trip(trip_id, user, db)
    if body.mode is None:
        row.is_public = 1 if body.is_public else 0
        db.commit()
        return {'is_public': bool(row.is_public)}

    active = db.scalar(select(ShareLink.id).where(
        ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None)).limit(1))
    token = None
    if body.mode == 'private':
        # 私密是「收回所有对外入口」：公开状态与链接一起撤销。
        db.execute(update(ShareLink).where(ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None))
                   .values(revoked_at=amap.now()))
        row.is_public = 0
        active = None
    elif body.mode == 'link':
        row.is_public = 0
        if active is None:
            token = new_token()
            db.add(ShareLink(trip_id=row.id, token_hash=hash_token(token)))
            active = 1
    else:
        row.is_public = 1
    db.commit()
    if body.mode in ('link', 'public'):
        analytics.record('share')
    return {
        'visibility': 'public' if row.is_public else ('link' if active else 'private'),
        'is_public': bool(row.is_public),
        'link_active': bool(active),
        **({'token': token} if token else {}),
    }

@router.get('/api/plaza')
def plaza(db: DBSession = Depends(db_session)):
    """灵感广场：最新 20 条公开行程。匿名可读；只暴露公开字段，不返回主人私有数据。"""
    rows = db.execute(
        select(Trip, User.username).join(User, Trip.user_id == User.id)
        .where(Trip.is_public == 1, Trip.deleted_at.is_(None))
        .order_by(Trip.id.desc()).limit(20)
    ).all()
    result = []
    for row, owner in rows:
        # 与列表接口一致：坏行跳过并告警，好行照常返回；排序/字段/limit 契约不变。
        try:
            data = json.loads(row.data)
            # 广场匿名可读：具体出发日期属于行踪信息，公开面只给天数。
            result.append({'id': row.id, 'title': row.title, 'city': row.city,
                           'days': len(data.get('days', [])), 'owner': owner,
                           'start_date': None})
        except (ValueError, TypeError, KeyError, AttributeError):
            log.warning('跳过数据损坏的广场行（trip_id=%s）', row.id)
            continue
    return {'trips': result}

@router.post('/api/plaza/{trip_id}/fork', status_code=201)
def fork_trip(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """复制公开行程为自己的行程（只复制行程内容，原作者的 AI 对话不随 fork 泄露）。"""
    row = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.is_public == 1, Trip.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '该行程不存在或未公开。')
    # 从公开面复制时同样先脱敏：不能绕开广场摘要，把精确日期和住宿地址带走。
    data = privacy.redact_public_trip(_load_data(row.data))
    copy = Trip(user_id=user.id, city=row.city, title=row.title,
                data=json.dumps(trip_places.for_storage(data), ensure_ascii=False))
    db.add(copy)
    db.commit()
    db.refresh(copy)
    analytics.record('fork')
    result = _detail(copy, data, user.id)
    result['city'] = copy.city  # 保留既有字段，兼容老客户端
    return result

@router.post('/api/trips/{trip_id}/collaborators/invite')
def invite_collaborator(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """生成协作邀请令牌（只存哈希）。"""
    row = get_trip(trip_id, user, db)
    token = new_token(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)).isoformat()
    db.add(TripInvite(trip_id=row.id, token_hash=hash_token(token), created_at=amap.now(),
                      expires_at=expires_at))
    db.commit()
    return {'token': token, 'expires_at': expires_at}

@router.delete('/api/trips/{trip_id}/invites')
def revoke_invites(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """撤销该行程全部未用邀请（仅 owner）：旧链接立即失效，需要时可重新生成。"""
    row = get_trip(trip_id, user, db)
    result = db.execute(delete(TripInvite).where(TripInvite.trip_id == row.id))
    db.commit()
    return {'ok': True, 'revoked': max(result.rowcount or 0, 0)}

@router.post('/api/collaborators/accept')
def accept_collaboration(body: ShareAccess, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """凭邀请令牌成为可编辑协作者：令牌一次性，接受即作废。"""
    token_hash = hash_token(body.token)
    invite = db.scalar(select(TripInvite).where(TripInvite.token_hash == token_hash))
    if not invite:
        raise HTTPException(404, '邀请链接无效或已被移除。')
    row = db.scalar(select(Trip).where(Trip.id == invite.trip_id, Trip.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '该行程已删除。')
    if _invite_expired(invite):
        raise HTTPException(410, '邀请链接已过期，请让行程创建者重新生成邀请。')
    # owner 自己点邀请链接没有意义；提示后保留令牌，仍可发给别人。
    if user.id == row.user_id:
        raise HTTPException(422, '不能接受自己发起的邀请。')
    # 先原子领取邀请（DELETE ... RETURNING），再写成员：两个并发请求只有一个能删到这一行，
    # 后到的请求拿不到令牌，不会把不同账号同时加进同一份行程。
    try:
        claimed = db.execute(delete(TripInvite).where(
            TripInvite.id == invite.id, TripInvite.token_hash == token_hash)
            .returning(TripInvite.id)).first()
    except OperationalError:
        db.rollback()
        raise HTTPException(503, '邀请正在被处理，请稍后重试。')
    if not claimed:
        db.rollback()
        raise HTTPException(409, '邀请链接已被使用或已失效，请让行程创建者重新发送。')
    member = db.scalar(select(TripCollaborator).where(TripCollaborator.trip_id == row.id, TripCollaborator.user_id == user.id))
    if not member:
        db.add(TripCollaborator(trip_id=row.id, user_id=user.id, role='edit', created_at=amap.now()))
    try:
        db.commit()
    except IntegrityError:
        # 同一账号拿两张邀请并发接受：另一请求已加为成员，这里视为成功。
        db.rollback()
    except OperationalError:
        db.rollback()
        raise HTTPException(503, '邀请正在被处理，请稍后重试。')
    return {'trip_id': row.id, 'title': row.title, 'city': row.city}

@router.get('/api/trips/{trip_id}/collaborators')
def list_collaborators(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """成员列表：owner + 全部协作者。"""
    row = get_trip_member(trip_id, user, db)
    members = []
    owner = db.get(User, row.user_id)
    if owner:
        members.append({'user_id': owner.id, 'username': owner.username, 'role': 'owner'})
    # 一次 join 取回全部协作者用户名，避免按成员逐个 db.get 的 N+1。
    links = db.execute(
        select(User, TripCollaborator.role)
        .join(TripCollaborator, TripCollaborator.user_id == User.id)
        .where(TripCollaborator.trip_id == row.id)
        .order_by(TripCollaborator.id)
    ).all()
    members.extend({'user_id': member.id, 'username': member.username, 'role': role}
                   for member, role in links)
    return {'members': members}

@router.delete('/api/trips/{trip_id}/collaborators/{member_user_id}')
def remove_collaborator(trip_id: int, member_user_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """移除协作者（仅 owner，不能移除自己）。"""
    row = get_trip(trip_id, user, db)
    if member_user_id == row.user_id:
        raise HTTPException(422, '不能移除行程的创建者。')
    link = db.scalar(select(TripCollaborator).where(TripCollaborator.trip_id == row.id, TripCollaborator.user_id == member_user_id))
    if not link:
        raise HTTPException(404, '没有找到这位协作者。')
    db.delete(link)
    # 移除即失效：同事务清掉该行程的全部邀请，并吊销分享码；否则被移除的人拿旧码
    # 直接就能加回来，等于“移除”没有生效。其余协作者的成员关系不受影响。
    db.execute(delete(TripInvite).where(TripInvite.trip_id == row.id))
    row.join_code = None
    db.commit()
    return {'ok': True}

@router.delete('/api/trips/{trip_id}/members/me')
def leave_trip(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """协作者主动退出：删掉自己的授权行，随后该行程按 404 处理（与陌生人一致）。"""
    row = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '行程不存在')
    if row.user_id == user.id:
        raise HTTPException(422, '行程创建者不能退出协作。')
    link = db.scalar(select(TripCollaborator).where(TripCollaborator.trip_id == row.id, TripCollaborator.user_id == user.id))
    if not link:
        raise HTTPException(404, '行程不存在')
    db.delete(link)
    db.commit()
    return {'ok': True}

def _insert_trip(db: DBSession, user: User, data: dict) -> Trip:
    """两个创建入口共用：序列化并插入一行行程，提交后返回带 id 的行。"""
    req = data['request']
    row = Trip(user_id=user.id, city=req['city'],
               data=json.dumps(trip_places.for_storage(data), ensure_ascii=False))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

async def build_trip_preview(body: CreateTrip):
    # 真正的检索/排天/校验逻辑在 services/preview.py，HTTP 与 Harness 共用同一套实现。
    return await preview.build_preview(
        body.model_dump(mode='json', exclude={'conversation', 'initial_places'}),
        [item.model_dump(mode='json') for item in body.initial_places],
        body.conversation,
    )

@router.post('/api/planning/preview')
async def create_preview(body: CreateTrip):
    await asyncio.to_thread(analytics.record, 'generate_start')
    try:
        data = await build_trip_preview(body)
    except Exception:
        await asyncio.to_thread(analytics.record, 'generate_failure')
        raise
    await asyncio.to_thread(analytics.record, 'generate_success')
    return {'id': 0, 'title': None, 'version': 0, 'is_owner': True, 'is_public': False, **data}

@router.post('/api/trips', status_code=201)
async def create_trip(body: CreateTrip, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    await asyncio.to_thread(analytics.record, 'generate_start')
    try:
        data = await build_trip_preview(body)
    except Exception:
        await asyncio.to_thread(analytics.record, 'generate_failure')
        raise
    await asyncio.to_thread(analytics.record, 'generate_success')
    row = _insert_trip(db, user, data)
    await asyncio.to_thread(analytics.record, 'trip_save')
    return _detail(row, data, user.id)

@router.post('/api/trips/from-preview', status_code=201)
async def save_preview(body: SavePreview, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    if len(body.days) != body.request.days:
        raise HTTPException(422, '预览天数与旅行需求不一致。')
    days = [day.model_dump(mode='json') for day in body.days]
    backlog = [stop.model_dump(mode='json') for stop in body.backlog]
    stops = [stop for day in days for stop in day['stops']] + backlog
    ids = [stop['place']['id'] for stop in stops]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '预览中包含重复地点。')
    known = await amap.find_places(ids)
    if any(pid not in known for pid in ids):
        raise HTTPException(422, '部分地点暂时无法从高德核实，请稍后重试。')
    for stop in stops:
        stop['place'] = known[stop['place']['id']]
    req = body.request.model_dump(mode='json')
    await amap.update_routes(days, req['transport'], req['city'])
    data = {'request':req, 'days':days, 'backlog':backlog, 'conversation':[m.model_dump() for m in body.conversation], 'created_at':amap.now()}
    row = _insert_trip(db, user, data)
    await asyncio.to_thread(analytics.record, 'trip_save')
    return _detail(row, data, user.id)

@router.post('/api/planning/preview/assistant/stream')
async def preview_assistant(body: PreviewAssistant):
    from ..services import agent
    if len(body.days) != body.request.days:
        raise HTTPException(422, '预览天数与旅行需求不一致。')
    req = body.request.model_dump(mode='json')
    if body.place_notice:
        raise HTTPException(503, body.place_notice)
    days = [day.model_dump(mode='json') for day in body.days]
    backlog = [stop.model_dump(mode='json') for stop in body.backlog]
    history = [m.model_dump() for m in body.history]
    candidates, context = _assistant_inputs(days, backlog, history, body.message)
    state = {'message':body.message,'history':history,'trip_id':0,'city':req['city'],'transport':req['transport'],
             'request':req,'days':days,'backlog':backlog,'candidates':candidates,'context':context}
    # 与正式流一致：agent 迭代放进独立 task，外层按心跳间隔取事件；
    # 模型长时间思考时发注释行保活，避免被 60s 代理超时掐断。
    queue: asyncio.Queue = asyncio.Queue()

    async def drive() -> None:
        try:
            async for chunk in agent.run_stream(state):
                for item in chunk.get('events', []):
                    await queue.put(item)
        except ServiceError as exc:
            await queue.put({'kind':'error','message':str(exc)})
        except Exception:
            await queue.put({'kind':'error','message':'行程助手暂时不可用，请稍后再试。'})
        finally:
            await queue.put(None)

    # 预览流不落库；断流时由通用 SSE 编排取消后台 task。
    return sse.sse_response(queue, drive, heartbeat=SSE_HEARTBEAT_SECONDS)

@router.put('/api/trips/{trip_id}/days')
async def save_days(trip_id: int, body: UpdateDays, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    version = _check_version(row, body.version)
    data = await trip_places.refresh(_load_data(row.data))
    _require_places(data)
    if len(body.days) != data['request']['days']:
        raise HTTPException(422, '行程天数不能改变')
    known = {stop['place']['id']: stop['place'] for day in data['days'] for stop in day['stops']}
    known.update({stop['place']['id']: stop['place'] for stop in data.get('backlog', [])})
    old_stops = {stop['place']['id']: stop for day in data['days'] for stop in day['stops']}
    old_stops.update({stop['place']['id']: stop for stop in data.get('backlog', [])})
    days = [day.model_dump() for day in body.days]
    for index, day in enumerate(body.days):
        for field in ('start_time', 'end_time'):
            if field not in day.model_fields_set:
                days[index][field] = data['days'][index].get(field)
        # 老客户端不传时间字段时上面回填旧值；结束早于开始按次日计算（README 第 87 行），不再拦成 422。
    backlog = [stop.model_dump() for stop in body.backlog] if body.backlog is not None else data.get('backlog', [])
    incoming = [(days[i]['stops'], day.stops) for i, day in enumerate(body.days)]
    if body.backlog is not None:
        incoming.append((backlog, body.backlog))
    for stops, models in incoming:
        for stop, model in zip(stops, models):
            previous = old_stops.get(stop['place']['id'], {})
            for field in ('fixed_time', 'fixed_next_day'):
                if field not in model.model_fields_set and field in previous:
                    stop[field] = previous[field]
    seen = set()
    missing = []
    for stops in [*(day['stops'] for day in days), backlog]:
        for stop in stops:
            pid = stop['place']['id']
            if pid in seen:
                raise HTTPException(422, '同一个地点不能重复添加')
            seen.add(pid)
            if pid not in known:
                missing.append(stop['place'])
    if missing:
        # 新地点之间互不依赖：并发核实（最多 4 个在途），再按原顺序落回。
        semaphore = asyncio.Semaphore(amap.AMAP_BATCH_CONCURRENCY)

        async def lookup(place: dict) -> dict | None:
            async with semaphore:
                matches = await amap.search_places(data['request']['city'], place['name'])
            return next((p for p in matches if p['id'] == place['id']), None)

        found = await asyncio.gather(*(lookup(place) for place in missing))
        for place, match in zip(missing, found):
            if not match:
                raise HTTPException(422, '新增地点无法在当前城市核实，请重新搜索。')
            known[place['id']] = match
    for stops in [*(day['stops'] for day in days), backlog]:
        for stop in stops:
            stop['place'] = known[stop['place']['id']]
    await amap.update_routes(days, data['request']['transport'], row.city, data['days'])
    data['days'] = days
    data['backlog'] = backlog
    _save_data(db, row, data, version, user.username)
    db.refresh(row)
    await asyncio.to_thread(analytics.record, 'trip_save')
    return _detail(row, data, user.id)

