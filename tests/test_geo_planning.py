import pytest

from backend.services import geo_planning, planning


def place(pid, lon):
    return {'id':pid, 'name':f'景点{pid}', 'location':f'{lon},25.2'}


def stop(place):
    return {'place':place, 'duration':90, 'reason':'上午参观'}


def test_group_selected_stops_by_area_without_losing_or_duplicating():
    a, b, c, d = (place('a',110.00), place('b',110.02), place('c',110.70), place('d',110.72))
    days = [{'stops':[stop(a),stop(c)]},{'stops':[stop(b),stop(d)]}]
    result = geo_planning.group_days(days, '桂林三天喜欢自然风景')
    assert all(geo_planning.day_span(day) < 5 for day in result)
    assert {s['place']['id'] for day in result for s in day['stops']} == {'a','b','c','d'}
    assert [len(day['stops']) for day in result] == [2,2]
    assert days[0]['stops'][1]['place']['id'] == 'c'


def test_explicit_day_and_unavailable_location_are_not_reassigned():
    days = [{'stops':[stop(place('a',110)), stop(place('b',110.7))]},
            {'stops':[stop(place('c',110.02)),stop(place('d',110.72))]}]
    assert geo_planning.group_days(days, '第一天去景点a和景点b') == days
    days[0]['stops'][0]['place']['location'] = ''
    assert geo_planning.group_days(days, '') == days


def test_unresolved_required_place_alias_does_not_drop_selected_stops():
    places = [place('a',110),place('b',110.01)]
    assert geo_planning.protected_ids(places, {'a','b'}, [], '必去别名', '别名') == {'a','b'}


@pytest.mark.anyio
async def test_model_can_retry_single_day_far_apart_and_keep_explicit_place(monkeypatch):
    places = [place('a',110), place('b',110.7), place('c',110.02)]
    calls = []
    async def model(messages, max_tokens=4000):
        calls.append(messages[:])
        ids = ['a','b'] if len(calls)==1 else ['a','c']
        return {'days':[{'stops':[{'id':pid,'duration':90} for pid in ids]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    days = await planning.generate_plan({'city':'桂林','days':1}, places, explicit_place_ids=['a'])
    assert len(calls) == 2
    assert [s['place']['id'] for s in days[0]['stops']] == ['a','c']


@pytest.mark.anyio
async def test_retry_does_not_discard_original_explicit_destination(monkeypatch):
    places = [place('a',110), place('b',110.7), place('c',110.02)]
    calls = []
    async def model(messages, max_tokens=4000):
        calls.append(1)
        ids = ['a','b'] if len(calls)==1 else ['a','c']
        return {'days':[{'stops':[{'id':pid,'duration':90} for pid in ids]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    days = await planning.generate_plan({'city':'桂林','days':1}, places, explicit_place_ids=['b'])
    assert len(calls) == 2
    assert [s['place']['id'] for s in days[0]['stops']] == ['a','b']


def test_long_actual_route_is_reported_in_preview(client, monkeypatch):
    from backend.services import amap
    c, places = client
    async def generate(request, candidates, **kwargs):
        return [{'stops':[stop(places[0]), stop(places[1])]}]
    async def route(a, b, mode, city):
        return {'origin':a['id'],'destination':b['id'],'mode':mode,'duration':7200,'polyline':[], 'source_time':''}
    monkeypatch.setattr(planning, 'generate_plan', generate)
    monkeypatch.setattr(amap, 'route_between', route)
    result = c.post('/api/planning/preview',json={'city':'桂林','days':1}).json()
    assert '交通预计约 120 分钟' in result['place_notice']


def test_long_route_retries_and_keeps_the_faster_verified_option(client, monkeypatch):
    from backend.services import amap
    c, _ = client
    a,b,candidate = place('a',110), place('b',110.01), place('c',110.015)
    calls = []
    async def search(city, keyword): return [a,b,candidate]
    async def generate(request, candidates, **kwargs):
        calls.append(kwargs.get('traffic_feedback'))
        return [{'stops':[stop(a),stop(b if len(calls)==1 else candidate)]}]
    async def route(first, second, mode, city):
        return {'origin':first['id'],'destination':second['id'],'mode':mode,
                'duration':7200 if second['id']=='b' else 1200,'polyline':[], 'source_time':''}
    monkeypatch.setattr(amap, 'search_places', search)
    monkeypatch.setattr(amap, 'route_between', route)
    monkeypatch.setattr(planning, 'generate_plan', generate)
    result = c.post('/api/planning/preview',json={'city':'桂林','days':1}).json()
    assert len(calls) == 2 and calls[1][0]['minutes'] == 120
    assert result['days'][0]['stops'][1]['place']['id'] == 'c'
    assert result['days'][0]['routes'][0]['duration'] == 1200


def test_long_route_retry_cannot_remove_explicit_destination(client, monkeypatch):
    from backend.services import amap
    c, _ = client
    a,b,candidate = place('a',110), place('b',110.01), place('c',110.015)
    calls = []
    async def search(city, keyword): return [a,b,candidate]
    async def generate(request, candidates, **kwargs):
        calls.append(1)
        return [{'stops':[stop(a),stop(b if len(calls)==1 else candidate)]}]
    async def route(first, second, mode, city):
        return {'origin':first['id'],'destination':second['id'],'mode':mode,'duration':7200,'polyline':[], 'source_time':''}
    monkeypatch.setattr(amap, 'search_places', search)
    monkeypatch.setattr(amap, 'route_between', route)
    monkeypatch.setattr(planning, 'generate_plan', generate)
    result = c.post('/api/planning/preview',json={'city':'桂林','days':1,'must_visit':'景点b'}).json()
    assert len(calls) == 2
    assert result['days'][0]['stops'][1]['place']['id'] == 'b'
    assert '120 分钟' in result['place_notice']
