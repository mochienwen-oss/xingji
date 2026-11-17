"""需求：README.md:102 高德地点详情有 5 分钟进程内缓存；README.md:108 路线查询失败不会用直线代替，缺失显示未知。

这里覆盖 amap 服务层：
- route_between 的回退只能使用高德真实返回的另一交通方式，并如实标注 mode；
  非公交方式查不到、三种方式都查不到时保持 duration/distance 未知、polyline 为空。
- update_routes 复用旧路线，失败路段降级为空路线而不是伪造坐标。
- find_places 的进程内缓存：重复读只打一次高德、返回深拷贝、按 TTL 过期。
"""
import asyncio
import logging

import pytest

from backend.services import amap
from backend.services.errors import ServiceError

ORIGIN = {'id': '1', 'location': '120.10,30.20'}
DESTINATION = {'id': '2', 'location': '120.20,30.30'}


def walking_payload(duration='540', distance='700'):
    return {'route': {'paths': [{'duration': duration, 'distance': distance, 'steps': [
        {'polyline': '120.1,30.2;120.11,30.21;120.12,30.22'}]}]}}


@pytest.mark.anyio
@pytest.mark.parametrize('mode,path', [
    ('walking', '/v3/direction/walking'),
    ('driving', '/v3/direction/driving'),
])
async def test_non_transit_failure_stays_unknown_without_fabricated_line(monkeypatch, mode, path):
    calls = []

    async def response(endpoint, params):
        calls.append(endpoint)
        raise ServiceError('高德接口返回错误码 10001')

    monkeypatch.setattr(amap, 'amap', response)

    result = await amap.route_between(ORIGIN, DESTINATION, mode, '杭州')

    # 失败不回退、更不拿起点和终点拼直线：只查了本方式一次。
    assert calls == [path]
    assert result['mode'] == mode
    assert result['duration'] is None
    assert result['distance'] is None
    assert result['polyline'] == []


@pytest.mark.anyio
async def test_transit_error_falls_back_to_real_walking_route(monkeypatch):
    calls = []

    async def response(path, params):
        calls.append(path)
        if path == '/v3/direction/transit/integrated':
            raise ServiceError('高德接口返回错误码 10001')
        return walking_payload()

    monkeypatch.setattr(amap, 'amap', response)

    result = await amap.route_between(ORIGIN, DESTINATION, 'transit', '杭州')

    assert calls == ['/v3/direction/transit/integrated', '/v3/direction/walking']
    # 回退拿到的是高德真实的步行数据，mode 如实标注 walking。
    assert result['mode'] == 'walking'
    assert result['duration'] == 540
    assert result['distance'] == 700
    assert result['polyline'] == [[[120.1, 30.2], [120.11, 30.21], [120.12, 30.22]]]


@pytest.mark.anyio
async def test_transit_with_duration_but_no_polyline_does_not_fall_back(monkeypatch):
    calls = []

    async def response(path, params):
        calls.append(path)
        return {'route': {'transits': [{'duration': '900', 'distance': '0', 'segments': []}]}}

    monkeypatch.setattr(amap, 'amap', response)

    result = await amap.route_between(ORIGIN, DESTINATION, 'transit', '杭州')

    # 有真实耗时就不算缺失；空折线只意味着地图画不出线，不能拿步行/驾车顶替公交耗时。
    assert calls == ['/v3/direction/transit/integrated']
    assert result['mode'] == 'transit'
    assert result['duration'] == 900
    assert result['distance'] is None
    assert result['polyline'] == []


@pytest.mark.anyio
async def test_transit_all_fallbacks_empty_keeps_unknown(monkeypatch, caplog):
    calls = []

    async def response(path, params):
        calls.append(path)
        return {'route': {}}

    monkeypatch.setattr(amap, 'amap', response)

    with caplog.at_level(logging.INFO):
        result = await amap.route_between(ORIGIN, DESTINATION, 'transit', '杭州')

    assert calls == ['/v3/direction/transit/integrated',
                     '/v3/direction/walking', '/v3/direction/driving']
    assert result['mode'] == 'transit'
    assert result['duration'] is None
    assert result['distance'] is None
    assert result['polyline'] == []
    assert 'amap route empty origin=1 destination=2 mode=transit' in caplog.text


@pytest.mark.anyio
async def test_update_routes_reuses_unchanged_segments(monkeypatch):
    places = [{'id': str(index), 'location': f'120.1{index},30.2{index}'} for index in range(3)]
    day = {'stops': [{'place': place} for place in places]}
    old = {'stops': [{'place': places[0]}, {'place': places[1]}], 'routes': [
        {'origin': '0', 'destination': '1', 'mode': 'walking', 'duration': 600,
         'distance': 800, 'polyline': [[[120.1, 30.2], [120.11, 30.21]]], 'source_time': 't'},
    ]}
    calls = []

    async def route(a, b, mode, city):
        calls.append((a['id'], b['id']))
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 300,
                'distance': 400, 'polyline': [], 'source_time': 't'}

    monkeypatch.setattr(amap, 'route_between', route)

    await amap.update_routes([day], 'walking', '杭州', old_days=[old])

    # 未变化的 0→1 段直接复用，只有新增的 1→2 段重新查。
    assert calls == [('1', '2')]
    assert day['routes'][0]['duration'] == 600
    assert day['routes'][1]['duration'] == 300
    assert [route['origin'] for route in day['routes']] == ['0', '1']


