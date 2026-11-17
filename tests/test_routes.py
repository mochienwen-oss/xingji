import pytest
from backend.services import amap, route_opt
from backend.services.errors import ServiceError


@pytest.mark.anyio
async def test_route_distance_uses_map_data_and_transit_does_not_claim_walking_distance(monkeypatch):
    async def request(path, params):
        if path.endswith('integrated'):
            return {'route': {'distance': '800', 'transits': [{'duration': '900', 'segments': []}]}}
        return {'route': {'paths': [{'distance': '1200', 'duration': '600', 'steps': []}]}}
    monkeypatch.setattr(amap, 'amap', request)
    a = {'id': 'a', 'location': '110,25'}
    b = {'id': 'b', 'location': '111,25'}
    walking = await amap.route_between(a, b, 'walking', '桂林')
    transit = await amap.route_between(a, b, 'transit', '桂林')
    assert (walking['distance'], walking['duration']) == (1200, 600)
    assert (transit['distance'], transit['duration']) == (None, 900)


@pytest.mark.anyio
async def test_optimization_only_suggests_real_faster_routes(monkeypatch):
    stops = [{'place': {'id': name, 'location': f'{lon},25'}, 'duration': 90} for name, lon in [('a', 110), ('c', 112), ('b', 111)]]
    day = {'stops': stops, 'routes': [], 'start_time':'09:30', 'end_time':'18:00'}
    times = {('a', 'c'): 1200, ('c', 'b'): 600, ('a', 'b'): 300, ('b', 'c'): 300}
    async def route(a, b, mode, city):
        assert mode == 'driving'
        return {'duration': times[(a['id'], b['id'])]}
    monkeypatch.setattr(amap, 'route_between', route)
    result = await route_opt.suggest_route(day, 'driving', '桂林')
    assert result['improved']
    assert [s['place']['id'] for s in result['day']['stops']] == ['a', 'b', 'c']
    assert result['day']['start_time'] == '09:30' and result['day']['end_time'] == '18:00'
    assert [s['place']['id'] for s in day['stops']] == ['a', 'c', 'b']
    async def unavailable(a, b, mode, city): return {'duration': None}
    monkeypatch.setattr(amap, 'route_between', unavailable)
    with pytest.raises(ServiceError, match='无法比较路线'):
        await route_opt.suggest_route(day, 'driving', '桂林')


@pytest.mark.anyio
async def test_optimization_does_not_introduce_fixed_time_conflict(monkeypatch):
    stops = [
        {'place':{'id':'a','location':'110,25'},'duration':15},
        {'place':{'id':'c','location':'112,25'},'duration':15,'fixed_time':'09:30'},
        {'place':{'id':'b','location':'111,25'},'duration':120},
    ]
    day = {'stops':stops, 'routes':[], 'start_time':'09:00'}
    times = {('a','c'):600,('c','b'):1800,('a','b'):60,('b','c'):60}
    async def route(a,b,mode,city): return {'duration':times[(a['id'],b['id'])]}
    monkeypatch.setattr(amap, 'route_between', route)
    result = await route_opt.suggest_route(day, 'walking', '桂林')
    assert not result['improved'] and '固定事项' in result['message']
    no_start = await route_opt.suggest_route({**day,'start_time':None}, 'walking', '桂林')
    assert not no_start['improved'] and '开始时间' in no_start['message']
