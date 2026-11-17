"""需求：README.md:85 收藏的地点生成行程时再次核实；未安排进日程的地点保留在待规划池。

这里直接调用服务层 build_preview，用高德检索/模型排天/路线核验的桩覆盖需求边界：
- 收藏地点在当前城市核实不到时必须明确报错（422），不能静默丢弃；
- 候选地点不足、整城对不上时提示用户检查城市；
- 已核实但没排进日程的收藏地点进入 backlog；
- 长直线跨度、单段交通过长时给出 place_notice 提示（README.md:108 的降级提示）。
"""
import pytest

from backend.services import geo_planning, preview
from backend.services.errors import ServiceError


def place(pid, name, lon, lat, city='杭州市'):
    return {'id': pid, 'name': name, 'address': f'{name}路 1 号', 'location': f'{lon},{lat}', 'city': city}


def day(*places):
    return {'stops': [{'place': item, 'duration': 60} for item in places],
            'routes': [], 'start_time': '09:00', 'end_time': '18:00'}


def request(**overrides):
    base = {'city': '杭州市', 'days': 1, 'transport': 'walking',
            'must_visit': '', 'interests': '', 'budget': ''}
    base.update(overrides)
    return base


def install(monkeypatch, search, plan, routes=None):
    calls = {'search': [], 'plan': [], 'routes': []}

    async def fake_search(city, keyword):
        calls['search'].append((city, keyword))
        return search(city, keyword)

    async def fake_plan(req, places, **kwargs):
        calls['plan'].append({'request': req, 'places': list(places), 'kwargs': kwargs})
        return plan(req, places, **kwargs)

    async def fake_routes(days, mode, city):
        calls['routes'].append((mode, city))
        if routes is not None:
            routes(days)

    monkeypatch.setattr(preview.amap, 'search_places', fake_search)
    monkeypatch.setattr(preview.planning, 'generate_plan', fake_plan)
    monkeypatch.setattr(preview.amap, 'update_routes', fake_routes)
    return calls


@pytest.mark.anyio
async def test_saved_place_must_be_verifiable_in_requested_city(monkeypatch):
    saved = place('fav', '西湖', 120.15, 30.27)
    other = place('1', '河坊街', 120.16, 30.28)

    def search(city, keyword):
        return [] if keyword == '西湖' else [other]

    install(monkeypatch, search, lambda req, places, **kw: [day(other)])

    with pytest.raises(ServiceError) as info:
        await preview.build_preview(request(), [saved])

    assert info.value.status_code == 422
    assert str(info.value) == '收藏的地点“西湖”无法在当前城市核实，请检查目的地或移除该地点。'


@pytest.mark.anyio
async def test_not_enough_candidates_for_requested_days(monkeypatch):
    only = place('1', '河坊街', 120.16, 30.28)
    install(monkeypatch, lambda city, keyword: [only], lambda req, places, **kw: [day(only)])

    with pytest.raises(ServiceError) as info:
        await preview.build_preview(request(days=2), [])

    assert info.value.status_code == 422
    assert str(info.value) == '该城市可用地点不足，请检查城市名称或补充想去的地点。'


@pytest.mark.anyio
async def test_rejects_preview_when_every_candidate_is_in_another_city(monkeypatch):
    beijing = place('1', '天安门', 116.40, 39.90, city='北京市')
    install(monkeypatch, lambda city, keyword: [beijing], lambda req, places, **kw: [day(beijing)])

    with pytest.raises(ServiceError) as info:
        await preview.build_preview(request(), [])

    assert info.value.status_code == 422
    assert str(info.value) == '没有找到「杭州市」的城市内地点，请检查城市名称（建议使用中文城市名）。'


@pytest.mark.anyio
async def test_unplanned_saved_place_stays_in_backlog(monkeypatch):
    saved = place('fav', '西湖', 120.15, 30.27)
    chosen = place('1', '河坊街', 120.16, 30.28)

    def search(city, keyword):
        return [saved] if keyword == '西湖' else [chosen]

    memories = [{'id': 'm1', 'content': '喜欢步行'}]
    calls = install(monkeypatch, search, lambda req, places, **kw: [day(chosen)])

    data = await preview.build_preview(
        request(),
        [saved],
        [{'role': 'user', 'content': '我想去西湖'}, {'role': 'assistant', 'content': '好的'}],
        memories=memories,
    )

    assert data['backlog'] == [{'place': saved, 'duration': 90, 'reason': ''}]
    assert 'place_notice' not in data
    plan_call = calls['plan'][0]
    assert [item['id'] for item in plan_call['places']] == ['fav', '1']
    assert plan_call['kwargs']['instruction'] == '我想去西湖'
    assert plan_call['kwargs']['explicit_place_ids'] == ['fav']
    assert plan_call['kwargs']['memories'] == memories
    # 路线核验用的是请求里的交通方式和城市。
    assert calls['routes'] == [('walking', '杭州市')]


@pytest.mark.anyio
async def test_scheduled_saved_place_leaves_no_backlog(monkeypatch):
    saved = place('fav', '西湖', 120.15, 30.27)
    other = place('1', '河坊街', 120.16, 30.28)

    def search(city, keyword):
        return [saved] if keyword == '西湖' else [other]

    install(monkeypatch, search, lambda req, places, **kw: [day(saved, other)])

    data = await preview.build_preview(request(), [saved])

    assert data['backlog'] == []


@pytest.mark.anyio
async def test_warns_when_day_stops_are_too_far_apart(monkeypatch):
    """plan_compose.md:36 要求一天直线跨度不得超过 20 公里；超限要提示而不是静默打回。"""
    near = place('1', '河坊街', 120.15, 30.27)
    far = place('far', '故宫', 116.40, 39.90)
    install(monkeypatch, lambda city, keyword: [near, far], lambda req, places, **kw: [day(near, far)])

    data = await preview.build_preview(request(), [])

    span = geo_planning.day_span(day(near, far))
    assert span is not None and span > 20
    assert data['place_notice'] == f'第 1 天地点直线跨度约 {round(span)} 公里，建议核对后调整。'


@pytest.mark.anyio
async def test_warns_when_a_segment_is_very_long(monkeypatch):
    first = place('1', '河坊街', 120.15, 30.27)
    second = place('2', '灵隐寺', 120.16, 30.28)

    def routes(days):
        days[0]['routes'] = [{'origin': '1', 'destination': '2', 'mode': 'walking',
                              'duration': 5460, 'distance': 4200, 'polyline': [],
                              'source_time': '2026-11-17T00:00:00'}]

    calls = install(monkeypatch, lambda city, keyword: [first, second],
                    lambda req, places, **kw: [day(first, second)], routes)

    data = await preview.build_preview(request(), [])

    assert data['place_notice'] == '第 1 天有一段交通预计约 91 分钟，建议核对后调整。'
    # 两个候选都已被选中，没有更近的替代地点，不应触发二次排天。
    assert len(calls['plan']) == 1


@pytest.mark.anyio
async def test_partial_city_mismatch_still_previews(monkeypatch):
    """高德对部分关键词会回落到其它城市；只要有一处对得上就放行，不整体拒绝。"""
    local = place('1', '河坊街', 120.15, 30.27)
    beijing = place('2', '天安门', 120.17, 30.29, city='北京市')
    install(monkeypatch, lambda city, keyword: [local, beijing],
            lambda req, places, **kw: [day(local)])

    data = await preview.build_preview(request(days=2), [])

    assert data['days'][0]['stops'][0]['place']['id'] == '1'
