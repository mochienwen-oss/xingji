"""协同列表元数据：/api/trips/shared 的创建者/人数/在线，以及 /api/trips 的协作人数。"""
import json

from backend.services import live
from tests.conftest import login


def _create_trip(c, city='杭州'):
    resp = c.post('/api/trips', json={'city': city, 'days': 2, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()['id']


def _share(c, trip_id):
    resp = c.post(f'/api/trips/{trip_id}/join-code', json={'rotate': False})
    assert resp.status_code == 200, resp.text
    return resp.json()['code']


def _join(c, code):
    resp = c.post('/api/trips/join', json={'code': code})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _shared(c):
    resp = c.get('/api/trips/shared')
    assert resp.status_code == 200, resp.text
    return resp.json()['trips']


def _my_trips(c, deleted=False):
    resp = c.get('/api/trips', params={'deleted': deleted})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_shared_returns_owner_member_count_and_online(client):
    c, _ = client
    login(c)  # alice
    trip_id = _create_trip(c)
    code = _share(c, trip_id)
    # 自己的行程不算「协作行程」：shared 只看 TripCollaborator 行。
    assert _shared(c) == []

    login(c, 'bob', 'password2')
    _join(c, code)
    trips = _shared(c)
    assert len(trips) == 1
    item = trips[0]
    # 旧字段保持原样，只做加法。
    assert item['id'] == trip_id
    assert item['city'] == '杭州'
    assert item['role'] == 'edit'
    assert item['is_owner'] is False
    assert isinstance(item['is_public'], bool)
    assert 'title' in item  # 新建行程 title 可能为 null，旧字段只保证存在
    # 新增协同元数据：创建者、成员数（owner+协作者）、在线人数。
    assert item['owner'] == 'alice'
    assert item['member_count'] == 2
    assert item['online'] == 0


def test_shared_online_counts_live_connection(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _share(c, trip_id)
    login(c, 'bob', 'password2')
    _join(c, code)
    assert _shared(c)[0]['online'] == 0

    with c.websocket_connect(f'/api/trips/{trip_id}/live') as ws:
        hello = json.loads(ws.receive()['text'])
        assert hello['type'] == 'hello'
        # 房间里有 bob 的连接，列表里的 online 应立刻变成 1。
        item = _shared(c)[0]
        assert item['online'] == 1
        assert item['member_count'] == 2
    # 断开后房间被丢弃，在线人数回到 0。
    assert _shared(c)[0]['online'] == 0


def test_shared_excludes_soft_deleted_trip(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _share(c, trip_id)
    login(c, 'bob', 'password2')
    _join(c, code)
    assert len(_shared(c)) == 1

    login(c)  # 回到 alice 删除行程（软删除）
    assert c.delete(f'/api/trips/{trip_id}').status_code == 200
    login(c, 'bob', 'password2')
    assert _shared(c) == []


def test_trips_list_collaborator_count(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    assert _my_trips(c)[0]['collaborator_count'] == 0

    code = _share(c, trip_id)
    login(c, 'bob', 'password2')
    _join(c, code)
    login(c)
    # 列表页只看当前用户自己的行程：协作人数不含 owner。
    assert _my_trips(c)[0]['collaborator_count'] == 1

    # 删除列表形状不变（不带协同字段）。
    assert c.delete(f'/api/trips/{trip_id}').status_code == 200
    deleted = _my_trips(c, deleted=True)
    assert deleted
    assert 'collaborator_count' not in deleted[0]


def test_shared_online_is_zero_without_room(client):
    """online_count 不查库：没有房间就是 0，不会因行程不存在而报错。"""
    assert live.online_count(999999) == 0
