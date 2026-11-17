"""三级可见性与公开面脱敏的接口契约。"""
from tests.conftest import login


def _place(pid, name, address):
    return {'id': pid, 'name': name, 'address': address, 'location': f'120.{pid},30.{pid}',
            'city': '杭州', 'opentime': '', 'cost': '', 'source_time': ''}


def test_visibility_three_modes_and_share_status(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    tid = trip['id']

    status = c.get(f'/api/trips/{tid}/share-status')
    assert status.status_code == 200
    assert status.json() == {'visibility': 'private', 'is_public': False, 'link_active': False}

    linked = c.put(f'/api/trips/{tid}/visibility', json={'mode': 'link'})
    assert linked.status_code == 200, linked.text
    body = linked.json()
    assert body['visibility'] == 'link' and body['link_active'] and body['is_public'] is False
    assert body['token'], '首次切到仅链接应直接拿到可发送的 token'
    assert c.get(f'/api/trips/{tid}/share-status').json()['visibility'] == 'link'
    # 已有有效链接时再切「仅链接」不重复生成
    again = c.put(f'/api/trips/{tid}/visibility', json={'mode': 'link'}).json()
    assert again['visibility'] == 'link' and 'token' not in again

    public = c.put(f'/api/trips/{tid}/visibility', json={'mode': 'public'}).json()
    assert public['visibility'] == 'public' and public['is_public'] is True
    assert c.get(f'/api/trips/{tid}/share-status').json()['visibility'] == 'public'

    private = c.put(f'/api/trips/{tid}/visibility', json={'mode': 'private'}).json()
    assert private == {'visibility': 'private', 'is_public': False, 'link_active': False}
    assert c.get(f'/api/trips/{tid}/share-status').json()['link_active'] is False
    # 老客户端 {is_public} 契约不变
    assert c.put(f'/api/trips/{tid}/visibility', json={'is_public': True}).json() == {'is_public': True}


def test_public_plaza_and_fork_are_redacted(client, monkeypatch):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1, 'start_date': '2027-03-15'}).json()
    tid = trip['id']
    hotel = _place('1', '杭州西湖国宾馆', '西湖区杨公堤18号')
    museum = _place('2', '浙江省博物馆', '孤山路25号')

    async def find_places(ids):
        return {p['id']: p for p in (hotel, museum) if p['id'] in ids}

    monkeypatch.setattr('backend.services.trip_places.amap.find_places', find_places)
    days = [{
        'stops': [{'place': hotel, 'duration': 60}, {'place': museum, 'duration': 90}],
        'start_time': '09:00',
    }]
    saved = c.put(f'/api/trips/{tid}/days', json={'days': days, 'backlog': []})
    assert saved.status_code == 200, saved.text
    assert c.put(f'/api/trips/{tid}/visibility', json={'mode': 'public'}).status_code == 200

    plaza = c.get('/api/plaza').json()['trips']
    card = next(item for item in plaza if item['id'] == tid)
    assert card['start_date'] is None, '广场匿名面不暴露具体出发日期'

    login(c, 'bob', 'password2')
    forked = c.post(f'/api/plaza/{tid}/fork')
    assert forked.status_code == 201, forked.text
    # 复制响应直接来自脱敏后的数据；再次 GET 会按地图源刷新地点详情，那是新主人的私有副本。
    copy = forked.json()
    assert copy['request']['start_date'] is None
    stops = copy['days'][0]['stops']
    # 新行程只持久化地点 id，公开复制响应不再带出任何精确地址。
    assert 'address' not in stops[0]['place']
    assert copy['conversation'] == []


def test_invalid_visibility_body_is_422(client):
    c, _ = client
    login(c)
    tid = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()['id']
    assert c.put(f'/api/trips/{tid}/visibility', json={}).status_code == 422
    assert c.put(f'/api/trips/{tid}/visibility', json={'mode': 'friends'}).status_code == 422
