import asyncio
import logging
import os
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import httpx
from .env import env_float, env_int
from .errors import ServiceError
from .http_pool import shared_client

log = logging.getLogger('uvicorn.error')

AMAP_BATCH_CONCURRENCY = 4  # 地点详情/路线段的并发上限，避免高峰时把配额打满
AMAP_TASK_TIMEOUT_SECONDS = 20.0  # 单个批次的硬超时：慢批只丢自己，不拖垮整个请求
# 地点详情在 5 分钟内基本不变：同一次行程的多个协作者轮询、分享页刷新都复用
# 同一份结果，避免每个 GET 都把几十个地点重新打一遍高德配额。
AMAP_PLACE_CACHE_SECONDS = env_float('AMAP_PLACE_CACHE_SECONDS', 300.0, minimum=0.0)
AMAP_PLACE_CACHE_MAX = env_int('AMAP_PLACE_CACHE_MAX', 2000, minimum=0)
_place_cache: 'OrderedDict[str, tuple[float, dict]]' = OrderedDict()
# 缓存命中率是 /api/metrics 的核心观测项：命中下降说明高德配额会被重复消耗。
_place_cache_hits = 0
_place_cache_misses = 0

def reset_place_cache() -> None:
    """测试与配置热更新用：清空地点详情缓存与命中计数。"""
    global _place_cache_hits, _place_cache_misses
    _place_cache.clear()
    _place_cache_hits = 0
    _place_cache_misses = 0

def cache_stats() -> dict:
    """只读缓存统计；供 /api/metrics 暴露高德配额消耗趋势。"""
    return {'place_hits': _place_cache_hits, 'place_misses': _place_cache_misses,
            'place_entries': len(_place_cache), 'place_limit': AMAP_PLACE_CACHE_MAX}

def _cached_place(place_id: str, now: float) -> dict | None:
    item = _place_cache.get(place_id)
    if item is None:
        return None
    expires_at, place = item
    if expires_at <= now:
        _place_cache.pop(place_id, None)
        return None
    _place_cache.move_to_end(place_id)
    return place

def _store_place(place_id: str, place: dict, now: float) -> None:
    if AMAP_PLACE_CACHE_SECONDS <= 0 or AMAP_PLACE_CACHE_MAX <= 0:
        return
    _place_cache[place_id] = (now + AMAP_PLACE_CACHE_SECONDS, deepcopy(place))
    _place_cache.move_to_end(place_id)
    while len(_place_cache) > AMAP_PLACE_CACHE_MAX:
        _place_cache.popitem(last=False)

def now():
    return datetime.now(timezone.utc).isoformat()

# 高德个人 Key 的搜索类接口并发配额很小（实测并发 4 就会回 10021 CUQPS），
# 一次行程预览会并行搜多个关键词；这类错误是瞬时的，退避重试比直接让整页失败更合适。
AMAP_CUQPS_INFOCODE = '10021'
AMAP_MAX_ATTEMPTS = 3
AMAP_RETRY_BASE_SECONDS = 0.4

