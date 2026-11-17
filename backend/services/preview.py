"""把已核实的候选地点排成可预览的行程。

这里不碰数据库、不认证；HTTP 端点、Harness 和测试共用同一套高德检索 + 模型排天 + 校验 + 路线核验逻辑。
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..services import amap, geo_planning, planning
from ..services.errors import ServiceError
from ..schemas import ChatMessage

CITY_SUFFIXES = ('特别行政区', '地区', '自治州', '市')


def _city_key(name: str) -> str:
    text = str(name or '').strip()
    for suffix in CITY_SUFFIXES:
        if text.endswith(suffix):
            return text[:-len(suffix)]
    return text


def _same_city(requested: str, actual: str) -> bool:
    # 高德用“杭州市”“恩施土家族苗族自治州”这类全称，用户输入可能是“杭州”“恩施”；
    # 归一后相等或前缀匹配都算同一城市，避免把自治州误判成另一个城市。
    wanted, found = _city_key(requested), _city_key(actual)
    if not wanted or not found:
        return False
    return (wanted == found
            or (len(wanted) >= 2 and found.startswith(wanted))
            or (len(found) >= 2 and wanted.startswith(found)))


async def build_preview(
    request: dict,
    initial_places: list[dict],
    conversation: list[dict] | list[ChatMessage] | None = None,
    *,
    memories: list[dict] | None = None,
    on_places: Callable[[list[dict]], None] | None = None,
) -> dict:
    req = dict(request)
    req["city"] = str(req.get("city") or "").strip()
    if not req["city"]:
        raise ServiceError("请填写目的地城市", 422)
    keywords = [x.strip() for x in str(req.get("must_visit") or "").replace("，", ",").split(",") if x.strip()][:5]
    keywords += [x.strip() for x in str(req.get("interests") or "").replace("，", ",").split(",") if x.strip()][:3]
    keywords += ["景点", "公园", "博物馆"]
    candidates: dict[str, dict] = {}
    verified_initial: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(amap.AMAP_BATCH_CONCURRENCY)

    async def search(keyword: str) -> list[dict]:
        async with semaphore:
            return await amap.search_places(req["city"], keyword)

    initial_items = list(initial_places or [])
    if initial_items:
        names = [item.get("name") if isinstance(item, dict) else getattr(item, "name", "") for item in initial_items]
        results = await asyncio.gather(*(search(str(name or "")) for name in names), return_exceptions=True)
        for item, name, matches in zip(initial_items, names, results):
            if isinstance(matches, BaseException):
                raise matches
            wanted_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
            match = next((place for place in matches if place["id"] == wanted_id), None)
            if not match:
                raise ServiceError(f"收藏的地点“{name}”无法在当前城市核实，请检查目的地或移除该地点。", 422)
            verified_initial[match["id"]] = match
            candidates[match["id"]] = match
    if on_places and verified_initial:
        # 用户收藏的地点先落图：渐进检索从「我选的地方」开始，而不是从零开始。
        on_places(list(verified_initial.values())[:24])
    keyword_results = await asyncio.gather(*(search(keyword) for keyword in keywords), return_exceptions=True)
    for keyword, matches in zip(keywords, keyword_results):
        if isinstance(matches, BaseException):
            raise matches
        for place in matches:
            candidates[place["id"]] = place
        if on_places:
            # 每核实完一个关键词就推送一次：前端地图上候选地点逐批出现。
            on_places(list(candidates.values())[:24])
    if len(candidates) < int(req.get("days") or 1):
        raise ServiceError("该城市可用地点不足，请检查城市名称或补充想去的地点。", 422)
    # 高德对无法识别的 region 会回落到默认城市（例如英文 Suzhou 返回北京景点）。
    # 只要有一处地点来自请求城市就放行；全部对不上时明确报错，绝不生成另一个城市的行程。
    city_mismatch = [place for place in candidates.values()
                     if place.get('city') and not _same_city(req['city'], place['city'])]
    if city_mismatch and len(city_mismatch) == len(candidates):
        raise ServiceError(f"没有找到「{req['city']}」的城市内地点，请检查城市名称（建议使用中文城市名）。", 422)

    history = []
    for message in conversation or []:
        if isinstance(message, ChatMessage):
            history.append(message.model_dump())
        elif isinstance(message, dict):
            history.append(message)
    instruction = "\n".join(str(m.get("content", "")) for m in history if m.get("role") == "user")
    days = await planning.generate_plan(
        req, list(candidates.values()), instruction=instruction, explicit_place_ids=list(verified_initial),
        memories=memories,
    )
    await amap.update_routes(days, req["transport"], req["city"])
    feedback = []
    selected = {stop["place"]["id"] for day in days for stop in day["stops"]}
    for index, day in enumerate(days):
        for route in day["routes"]:
            if route.get("duration") is not None and route["duration"] >= 5400:
                feedback.append({
                    "day": index + 1,
                    "origin": route["origin"],
                    "destination": route["destination"],
                    "minutes": round(route["duration"] / 60),
                })
    long_endpoints = {pid for route in feedback for pid in (route["origin"], route["destination"])}
    has_alternative = any(
        p["id"] not in selected and (distance := geo_planning.distance_km(stop["place"], p)) is not None and distance <= 5
        for day in days for stop in day["stops"] if stop["place"]["id"] in long_endpoints for p in candidates.values()
    ) if feedback else False
    constraints = " ".join(str(req.get(key, "")) for key in ("interests", "must_visit", "budget")) + " " + instruction
    spans = [geo_planning.day_span(day) for day in days]
    if feedback and has_alternative and not geo_planning.DAY_CONSTRAINT.search(constraints) and all(span is not None for span in spans):
        try:
            alternate = await planning.generate_plan(
                req,
                list(candidates.values()),
                instruction=instruction,
                explicit_place_ids=list(verified_initial),
                traffic_feedback=feedback,
                memories=memories,
            )
            alternate_ids = {stop["place"]["id"] for day in alternate for stop in day["stops"]}
            protected = geo_planning.protected_ids(
                list(candidates.values()), selected, list(verified_initial), constraints, str(req.get("must_visit") or "")
            )
            alternate_spans = [geo_planning.day_span(day) for day in alternate]
            if (
                (protected & selected) <= alternate_ids
                and len(alternate_ids) >= len(selected)
                and all(span is not None for span in alternate_spans)
                and max(alternate_spans, default=0) <= max(spans, default=0) + 1
            ):
                await amap.update_routes(alternate, req["transport"], req["city"])
                old_routes = [r for day in days for r in day["routes"]]
                new_routes = [r for day in alternate for r in day["routes"]]
                old_unknown = sum(r.get("duration") is None for r in old_routes)
                new_unknown = sum(r.get("duration") is None for r in new_routes)
                old_longest = max((r["duration"] for r in old_routes if r.get("duration") is not None), default=0)
                new_longest = max((r["duration"] for r in new_routes if r.get("duration") is not None), default=0)
                if new_unknown <= old_unknown and new_longest < old_longest:
                    days = alternate
        except ServiceError:
            pass  # 保留已通过校验的原方案，下面继续给出长路线提示。
    warnings = []
    for index, day in enumerate(days):
        span = geo_planning.day_span(day)
        longest = max((route["duration"] for route in day["routes"] if route.get("duration") is not None), default=0)
        if span is not None and span > 20:
            warnings.append(f"第 {index + 1} 天地点直线跨度约 {round(span)} 公里")
        if longest >= 5400:
            warnings.append(f"第 {index + 1} 天有一段交通预计约 {round(longest / 60)} 分钟")
    scheduled = {stop["place"]["id"] for day in days for stop in day["stops"]}
    backlog = [{"place": place, "duration": 90, "reason": ""} for pid, place in verified_initial.items() if pid not in scheduled]
    data = {
        "request": req,
        "days": days,
        "backlog": backlog,
        "conversation": history,
        "created_at": amap.now(),
    }
    if warnings:
        data["place_notice"] = "；".join(warnings) + "，建议核对后调整。"
    return data