@pytest.mark.anyio
async def test_update_routes_degrades_failed_segment_to_unknown(monkeypatch):
    places = [{'id': str(index), 'location': f'120.1{index},30.2{index}'} for index in range(3)]
    day = {'stops': [{'place': place} for place in places]}

    async def route(a, b, mode, city):
        if (a['id'], b['id']) == ('0', '1'):
            raise ServiceError('高德接口返回错误码 10001')
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 300,
                'distance': 400, 'polyline': [[[120.1, 30.2], [120.12, 30.22]]], 'source_time': 't'}

    monkeypatch.setattr(amap, 'route_between', route)

    await amap.update_routes([day], 'walking', '杭州')

    # 失败段保留位置并显示待定，另一段照常返回；不伪造直线。
    assert day['routes'][0]['duration'] is None
    assert day['routes'][0]['distance'] is None
    assert day['routes'][0]['polyline'] == []
    assert day['routes'][0]['origin'] == '0' and day['routes'][0]['destination'] == '1'
    assert day['routes'][1]['duration'] == 300
    assert day['routes'][1]['polyline'] == [[[120.1, 30.2], [120.12, 30.22]]]


def _detail_handler(calls):
    async def response(path, params):
        assert path == '/v5/place/detail'
        calls.append(params['id'])
        return {'pois': [
            {'id': pid, 'name': f'地点{pid}', 'location': '120.15,30.26'}
            for pid in params['id'].split('|')
        ]}
    return response


@pytest.mark.anyio
async def test_place_details_are_cached_within_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(amap, 'amap', _detail_handler(calls))

    first = await amap.find_places(['1', '2'])
    second = await amap.find_places(['2', '1'])

    # README.md:102：同一份地点详情在缓存窗口内只向高德请求一次。
    assert calls == ['1|2']
    assert first == second
    assert set(first) == {'1', '2'}


@pytest.mark.anyio
async def test_cached_places_are_returned_as_copies(monkeypatch):
    calls = []
    monkeypatch.setattr(amap, 'amap', _detail_handler(calls))

    first = await amap.find_places(['1'])
    first['1']['name'] = '被调用方篡改'
    first['1']['photos'].append({'title': 'x', 'url': 'https://example.com/x.jpg'})

    second = await amap.find_places(['1'])

    assert calls == ['1']
    assert second['1']['name'] == '地点1'
    assert second['1']['photos'] == []


@pytest.mark.anyio
async def test_place_cache_expires_after_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(amap, 'amap', _detail_handler(calls))
    monkeypatch.setattr(amap, 'AMAP_PLACE_CACHE_SECONDS', 0.05)

    await amap.find_places(['1'])
    await asyncio.sleep(0.08)
    await amap.find_places(['1'])

    assert calls == ['1', '1']


@pytest.mark.anyio
async def test_zero_ttl_disables_place_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(amap, 'amap', _detail_handler(calls))
    monkeypatch.setattr(amap, 'AMAP_PLACE_CACHE_SECONDS', 0)

    await amap.find_places(['1'])
    await amap.find_places(['1'])

    assert calls == ['1', '1']
    assert '1' not in amap._place_cache


@pytest.mark.anyio
async def test_place_cache_window_uses_configured_ttl(monkeypatch):
    if amap.AMAP_PLACE_CACHE_SECONDS <= 0:
        pytest.skip('当前环境关闭了地点缓存')
    calls = []
    monkeypatch.setattr(amap, 'amap', _detail_handler(calls))

    await amap.find_places(['1'])

    expires_at = amap._place_cache['1'][0]
    remaining = expires_at - asyncio.get_running_loop().time()
    assert remaining == pytest.approx(amap.AMAP_PLACE_CACHE_SECONDS, abs=2)


@pytest.mark.anyio
async def test_failed_detail_batch_does_not_drop_other_places(monkeypatch):
    calls = []

    async def response(path, params):
        ids = params['id'].split('|')
        calls.append(params['id'])
        if '10' in ids:
            raise ServiceError('高德接口返回错误码 10001')
        return {'pois': [{'id': pid, 'name': f'地点{pid}', 'location': '120.15,30.26'}
                         for pid in ids]}

    monkeypatch.setattr(amap, 'amap', response)

    ids = [str(index) for index in range(12)]
    result = await amap.find_places(ids)

    # 一批失败只丢这一批：其余地点仍然返回，缺失由调用方显示未知。
    assert len(calls) == 2
    assert set(result) == {str(index) for index in range(10)}
    assert '10' not in result and '11' not in result