async def amap(path: str, params: dict) -> dict:
    key = os.getenv('AMAP_WEB_KEY')
    if not key:
        raise ServiceError('尚未配置高德 Web 服务 Key。')
    client = shared_client()
    transient = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                 httpx.RemoteProtocolError, httpx.NetworkError)
    try:
        # 网络抖动、上游 5xx、并发配额（10021）都按瞬时故障退避重试；
        # Key 错误、接口无权限等确定性错误立即失败，避免无谓放大配额消耗。
        for attempt in range(AMAP_MAX_ATTEMPTS):
            last_attempt = attempt == AMAP_MAX_ATTEMPTS - 1
            try:
                r = await client.get('https://restapi.amap.com' + path,
                                     params={**params, 'key': key}, timeout=20)
                if r.status_code in (429, 500, 502, 503, 504) and not last_attempt:
                    await asyncio.sleep(AMAP_RETRY_BASE_SECONDS * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
            except transient as exc:
                if not last_attempt:
                    log.warning('amap transient error endpoint=%s error=%s attempt=%d',
                                path, type(exc).__name__, attempt + 1)
                    await asyncio.sleep(AMAP_RETRY_BASE_SECONDS * (attempt + 1))
                    continue
                raise
            if data.get('status') == '1':
                log.debug('amap request endpoint=%s', path)
                return data
            code = str(data.get('infocode', ''))
            code = code if code.isdigit() else '未知'
            if code == AMAP_CUQPS_INFOCODE and not last_attempt:
                log.warning('amap concurrency limit endpoint=%s infocode=%s attempt=%d',
                            path, code, attempt + 1)
                await asyncio.sleep(AMAP_RETRY_BASE_SECONDS * (attempt + 1))
                continue
            if code == AMAP_CUQPS_INFOCODE:
                raise ServiceError('高德接口并发请求超出 Key 配额，请稍后重试。')
            raise ServiceError(f'高德接口返回错误码 {code}，请检查 Key 类型、接口权限和配额。')
    except httpx.ConnectError as exc:
        raise ServiceError('本地服务无法连接高德，请检查服务的网络访问权限。') from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceError('高德服务请求失败，请稍后重试。') from exc

def place_from_poi(poi: dict) -> dict | None:
    if not all(isinstance(poi.get(k), str) and poi[k] for k in ('id', 'name', 'location')):
        return None
    try:
        lon, lat = map(float, poi['location'].split(','))
        if not (73 <= lon <= 135 and 3 <= lat <= 54):
            return None
    except (ValueError, TypeError):
        return None
    business = poi.get('business') if isinstance(poi.get('business'), dict) else {}
    def val(value):
        return value if isinstance(value, str) else ''
    photos = poi.get('photos') if isinstance(poi.get('photos'), list) else []
    photos = [{'title': val(p.get('title')), 'url': val(p.get('url'))} for p in photos
              if isinstance(p, dict) and isinstance(p.get('url'), str) and p['url'].startswith(('https://', 'http://'))]
    distance = val(poi.get('distance'))
    checked_at = now()
    opentime = val(business.get('opentime_week') or business.get('opentime_today'))
    # 高德能给出地点详情，说明地点本身已被地图数据源确认；营业时间是更弱的一层，
    # 有 opentime 才算核验，没有就明确标成待确认，不用“未知”冒充已核验。
    verification = {'status': 'verified' if opentime else 'needs_check',
                    'source': 'amap', 'checked_at': checked_at,
                    'opening_hours': bool(opentime)}
    return {'id': poi['id'], 'name': poi['name'], 'address': val(poi.get('address')),
            'location': poi['location'], 'city': val(poi.get('cityname')),
            'opentime': opentime,
            'cost': val(business.get('cost')), 'photos': photos, 'source_time': checked_at,
            'verification': verification,
            'distance': int(distance) if distance.isdigit() else None}

async def discover_nearby(lon: float, lat: float, radius: int) -> list[dict]:
    data = await amap('/v5/place/around', {'location': f'{lon:.6f},{lat:.6f}', 'types': '110000',
        'radius': radius, 'sortrule': 'weight', 'page_size': 20, 'show_fields': 'business,photos'})
    return [p for poi in data.get('pois', []) if (p := place_from_poi(poi))]

async def city_center(city: str) -> dict | None:
    data = await amap('/v3/geocode/geo', {'address': city})
    for item in data.get('geocodes', []):
        if isinstance(item, dict) and isinstance(item.get('location'), str):
            try:
                lon, lat = map(float, item['location'].split(','))
                if 73 <= lon <= 135 and 3 <= lat <= 54:
                    return {'lon': lon, 'lat': lat, 'city': city}
            except (TypeError, ValueError):
                pass
    return None

async def search_places(city: str, keyword: str) -> list[dict]:
    data = await amap('/v5/place/text', {'keywords': keyword, 'region': city, 'city_limit': 'true', 'page_size': 20, 'show_fields': 'business,photos'})
    return [p for poi in data.get('pois', []) if (p := place_from_poi(poi))]

async def nearby_places(city: str, location: str, keyword: str) -> list[dict]:
    data = await amap('/v5/place/around', {'location': location, 'keywords': keyword,
        'region': city, 'city_limit': 'true', 'radius': 2000, 'sortrule': 'distance',
        'page_size': 10, 'show_fields': 'business,photos'})
    return [p for poi in data.get('pois', []) if (p := place_from_poi(poi))]

async def _find_batch(place_ids: list[str]) -> dict[str, dict]:
    data = await amap('/v5/place/detail', {'id': '|'.join(place_ids), 'show_fields': 'business,photos'})
    return {p['id']: p for poi in data.get('pois', []) if (p := place_from_poi(poi))}

async def find_places(place_ids: list[str]) -> dict[str, dict]:
    unique = list(dict.fromkeys(pid for pid in place_ids if pid))
    if not unique:
        return {}
    now = asyncio.get_running_loop().time()
    result: dict[str, dict] = {}
    missing: list[str] = []
    global _place_cache_hits, _place_cache_misses
    for place_id in unique:
        cached = _cached_place(place_id, now)
        if cached is None:
            _place_cache_misses += 1
            missing.append(place_id)
        else:
            _place_cache_hits += 1
            result[place_id] = deepcopy(cached)
    batches = [missing[offset:offset + 10] for offset in range(0, len(missing), 10)]
    if not batches:
        return result
    semaphore = asyncio.Semaphore(AMAP_BATCH_CONCURRENCY)

    async def guarded(batch: list[str]) -> dict[str, dict]:
        async with semaphore:
            try:
                async with asyncio.timeout(AMAP_TASK_TIMEOUT_SECONDS):
                    return await _find_batch(batch)
            # 单批失败只丢这一批：其余地点仍可用于行程，不让整页查询失败。
            except (TimeoutError, ServiceError, httpx.HTTPError) as exc:
                log.warning('amap find_places batch failed size=%d error=%s', len(batch), exc)
                return {}

    for batch_result in await asyncio.gather(*(guarded(batch) for batch in batches)):
        result.update(batch_result)
        for place in batch_result.values():
            _store_place(place['id'], place, now)
    return result

async def _route_between_once(origin: dict, destination: dict, mode: str, city: str) -> dict:
    result = {'origin': origin['id'], 'destination': destination['id'], 'mode': mode,
              'duration': None, 'distance': None, 'polyline': [], 'source_time': now()}
    try:
        params = {'origin': origin['location'], 'destination': destination['location']}
        if mode == 'transit':
            params.update({'city': city, 'cityd': city, 'strategy': 0})
        data = await amap('/v3/direction/' + {'walking': 'walking', 'driving': 'driving', 'transit': 'transit/integrated'}[mode], params)
        route = data.get('route')
        if not isinstance(route, dict):
            return result
        paths = route.get('transits' if mode == 'transit' else 'paths', [])
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            return result
        path = paths[0]
        if str(path.get('duration', '')).isdigit():
            result['duration'] = int(path['duration'])
        # Transit route.distance is documented as the origin-to-destination walking
        # distance, not the total transit distance, so do not label it as such.
        if mode != 'transit' and str(path.get('distance', '')).isdigit():
            result['distance'] = int(path['distance'])
        steps = path.get('steps', [])
        if not isinstance(steps, list):
            steps = []
        if mode == 'transit':
            # 公交折线由每段的步行步骤和实际乘坐的第一条线路拼成。高德对空字段的类型
            # 并不稳定（None/对象/字符串都出现过），这里宁可少拼一段，也不拼假坐标。
            steps = []
            segments = path.get('segments', [])
            for segment in segments if isinstance(segments, list) else []:
                if not isinstance(segment, dict):
                    continue
                walking = segment.get('walking')
                walking_steps = walking.get('steps') if isinstance(walking, dict) else None
                if isinstance(walking_steps, list):
                    steps.extend(step for step in walking_steps if isinstance(step, dict))
                bus = segment.get('bus')
                buslines = bus.get('buslines') if isinstance(bus, dict) else None
                if isinstance(buslines, list):
                    steps.extend(line for line in buslines[:1] if isinstance(line, dict))
        for step in steps:
            if not isinstance(step, dict):
                continue
            polyline = step.get('polyline', '')
            if isinstance(polyline, str):
                points = []
                for point in polyline.split(';'):
                    try:
                        lon, lat = map(float, point.split(','))
                        points.append([lon, lat])
                    except ValueError:
                        continue
                if len(points) > 1:
                    result['polyline'].append(points)
        return result
    except ServiceError:
        return result


def _route_is_empty(route: dict) -> bool:
    """duration 与 polyline 都没有，才算这一段真的没查到路线。"""
    return route['duration'] is None and not route['polyline']


async def route_between(origin: dict, destination: dict, mode: str, city: str) -> dict:
    result = await _route_between_once(origin, destination, mode, city)
    if not _route_is_empty(result):
        return result
    if mode == 'transit':
        # 公交对近距离、跨水面等地点组合经常返回空结果（接口状态仍是成功）：先改查步行，
        # 步行也空再查驾车（城市内短距离通常有真实驾车路线）。画出的线、耗时和
        # mode 都是高德真实数据，避免地图上凭空缺一段。
        for fallback in ('walking', 'driving'):
            alternative = await _route_between_once(origin, destination, fallback, city)
            log.info('amap route fallback origin=%s destination=%s mode=%s fallback=%s hit=%s',
                     origin['id'], destination['id'], mode, fallback,
                     not _route_is_empty(alternative))
            if not _route_is_empty(alternative):
                return alternative
    log.warning('amap route empty origin=%s destination=%s mode=%s',
                origin['id'], destination['id'], result['mode'])
    return result


def empty_route(origin: dict, destination: dict, mode: str) -> dict:
    """路段拿不到数据时的占位路线：只保留端点与交通方式，耗时/距离留空（显示为未知）。"""
    return {'origin': origin['id'], 'destination': destination['id'], 'mode': mode,
            'duration': None, 'distance': None, 'polyline': [], 'source_time': now()}

async def update_routes(days: list[dict], mode: str, city: str, old_days: list[dict] | None = None) -> None:
    previous = {}
    for day in old_days or []:
        for route in day.get('routes', []):
            # Do not preserve failures: an edit offers an opportunity to retry.
            if route.get('duration') is not None and 'distance' in route:
                previous[(route['origin'], route['destination'], route['mode'])] = route
    # 先占住可复用旧路线，只把真正要查的段放进并发任务；每段记住自己的 index。
    plans = []
    for day in days:
        pairs = list(zip(day['stops'], day['stops'][1:]))
        routes: list[dict | None] = [None] * len(pairs)
        pending = []
        for index, (first, second) in enumerate(pairs):
            a, b = first['place'], second['place']
            reusable = previous.get((a['id'], b['id'], mode))
            if reusable is not None:
                routes[index] = reusable
            else:
                pending.append(index)
        plans.append((day, pairs, routes, pending))
    semaphore = asyncio.Semaphore(AMAP_BATCH_CONCURRENCY)

    async def fetch(index: int, first: dict, second: dict, routes: list[dict | None]) -> None:
        a, b = first['place'], second['place']
        async with semaphore:
            try:
                async with asyncio.timeout(AMAP_TASK_TIMEOUT_SECONDS):
                    routes[index] = await route_between(a, b, mode, city)
            # 超时/失败只把这一段降级为空路线，保留段顺序，其余段照常返回。
            except (TimeoutError, ServiceError, httpx.HTTPError) as exc:
                log.warning('amap route segment failed origin=%s destination=%s error=%s', a['id'], b['id'], exc)
                routes[index] = empty_route(a, b, mode)

    await asyncio.gather(*(fetch(index, pairs[index][0], pairs[index][1], routes)
                           for _, pairs, routes, pending in plans for index in pending))
    for day, _, routes, _ in plans:
        day['routes'] = routes
