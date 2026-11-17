import logging

import pytest
from backend.services import amap
from backend.services.errors import ServiceError


def test_place_verification_marks_opening_hours():
    place = amap.place_from_poi({
        'id': '1', 'name': '西湖', 'location': '120.15,30.26',
        'business': {'opentime_week': '08:00-17:00'},
    })
    assert place['opentime'] == '08:00-17:00'
    assert place['verification']['status'] == 'verified'
    assert place['verification']['opening_hours'] is True
    assert place['verification']['source'] == 'amap'
    assert place['verification']['checked_at']


def test_place_without_opening_hours_is_needs_check():
    place = amap.place_from_poi({'id': '2', 'name': '无名小店', 'location': '120.15,30.26'})
    assert place['opentime'] == ''
    assert place['verification']['status'] == 'needs_check'
    assert place['verification']['opening_hours'] is False

@pytest.mark.anyio
async def test_route_failure_is_unknown(monkeypatch):
    async def fail(*args, **kwargs):
        raise ServiceError('unavailable')
    monkeypatch.setattr(amap, 'amap', fail)
    result = await amap.route_between({'id':'1','location':'120,30'}, {'id':'2','location':'121,31'}, 'walking', '杭州')
    assert result['duration'] is None
    assert result['polyline'] == []

@pytest.mark.anyio
async def test_transit_route_handles_missing_segments(monkeypatch):
    async def response(*args, **kwargs):
        return {'route': {'transits': [{'duration': '900', 'segments': [{'walking': [], 'bus': []}]}]}}
    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.route_between({'id':'1','location':'120,30'}, {'id':'2','location':'121,31'}, 'transit', '杭州')
    assert result['duration'] == 900
    assert result['polyline'] == []


@pytest.mark.anyio
async def test_transit_empty_falls_back_to_walking(monkeypatch):
    """公交无结果（如近距离）时改查步行：线画得出、时间是真的，mode 如实标注 walking。"""
    calls = []

    async def response(path, params):
        calls.append(path)
        if path == '/v3/direction/transit/integrated':
            return {'route': {'transits': []}}
        return {'route': {'paths': [{'duration': '540', 'distance': '700',
                                     'steps': [{'polyline': '120.1,30.2;120.11,30.21;120.12,30.22'}]}]}}

    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.route_between({'id': '1', 'location': '120.1,30.2'},
                                      {'id': '2', 'location': '120.12,30.22'}, 'transit', '杭州')
    assert result['mode'] == 'walking'
    assert result['duration'] == 540
    assert result['distance'] == 700
    assert result['polyline'] == [[[120.1, 30.2], [120.11, 30.21], [120.12, 30.22]]]
    assert calls == ['/v3/direction/transit/integrated', '/v3/direction/walking']


@pytest.mark.anyio
async def test_transit_ok_does_not_call_walking(monkeypatch):
    calls = []

    async def response(path, params):
        calls.append(path)
        return {'route': {'transits': [{'duration': '900', 'segments': []}]}}

    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.route_between({'id': '1', 'location': '120,30'}, {'id': '2', 'location': '121,31'}, 'transit', '杭州')
    assert result['duration'] == 900
    assert calls == ['/v3/direction/transit/integrated']


@pytest.mark.anyio
async def test_transit_and_walking_both_empty_stays_empty(monkeypatch):
    async def response(path, params):
        return {'route': {}}

    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.route_between({'id': '1', 'location': '120,30'}, {'id': '2', 'location': '121,31'}, 'transit', '杭州')
    assert result['mode'] == 'transit'
    assert result['duration'] is None
    assert result['polyline'] == []

@pytest.mark.anyio
async def test_transit_empty_walking_empty_falls_back_to_driving(monkeypatch, caplog):
    """公交、步行都查不到时再查驾车：城市内短距离通常有真实路线，避免整段无线可画。"""
    calls = []

    async def response(path, params):
        calls.append(path)
        if path == '/v3/direction/driving':
            return {'route': {'paths': [{'duration': '300', 'distance': '2500',
                                         'steps': [{'polyline': '120.1,30.2;120.12,30.24'}]}]}}
        return {'route': {'transits': [], 'paths': []}}

    monkeypatch.setattr(amap, 'amap', response)
    with caplog.at_level(logging.INFO):
        result = await amap.route_between({'id': '1', 'location': '120.1,30.2'},
                                          {'id': '2', 'location': '120.12,30.24'}, 'transit', '杭州')
    assert result['mode'] == 'driving'
    assert result['duration'] == 300
    assert result['distance'] == 2500
    assert result['polyline'] == [[[120.1, 30.2], [120.12, 30.24]]]
    assert calls == ['/v3/direction/transit/integrated', '/v3/direction/walking', '/v3/direction/driving']
    assert 'amap route fallback origin=1 destination=2 mode=transit fallback=walking hit=False' in caplog.text
    assert 'amap route fallback origin=1 destination=2 mode=transit fallback=driving hit=True' in caplog.text


