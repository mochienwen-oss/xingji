import asyncio
import logging
import math

import httpx

from . import amap, geo_planning
from .errors import ServiceError

log = logging.getLogger(__name__)

# 单次优化的在途路段数与 amap.update_routes 共用同一个上限，避免把地图配额打满。


def geographic_distance(a: dict, b: dict) -> float:
    """两点直线距离（公里）；坐标缺失/非法时返回 inf，排到候选项末尾。"""
    first = a.get('place') if isinstance(a, dict) else None
    second = b.get('place') if isinstance(b, dict) else None
    distance = geo_planning.distance_km(first, second) if isinstance(first, dict) and isinstance(second, dict) else None
    return math.inf if distance is None else distance

async def suggest_route(day: dict, mode: str, city: str) -> dict:
    original = day['stops']
    if len(original) < 3:
        return {'improved':False, 'day':day, 'message':'至少需要三个地点才能尝试优化。'}
    if any(stop.get('fixed_time') for stop in original) and not day.get('start_time'):
        return {'improved':False, 'day':day, 'message':'请先设置当天开始时间，再比较包含固定事项的路线。'}
    # Generate one inexpensive candidate while retaining the first stop.
    remaining = original[1:].copy()
    ordered = [original[0]]
    while remaining:
        closest = min(remaining, key=lambda stop: geographic_distance(ordered[-1], stop))
        ordered.append(closest)
        remaining.remove(closest)
    if [s['place']['id'] for s in ordered] == [s['place']['id'] for s in original]:
        return {'improved':False, 'day':day, 'message':'未找到可比较的其他路线，保留当前顺序。'}
    semaphore = asyncio.Semaphore(amap.AMAP_BATCH_CONCURRENCY)

    async def route_segment(a: dict, b: dict) -> dict:
        async with semaphore:
            try:
                async with asyncio.timeout(amap.AMAP_TASK_TIMEOUT_SECONDS):
                    return await amap.route_between(a['place'], b['place'], mode, city)
            # 单段超时/传输失败只降级这一段（与 amap.update_routes 一致），交给下面的
            # 完整性检查统一报可读错误；漏出去的话 TimeoutError 会变成用户的 500。
            except (TimeoutError, ServiceError, httpx.HTTPError) as exc:
                log.warning('route opt segment failed origin=%s destination=%s error=%s',
                            a['place'].get('id'), b['place'].get('id'), exc)
                return amap.empty_route(a['place'], b['place'], mode)

    async def routes(stops):
        # 两条候选路线的各段一起并发查询；gather 保序，before/after 仍按原顺序返回。
        return list(await asyncio.gather(*(route_segment(a, b) for a, b in zip(stops, stops[1:]))))

    before, after = await asyncio.gather(routes(original), routes(ordered))
    if any(r['duration'] is None for r in before + after):
        raise ServiceError('部分路段无法获取交通时间，无法比较路线，原行程未改变。')
    before_seconds = sum(r['duration'] for r in before)
    after_seconds = sum(r['duration'] for r in after)
    if after_seconds >= before_seconds:
        return {'improved':False, 'day':day, 'message':'候选路线预计用时没有缩短，保留当前顺序。'}
    if day.get('start_time'):
        def minute(value):
            hour, minute_value = map(int, value.split(':'))
            return hour * 60 + minute_value
        def timing(stops, segments):
            current = minute(day['start_time'])
            late = set()
            for index, stop in enumerate(stops):
                if index:
                    current += math.ceil(segments[index - 1]['duration'] / 60)
                fixed = stop.get('fixed_time')
                if fixed:
                    fixed_minute = minute(fixed) + (1440 if stop.get('fixed_next_day') else 0)
                    if current > fixed_minute:
                        late.add(stop['place']['id'])
                    current = max(current, fixed_minute)
                current += stop['duration']
            return late, current
        before_late, before_end = timing(original, before)
        after_late, after_end = timing(ordered, after)
        deadline = minute(day['end_time']) if day.get('end_time') else None
        if deadline is not None and deadline <= minute(day['start_time']):
            deadline += 1440
        if after_late - before_late or (deadline is not None and before_end <= deadline < after_end):
            return {'improved':False, 'day':day, 'message':'候选路线会增加固定事项冲突或超出结束时间，保留当前顺序。'}
    return {'improved':True, 'day':{**day, 'stops':ordered, 'routes':after},
            'message':f'预计交通时间从 {math.ceil(before_seconds/60)} 分钟减少到 {math.ceil(after_seconds/60)} 分钟，请确认后保存。'}
