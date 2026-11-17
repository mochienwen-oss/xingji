"""需求：README.md:85 收藏地点生成时再次核实；未安排进日程的地点保留在待规划池。

覆盖 trip_places 服务层的两个职责：
- for_storage：新选择只落地点 id；旧快照里的完整地点按 id 复用，避免同一份详情在请求体里膨胀。
- refresh：打开行程时按 id 重新向高德核实；失败时保留地点顺序和用户填写内容，
  把地点标成不可用并给出提示（README.md:108 缺失显示未知）。
"""
import copy

import pytest

from backend.services import amap, trip_places
from backend.services.errors import ServiceError

PLACEHOLDER_NAME = '地点信息暂不可用'
PLACE_NOTICE = '部分地点暂时无法从高德获取，请稍后重新打开行程。地点顺序和用户填写的内容仍已保留。'


def make_place(pid, **overrides):
    place = {
        'id': pid, 'name': f'景点{pid}', 'address': f'地址{pid}', 'location': '120.15,30.26',
        'opentime': '08:00-17:00', 'cost': '60', 'source_time': '2026-01-01T00:00:00Z',
        'photos': [{'title': '图', 'url': 'https://example.com/a.jpg'}],
        'verification': {'status': 'verified', 'source': 'amap',
                         'checked_at': '2026-01-01T00:00:00Z', 'opening_hours': True},
    }
    place.update(overrides)
    return place


def make_trip():
    """生成后的行程快照：地点只有 id，完整详情留在旧快照里。"""
    return {
        'days': [
            {'start_time': '09:00', 'end_time': '18:00', 'stops': [
                {'place': {'id': '1'}, 'duration': 90, 'reason': '推荐'},
                {'place': {'id': '2'}, 'duration': 60, 'reason': '想去'},
            ]},
        ],
        'backlog': [{'place': {'id': '3'}, 'duration': 90, 'reason': ''}],
        'place_notice': '上一次的提示',
    }


def test_stops_walks_days_then_backlog():
    trip = make_trip()
    assert [stop['place']['id'] for stop in trip_places.stops(trip)] == ['1', '2', '3']


def test_for_storage_keeps_place_ids_only_for_new_selection():
    trip = make_trip()
    before = copy.deepcopy(trip)

    stored = trip_places.for_storage(trip)

    places = [stop['place'] for day in stored['days'] for stop in day['stops']]
    places += [stop['place'] for stop in stored['backlog']]
    assert places == [{'id': '1'}, {'id': '2'}, {'id': '3'}]
    # 生成时的过期提示不进入数据库。
    assert 'place_notice' not in stored
    # 顺序、停留时长和推荐理由原样保留。
    assert [stop['duration'] for stop in stored['days'][0]['stops']] == [90, 60]
    assert stored['days'][0]['stops'][0]['reason'] == '推荐'
    assert stored['days'][0]['start_time'] == '09:00' and stored['days'][0]['end_time'] == '18:00'
    # 不修改入参。
    assert trip == before


def test_for_storage_reuses_complete_places_from_original_snapshot():
    original = {
        'days': [{'stops': [
            {'place': make_place('1'), 'duration': 90},
            # 旧快照里只有 id 的地点，和「新选择」等价，不能当成完整详情复用。
            {'place': {'id': '2'}, 'duration': 60},
        ]}],
        'backlog': [{'place': make_place('3'), 'duration': 90}],
    }
    trip = make_trip()
    before = copy.deepcopy(trip)

    stored = trip_places.for_storage(trip, original)

    assert stored['days'][0]['stops'][0]['place'] == make_place('1')
    assert stored['days'][0]['stops'][1]['place'] == {'id': '2'}
    assert stored['backlog'][0]['place'] == make_place('3')
    # 深拷贝：改保存结果不能污染旧快照。
    stored['days'][0]['stops'][0]['place']['name'] = '改名'
    assert original['days'][0]['stops'][0]['place']['name'] == '景点1'
    assert trip == before


@pytest.mark.anyio
async def test_refresh_verifies_all_stops_from_amap(monkeypatch):
    trip = make_trip()
    before = copy.deepcopy(trip)
    captured = []
    fetched = {pid: make_place(pid, name=f'核实后的{pid}') for pid in ('1', '2', '3')}

    async def find_places(ids):
        captured.append(list(ids))
        return fetched

    monkeypatch.setattr(amap, 'find_places', find_places)

    result = await trip_places.refresh(trip)

    assert [stop['place']['name'] for stop in result['days'][0]['stops']] == ['核实后的1', '核实后的2']
    assert result['backlog'][0]['place']['name'] == '核实后的3'
    assert captured == [['1', '2', '3']]
    assert result['days'][0]['stops'][0]['duration'] == 90
    assert trip == before


@pytest.mark.anyio
async def test_refresh_degrades_every_stop_when_amap_is_unavailable(monkeypatch):
    trip = make_trip()
    before = copy.deepcopy(trip)

    async def find_places(ids):
        raise ServiceError('高德接口返回错误码 10001，请检查 Key 类型、接口权限和配额。')

    monkeypatch.setattr(amap, 'find_places', find_places)

    result = await trip_places.refresh(trip)

    stops = result['days'][0]['stops'] + result['backlog']
    for stop in stops:
        place = stop['place']
        assert place['name'] == PLACEHOLDER_NAME
        assert place['unavailable'] is True
        assert place['address'] == '' and place['location'] == ''
        assert place['opentime'] == '' and place['photos'] == []
        assert place['verification'] == {'status': 'unavailable', 'source': 'amap',
                                         'checked_at': '', 'opening_hours': False}
    # 地点顺序和用户填写的内容仍保留。
    assert [stop['place']['id'] for stop in stops] == ['1', '2', '3']
    assert [stop['duration'] for stop in stops] == [90, 60, 90]
    assert result['days'][0]['stops'][1]['reason'] == '想去'
    assert result['place_notice'] == PLACE_NOTICE
    assert trip == before


@pytest.mark.anyio
async def test_refresh_only_degrades_places_missing_from_amap(monkeypatch):
    trip = make_trip()

    async def find_places(ids):
        return {'2': make_place('2', name='核实后的2')}

    monkeypatch.setattr(amap, 'find_places', find_places)

    result = await trip_places.refresh(trip)

    first, second = result['days'][0]['stops']
    assert first['place']['name'] == PLACEHOLDER_NAME
    assert first['place']['unavailable'] is True
    assert second['place']['name'] == '核实后的2'
    assert 'unavailable' not in second['place']
    assert result['backlog'][0]['place']['name'] == PLACEHOLDER_NAME
    assert result['place_notice'] == PLACE_NOTICE


@pytest.mark.anyio
async def test_refresh_queries_each_place_id_once(monkeypatch):
    data = {
        'days': [{'stops': [
            {'place': {'id': '1'}, 'duration': 15, 'reason': ''},
            {'place': {'id': '1'}, 'duration': 15, 'reason': ''},
        ]}],
        'backlog': [{'place': {'id': '2'}, 'duration': 90, 'reason': ''}],
    }
    captured = []

    async def find_places(ids):
        captured.extend(ids)
        return {pid: make_place(pid) for pid in ids}

    monkeypatch.setattr(amap, 'find_places', find_places)

    result = await trip_places.refresh(data)

    # 同一地点在多天/待规划池重复出现时只查一次，顺序按首次出现。
    assert captured == ['1', '2']
    assert [stop['place']['name'] for stop in result['days'][0]['stops']] == ['景点1', '景点1']
    assert result['backlog'][0]['place']['name'] == '景点2'