@pytest.mark.anyio
async def test_transit_all_fallbacks_empty_stays_empty_and_warns(monkeypatch, caplog):
    """三种方式都空时保持原语义：空路线 + warning，不伪造任何坐标。"""
    calls = []

    async def response(path, params):
        calls.append(path)
        return {'route': {}}

    monkeypatch.setattr(amap, 'amap', response)
    with caplog.at_level(logging.INFO):
        result = await amap.route_between({'id': '1', 'location': '120,30'},
                                          {'id': '2', 'location': '121,31'}, 'transit', '杭州')
    assert result['mode'] == 'transit'
    assert result['duration'] is None
    assert result['distance'] is None
    assert result['polyline'] == []
    assert len(calls) == 3
    assert 'amap route fallback origin=1 destination=2 mode=transit fallback=walking hit=False' in caplog.text
    assert 'amap route fallback origin=1 destination=2 mode=transit fallback=driving hit=False' in caplog.text
    assert 'amap route empty origin=1 destination=2 mode=transit' in caplog.text


@pytest.mark.anyio
async def test_transit_polyline_skips_malformed_segments(monkeypatch):
    """折线只拼真实返回的步行/公交段：空段、类型异常、不足两点的折线都直接跳过。"""
    async def response(path, params):
        return {'route': {'transits': [{'duration': '1200', 'segments': [
            {'walking': {'steps': [{'polyline': '120.1,30.2;120.11,30.21'},
                                   {'polyline': '120.5'}]},
             'bus': {'buslines': []}},
            {'walking': None, 'bus': {'buslines': [
                {'polyline': '120.11,30.21;120.2,30.3'},
                {'polyline': '120.9,30.9;120.8,30.8'}]}},
            {'walking': {'steps': None}, 'bus': {'buslines': 'oops'}},
            'not-a-segment',
        ]}]}}

    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.route_between({'id': '1', 'location': '120.1,30.2'},
                                      {'id': '2', 'location': '120.2,30.3'}, 'transit', '杭州')
    assert result['duration'] == 1200
    # 每段只取实际乘坐的第一条公交线，单点和无效折线不画。
    assert result['polyline'] == [[[120.1, 30.2], [120.11, 30.21]],
                                  [[120.11, 30.21], [120.2, 30.3]]]
    # 公交的 route.distance 是起终点步行距离，不能当总里程用。
    assert result['distance'] is None


@pytest.mark.anyio
async def test_nearby_uses_amap_around_and_validates_places(monkeypatch):
    calls = []
    async def response(path, params):
        calls.append((path, params))
        return {'pois':[{'id':'1','name':'地点','location':'110.1,25.2'}, {'id':'2','name':'缺坐标'}]}
    monkeypatch.setattr(amap, 'amap', response)
    result = await amap.nearby_places('桂林', '110.1,25.1', '餐厅')
    assert [place['id'] for place in result] == ['1']
    assert calls[0][0] == '/v5/place/around'
    assert calls[0][1]['location'] == '110.1,25.1' and calls[0][1]['radius'] == 2000

@pytest.mark.anyio
async def test_place_queries_request_and_parse_photos(monkeypatch):
    calls = []
    async def response(path, params):
        calls.append((path, params))
        return {'pois': [{'id': '1', 'name': '景点', 'location': '110.1,25.2',
                          'business': {'cost': '88'}, 'photos': [{'title': '景色', 'url': 'https://example.com/a.jpg'}, {'url': []}]}]}
    monkeypatch.setattr(amap, 'amap', response)
    text = await amap.search_places('桂林', '景点')
    await amap.nearby_places('桂林', '110.1,25.1', '景点')
    details = await amap.find_places(['1'])
    assert all(call[1]['show_fields'] == 'business,photos' for call in calls)
    assert text[0]['photos'] == [{'title': '景色', 'url': 'https://example.com/a.jpg'}]
    assert details['1']['cost'] == '88'

@pytest.mark.anyio
async def test_discover_search_uses_radius_and_weight(monkeypatch):
    calls = []
    async def response(path, params):
        calls.append((path, params))
        return {'pois': [{'id': '1', 'name': '景点', 'location': '110.1,25.2', 'distance': '1234', 'photos': []}]}
    monkeypatch.setattr(amap, 'amap', response)
    results = await amap.discover_nearby(110.1, 25.2, 3000)
    assert calls[0][0] == '/v5/place/around'
    assert calls[0][1]['radius'] == 3000 and calls[0][1]['sortrule'] == 'weight'
    assert calls[0][1]['types'] == '110000' and calls[0][1]['show_fields'] == 'business,photos'
    assert results[0]['distance'] == 1234

