"""Harness 编排器：模型只提议，编排器（这里）负责校验、调用工具和发事件。

一次 turn 的顺序：
1. 压缩上下文（必要时）→ 2. 读取长期记忆 → 3. 组装静态/场景/动态提示词
→ 4. intake 模型抽取意图与表单 → 5. 需要时检索高德并排天 → 6. 校验后发 plan
→ 7. done；若满足条件，后台 fork 一次记忆提取（不阻塞回答）。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from ...db import Session as DBSession
from ...schemas import HarnessTurnRequest, PlanForm
from .. import amap, planning, preview
from ..env import env_float, env_int
from ..errors import ServiceError
from ..llm import model_json
from . import events
from .context import KEEP_RECENT, compact, needs_compaction, summary_to_text, trim_history
from .prompts import registry

log = logging.getLogger("uvicorn.error")

Emit = Callable[[dict], Awaitable[None]]
MEMORY_EVERY_N_TURNS = env_int("HARNESS_MEMORY_EVERY_N_TURNS", 4, minimum=1)
MEMORY_MIN_TURN = env_int("HARNESS_MEMORY_MIN_TURN", 2, minimum=1)
PLAN_TICK_SECONDS = env_float("HARNESS_PLAN_TICK_SECONDS", 5.0, minimum=0.1)
MAX_PLAN_TICKS = 24

FORM_FIELDS = tuple(PlanForm.model_fields)
TEXT_FIELDS = ("interests", "budget", "must_visit")

_background_tasks: set[asyncio.Task] = set()


def _spawn(coro: Awaitable[Any]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def default_form() -> dict:
    return {
        "city": "",
        "days": 3,
        "start_date": None,
        "travelers": 2,
        "interests": "",
        "pace": "适中",
        "budget": "",
        "must_visit": "",
        "transport": "transit",
    }


def _clean_patch(raw: Any, base: dict) -> tuple[dict, dict]:
    """只接受 PlanForm 的字段；单个字段非法时丢掉该字段，不拖垮整轮对话。"""
    if not isinstance(raw, dict):
        return base, {}
    accepted: dict = {}
    current = dict(base)
    for key, value in raw.items():
        if key not in FORM_FIELDS or value is None:
            continue
        candidate = {**current, key: value}
        try:
            PlanForm(**candidate)
        except (ValidationError, TypeError):
            continue
        current = candidate
        accepted[key] = value
    return current, accepted


def _form_from_request(req: HarnessTurnRequest) -> dict:
    if req.form is None:
        return default_form()
    return req.form.model_dump(mode="json")


def _normalize_history(req: HarnessTurnRequest) -> list[dict]:
    history = [
        {"role": item.role, "content": item.content}
        for item in req.messages
        if isinstance(item.content, str) and item.content.strip()
    ]
    last = history[-1] if history else None
    if not last or last["role"] != "user" or last["content"].strip() != req.message.strip():
        history.append({"role": "user", "content": req.message.strip()})
    return trim_history(history, 40)


def _preview_places(preview_data: dict | None, saved: list[dict]) -> list[dict]:
    found: dict[str, dict] = {}
    for place in saved:
        if isinstance(place, dict) and place.get("id"):
            found[str(place["id"])] = place
    for day in (preview_data or {}).get("days", []):
        for stop in day.get("stops", []):
            place = stop.get("place") or {}
            if place.get("id"):
                found.setdefault(str(place["id"]), place)
    for stop in (preview_data or {}).get("backlog", []):
        place = stop.get("place") or {}
        if place.get("id"):
            found.setdefault(str(place["id"]), place)
    return list(found.values())


def _preview_summary(preview_data: dict | None) -> dict | None:
    if not preview_data:
        return None
    return {
        "city": (preview_data.get("request") or {}).get("city", ""),
        "days": len(preview_data.get("days") or []),
        "stops": sum(len(day.get("stops") or []) for day in preview_data.get("days") or []),
        "place_notice": preview_data.get("place_notice", ""),
    }


def _load_memory_sync(user_id: int) -> list[dict]:
    from .memory.store import MemoryStore

    with DBSession() as db:
        return MemoryStore(db).list_for_user(user_id, limit=8)


async def _load_memory(user: dict | None) -> list[dict]:
    if not user or not user.get("memory_enabled", True):
        return []
    try:
        # SQLite/SQLAlchemy 会话是同步 IO：放到线程里，别阻塞事件循环里的其它 SSE。
        return await asyncio.to_thread(_load_memory_sync, int(user["id"]))
    except Exception as exc:  # noqa: BLE001 - 记忆是增强，不影响主流程
        log.warning("memory load failed: %s", type(exc).__name__)
        return []


async def _is_trip_owner(trip_id: int | None, user: dict | None) -> bool:
    """行程改稿回包里的 is_owner 必须来自真实归属，不能对匿名/协作者自称 owner。"""
    if not trip_id or not user:
        return False

    def _lookup() -> bool:
        from ...db import Trip

        with DBSession() as db:
            row = db.get(Trip, trip_id)
            return bool(row is not None and row.user_id == int(user["id"]))

    try:
        return await asyncio.to_thread(_lookup)
    except Exception as exc:  # noqa: BLE001 - 查不到就当无权限，不阻塞改稿
        log.warning("trip owner lookup failed: %s", type(exc).__name__)
        return False


async def _maybe_extract_memory(user: dict | None, messages: list[dict], summary: dict | None, turn_count: int) -> None:
    if not user or not user.get("memory_enabled", True):
        return
    if turn_count < MEMORY_MIN_TURN or turn_count % MEMORY_EVERY_N_TURNS != 0:
        return
    from .memory.extractor import extract_memories
    from .memory.store import MemoryStore

    try:
        existing = await _load_memory(user)
        candidates = await extract_memories(messages, existing, summary)
        if not candidates:
            return
        # 模型调用期间不持有数据库连接；拿到候选后再开短事务写入（同步会话放线程）。
        def _save() -> None:
            with DBSession() as db:
                MemoryStore(db).apply(int(user["id"]), candidates)
                db.commit()

        await asyncio.to_thread(_save)
    except Exception as exc:  # noqa: BLE001 - 后台任务失败不能影响已发送的回答
        log.warning("memory extraction failed: %s", type(exc).__name__)


def _beijing_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M %z")


async def _intake(req: HarnessTurnRequest, form: dict, history: list[dict], summary: dict | None, memories: list[dict], emit: Emit) -> dict:
    dynamic = {
        "模式": req.mode,
        "当前表单": form,
        "已收藏地点": [p.name for p in req.places[:20] if p.name.strip()],
        "会话摘要": summary_to_text(summary) or None,
        "长期记忆": memories,
        "当前北京时间": _beijing_now(),
        "预览摘要": _preview_summary(req.preview),
    }
    prompt_messages = registry.build("explore_chat", dynamic=dynamic, history=history)
    fingerprints = registry.fingerprints("explore_chat", dynamic)
    log.debug("harness intake prompt static=%s scenario=%s dynamic=%s", fingerprints["static"], fingerprints["scenario"], fingerprints["dynamic"])
    def on_reply(text: str) -> None:
        # 回调是同步的：把增量排进同一事件循环，随后 await 一次即可保证先于 done 发出。
        _spawn(emit(events.delta(text)))

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            raw = await model_json(prompt_messages, 1200, on_reply=on_reply)
            if not isinstance(raw, dict):
                raise ValueError("intake shape")
            return raw
        except (ServiceError, ValueError, TypeError) as exc:
            last_error = exc
            if isinstance(exc, ServiceError) and getattr(exc, "status_code", 503) not in (502,):
                raise
            if attempt == 0:
                prompt_messages = [*prompt_messages, {"role": "user", "content": "请只返回约定的 JSON 对象，reply 字段放第一位。"}]
    raise ServiceError("AI 没有返回可用的理解结果，请换个说法重试。") from last_error


async def _await_with_ticks(coro: Awaitable[Any], emit: Emit, labels: list[str]) -> Any:
    """长时间工具调用期间持续发状态，避免前端 30 秒没有任何反馈。"""
    task = asyncio.create_task(coro)
    index = 0
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=PLAN_TICK_SECONDS)
            if done:
                return await task
            if index < MAX_PLAN_TICKS:
                await emit(events.event("status", text=labels[index % len(labels)]))
                index += 1
    except asyncio.CancelledError:
        task.cancel()
        raise


async def _run_plan(req: HarnessTurnRequest, form: dict, history: list[dict], memories: list[dict], emit: Emit) -> dict | None:
    city = str(form.get("city") or "").strip()
    if not city:
        return None
    await emit(events.phase("planning", f"正在检索{city}的真实地点"))
    request = {**form, "city": city}
    data = await _await_with_ticks(
        preview.build_preview(
            request,
            req.places,
            history,
            memories=memories,
            on_places=lambda found: _spawn(emit(events.places(found))),
        ),
        emit,
        [
            "正在用高德核实地点…",
            "正在把候选地点按天分组…",
            "正在核对每段交通…",
            "就快好了，正在检查路线是否顺路…",
        ],
    )
    await emit(events.plan({"id": 0, "title": None, "version": 0, "is_owner": True, "is_public": False, **data}))
    return data


async def _run_revise(req: HarnessTurnRequest, form: dict, history: list[dict], memories: list[dict],
                      user: dict | None, emit: Emit) -> dict | None:
    current = req.preview or {}
    days = current.get("days") or []
    if not days:
        return None
    request = current.get("request") or form
    if not isinstance(request, dict):
        request = form
    candidates = _preview_places(current, [p.model_dump(mode="json") for p in req.places])
    if not candidates:
        return None
    await emit(events.phase("revise", "正在按你的要求调整路线"))
    # 用户点名的新地点往往不在预览候选里：像已保存行程助手（trips.py）一样先检索再并入候选，
    # 否则 suggest_edits 只能拒绝 add/replace，回复还会虚构「已搜索」。
    city = str(request.get("city") or form.get("city") or "").strip()
    known_ids = {str(p.get("id")) for p in candidates}
    try:
        keywords = await planning.adjustment_keywords(req.message, days, current.get("backlog") or [])
    except ServiceError:
        keywords = []
    words: list[str] = []
    for keyword in keywords:
        keyword = str(keyword).strip()
        if city and keyword and keyword not in words:
            words.append(keyword)
    # 多个关键词并行搜索；状态与结果事件仍按关键词顺序发出，前端不会看到乱序。
    for keyword in words:
        await emit(events.event("status", text=f"正在搜索「{keyword}」…"))
    outcomes = await asyncio.gather(
        *(amap.search_places(city, keyword) for keyword in words),
        return_exceptions=True,
    )
    for keyword, outcome in zip(words, outcomes):
        if isinstance(outcome, ServiceError):
            log.warning("revise place search failed city=%s keyword=%s error=%s", city, keyword, outcome)
            continue
        if isinstance(outcome, BaseException):
            raise outcome
        fresh = [p for p in outcome if str(p.get("id")) not in known_ids]
        for place in fresh:
            known_ids.add(str(place["id"]))
            candidates.append(place)
        if fresh:
            await emit(events.places(fresh[:6], keyword=keyword))
    last_reply = {"text": ""}

    def on_reply(text: str, reset: bool = False) -> None:
        if reset:
            last_reply["text"] = ""
            _spawn(emit(events.event("assistant_reset")))
            return
        last_reply["text"] += text
        _spawn(emit(events.delta(text)))

    result = await planning.suggest_edits(
        request,
        candidates,
        req.message,
        days,
        current.get("backlog") or [],
        on_reply=on_reply,
        mode="trip" if req.mode == "trip" else "preview",
        trip_id=req.trip_id,
        version=req.version,
        memories=memories,
        history=history,
    )
    if not result.get("changed"):
        # 不在这里发 done：run_turn 统一收尾（带 turn_count/summary），避免同一轮出现两个 done。
        return {"reply": (result.get("reply") or "").strip() or "这条路线目前不需要调整。"}
    await emit(events.phase("route", "正在更新每一段交通"))
    try:
        await _await_with_ticks(
            amap.update_routes(result["days"], request.get("transport", "transit"), request.get("city", ""), days),
            emit,
            ["正在重新核验交通…", "路线衔接马上就好…"],
        )
    except ServiceError:
        pass  # 路线核验失败保留调整后的顺序，缺失的交通段会显示为待定。
    # 已保存行程改稿必须回填真实 id/version/归属和完整对话；否则前端会拿
    # id=0/version=0 去保存，覆盖错版本或新建一条重复行程。
    trip_id = req.trip_id if req.mode == "trip" and req.trip_id else None
    if trip_id:
        plan_id = trip_id
        plan_version = req.version if isinstance(req.version, int) else int(current.get("version") or 0)
        is_owner = await _is_trip_owner(trip_id, user)
        title = current.get("title") if isinstance(current.get("title"), str) else None
        is_public = bool(current.get("is_public"))
        created_at = current.get("created_at") if isinstance(current.get("created_at"), str) else amap.now()
    else:
        plan_id, plan_version, is_owner = 0, 0, True
        title, is_public, created_at = None, False, amap.now()
    saved_conversation = current.get("conversation")
    conversation = [
        {"role": item["role"], "content": item["content"]}
        for item in (saved_conversation if isinstance(saved_conversation, list) else history)
        if isinstance(item, dict) and isinstance(item.get("role"), str) and isinstance(item.get("content"), str)
    ]
    if not conversation or conversation[-1].get("content") != req.message:
        conversation.append({"role": "user", "content": req.message})
    data = {
        "id": plan_id,
        "title": title,
        "version": plan_version,
        "is_owner": is_owner,
        "is_public": is_public,
        "request": request,
        "days": result["days"],
        "backlog": result.get("backlog") or [],
        "conversation": conversation[-100:],
        "created_at": created_at,
        "reply": result.get("reply") or "路线已按你的要求调整。",
    }
    await emit(events.plan(data))
    return data


async def _validate_keywords(raw_keywords: Any, city: str, emit: Emit) -> list[dict]:
    if not city or not isinstance(raw_keywords, list):
        return []
    words = [x.strip() for x in raw_keywords if isinstance(x, str) and x.strip()][:2]
    found: dict[str, dict] = {}
    outcomes = await asyncio.gather(
        *(amap.search_places(city, word) for word in words),
        return_exceptions=True,
    )
    for outcome in outcomes:
        if isinstance(outcome, ServiceError):
            continue
        if isinstance(outcome, BaseException):
            raise outcome
        for place in outcome:
            found.setdefault(place["id"], place)
            if len(found) >= 6:
                break
    if found:
        await emit(events.places(list(found.values()), keyword="、".join(words)))
    return list(found.values())


async def run_turn(req: HarnessTurnRequest, user: dict | None, emit: Emit) -> None:
    form = _form_from_request(req)
    history = _normalize_history(req)
    summary = req.summary if isinstance(req.summary, dict) else None
    completed_turns = max(0, int(req.turn_count))
    turn_count = completed_turns + 1
    memories = await _load_memory(user)

    try:
        # 用已完成的轮次判断边界：客户端第 8 轮结束后发来的下一次请求，先进压缩再回答。
        if needs_compaction(history, turn_count=completed_turns, summary=summary):
            await emit(events.phase("compacting", "正在整理前面对话的要点"))
            summary = await compact(history, previous=summary, dynamic={"表单": form})
            await emit(events.summary_patch(summary, turn_count))

        # 压缩后只把最近几条原文带进提示词，其余信息由九段摘要承载；
        # 否则前端每轮都发完整 history，压缩就只是多调用一次模型。
        turn_history = trim_history(history, KEEP_RECENT) if summary else history
        raw = await _intake(req, form, turn_history, summary, memories, emit)
        reply = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
        reply = (reply or "").strip()[:2000]
        intent = raw.get("intent") if raw.get("intent") in ("plan", "chat", "clarify", "revise") else "chat"
        raw_patch = raw.get("form_patch") if isinstance(raw.get("form_patch"), dict) else raw.get("updates")
        next_form, patch = _clean_patch(raw_patch, form)
        if patch:
            await emit(events.form_patch(patch))
        city = str(next_form.get("city") or "").strip()
        if not city and isinstance(raw.get("form_patch"), dict):
            city = str(raw["form_patch"].get("city") or "").strip()
        question_text = raw.get("question") if isinstance(raw.get("question"), str) else ""

        has_preview = bool(req.preview and req.preview.get("days"))
        if intent == "revise" and has_preview and req.mode in ("preview", "trip"):
            data = await _run_revise(req, next_form, turn_history, memories, user, emit)
            if data and data.get("days"):
                await emit(events.done(
                    reply=data.get("reply") or "路线已更新。",
                    plan={k: v for k, v in data.items() if k != "reply"},
                    turn_count=turn_count,
                    summary=summary,
                ))
            else:
                await emit(events.done(reply=(data or {}).get("reply") or "这条路线目前不需要调整。", changed=False, turn_count=turn_count, summary=summary))
        elif intent == "plan" and city:
            data = await _run_plan(req, next_form, turn_history, memories, emit)
            if not data:
                raise ServiceError("还没有足够的地点来排路线，请补充想去的地方。", 422)
            stops = sum(len(day.get("stops") or []) for day in data.get("days") or [])
            days_count = len(data.get("days") or [])
            tail = f"路线排好了：{days_count} 天、{stops} 个地点。可以在地图上看，也可以继续说想怎么改。"
            final_reply = f"{reply.rstrip('。')}。{tail}" if reply else tail
            plan = {'id': 0, 'title': None, 'version': 0, 'is_owner': True, 'is_public': False, **data}
            await emit(events.done(reply=final_reply, plan=plan, turn_count=turn_count, summary=summary))
        elif intent in ("plan", "clarify") or not city:
            prompt_text = question_text or reply or "先告诉我目的地和大概几天，我就能开始排路线。"
            if not reply:
                reply = prompt_text
            await emit(events.question(prompt_text))
            await emit(events.done(reply=reply, question=prompt_text, turn_count=turn_count, summary=summary))
        else:
            await _validate_keywords(raw.get("place_keywords"), city, emit)
            await emit(events.done(reply=reply or "我在。可以继续说想去哪、怎么玩。", turn_count=turn_count, summary=summary))

        if user:
            _spawn(_maybe_extract_memory(user, history, summary, turn_count))
    except ServiceError as exc:
        await emit(events.error(str(exc), retryable=exc.status_code >= 500 or exc.status_code == 429))
        await emit(events.done(reply="", failed=True, turn_count=turn_count, summary=summary))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 任何未预期错误都要变成可读事件，不能静默断开
        log.exception("harness turn failed: %s", type(exc).__name__)
        await emit(events.error("这次没有排成功，已保留你的输入。可以重试或换个说法。"))
        await emit(events.done(reply="", failed=True, turn_count=turn_count, summary=summary))
