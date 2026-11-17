"""成品化第一轮：攻略成稿/采纳、灵感、广场/fork、协作邀请、权限矩阵。"""
import pytest

from backend.services.errors import ServiceError
from tests.conftest import login


@pytest.fixture
def trip_id(client):
    c, _ = client
    login(c)
    body = {'city': '杭州', 'days': 2, 'travelers': 2, 'transport': 'transit'}
    resp = c.post('/api/trips', json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()['id']


def test_guide_outline_resolves_places(client, trip_id, monkeypatch):
    c, places = client
    async def fake_outline(text, day_count):
        assert day_count == 2
        return [{'summary': '西湖一日', 'stops': [{'name': '景点1', 'why': '攻略首推'}]}]
    monkeypatch.setattr('backend.api.trips.planning.guide_outline', fake_outline)
    resp = c.post(f'/api/trips/{trip_id}/guide/outline', json={'text': '第一天去景点1'})
    assert resp.status_code == 200, resp.text
    day = resp.json()['days'][0]
    assert day['stops'][0]['place']['id'] == '1'
    assert len(day['stops'][0]['matches']) == 4


def test_guide_outline_validation_error(client, trip_id, monkeypatch):
    c, _ = client
    async def bad(text, day_count):
        raise ServiceError('攻略大纲未通过校验，请缩短文字后重试。')
    monkeypatch.setattr('backend.api.trips.planning.guide_outline', bad)
    resp = c.post(f'/api/trips/{trip_id}/guide/outline', json={'text': '任意'})
    assert resp.status_code == 503


def test_guide_adopt_appends_and_persists(client, trip_id):
    c, _ = client
    resp = c.post(f'/api/trips/{trip_id}/guide/adopt', json={'assignments': [{'day': 1, 'place_id': '4', 'duration': 60}]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['version'] == 1
    assert [s['place']['id'] for s in data['days'][0]['stops']] == ['1', '4']
    detail = c.get(f'/api/trips/{trip_id}').json()
    assert [s['place']['id'] for s in detail['days'][0]['stops']] == ['1', '4']


def test_guide_adopt_rejects_duplicate_and_bad_day(client, trip_id):
    c, _ = client
    first = c.post(f'/api/trips/{trip_id}/guide/adopt', json={'assignments': [{'day': 1, 'place_id': '4'}]})
    assert first.status_code == 200
    dup = c.post(f'/api/trips/{trip_id}/guide/adopt', json={'assignments': [{'day': 1, 'place_id': '4'}]})
    assert dup.status_code == 422
    assert '已在行程中' in dup.json()['detail']
    beyond = c.post(f'/api/trips/{trip_id}/guide/adopt', json={'assignments': [{'day': 3, 'place_id': '4'}]})
    assert beyond.status_code == 422


def test_visibility_and_plaza_and_fork(client, trip_id):
    c, _ = client
    # 未公开时广场看不到，fork 404
    login(c, 'bob', 'password2')
    assert c.get('/api/plaza').json()['trips'] == []
    assert c.post(f'/api/plaza/{trip_id}/fork').status_code == 404
    # owner 公开
    assert c.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert c.put(f'/api/trips/{trip_id}/visibility', json={'is_public': True}).json() == {'is_public': True}
    # 协作者不能改可见性（get_trip 仍 owner-only）
    login(c, 'bob', 'password2')
    assert c.put(f'/api/trips/{trip_id}/visibility', json={'is_public': False}).status_code == 404
    # 广场可见，fork 成功且归属 bob
    plaza = c.get('/api/plaza').json()['trips']
    assert any(item['id'] == trip_id for item in plaza)
    forked = c.post(f'/api/plaza/{trip_id}/fork')
    assert forked.status_code == 201
    copy = forked.json()
    assert copy['city'] == '杭州'
    mine = c.get('/api/trips').json()
    assert any(item['id'] == copy['id'] for item in mine)
    detail = c.get(f"/api/trips/{copy['id']}").json()
    assert detail['days'][0]['stops'], 'fork 后行程内容完整'


def test_fork_drops_private_conversation(client):
    """fork 只复制行程内容：原作者的 AI 对话（含预算/身体限制）不能泄露给新主人。"""
    c, _ = client
    login(c)
    messages = [{'role': 'user', 'content': '预算 3000，同行有老人，别排太满'}, {'role': 'assistant', 'content': '已按轻松节奏安排'}]
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1, 'conversation': messages}).json()
    assert trip['conversation'] == messages
    assert c.put(f"/api/trips/{trip['id']}/visibility", json={'is_public': True}).json() == {'is_public': True}
    login(c, 'bob', 'password2')
    forked = c.post(f"/api/plaza/{trip['id']}/fork")
    assert forked.status_code == 201, forked.text
    detail = c.get(f"/api/trips/{forked.json()['id']}").json()
    assert detail['conversation'] == []
    assert detail['days'][0]['stops'], '行程内容仍完整'


def test_collaboration_invite_accept_matrix(client, trip_id):
    c, _ = client
    login(c)
    token = c.post(f'/api/trips/{trip_id}/collaborators/invite').json()['token']
    # bob 接受；邀请是一次性令牌，同一链接再次使用即失效
    login(c, 'bob', 'password2')
    first = c.post('/api/collaborators/accept', json={'token': token})
    again = c.post('/api/collaborators/accept', json={'token': token})
    assert first.status_code == 200 and again.status_code == 404
    assert first.json()['trip_id'] == trip_id
    # 接受前后：404 → 可读
    # 成员能读详情与共享列表
    assert c.get(f'/api/trips/{trip_id}').status_code == 200
    shared = c.get('/api/trips/shared').json()['trips']
    assert any(item['id'] == trip_id for item in shared)
    # 成员不能删除/改名（owner-only 路径不变）
    assert c.delete(f'/api/trips/{trip_id}').status_code == 404
    assert c.patch(f'/api/trips/{trip_id}', json={'title': 'bob 改名'}).status_code == 404
    # 成员不能移除协作者/不能改可见性
    assert c.delete(f'/api/trips/{trip_id}/collaborators/1').status_code == 404
    # owner 看到成员列表，不能移除自己，能移除 bob
    login(c)
    members = c.get(f'/api/trips/{trip_id}/collaborators').json()['members']
    roles = {m['username']: m['role'] for m in members}
    assert roles == {'alice': 'owner', 'bob': 'edit'}
    assert c.delete(f'/api/trips/{trip_id}/collaborators/1').status_code == 422
    assert c.delete(f'/api/trips/{trip_id}/collaborators/2').json() == {'ok': True}
    assert len(c.get(f'/api/trips/{trip_id}/collaborators').json()['members']) == 1


def test_member_can_save_days(client, trip_id):
    c, _ = client
    login(c)
    token = c.post(f'/api/trips/{trip_id}/collaborators/invite').json()['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    detail = c.get(f'/api/trips/{trip_id}').json()
    body = {'days': detail['days'], 'backlog': detail.get('backlog', []), 'version': detail['version']}
    resp = c.put(f'/api/trips/{trip_id}/days', json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()['version'] == detail['version'] + 1
    # 保存后记录最近编辑人，冲突弹层据此说明线上版本来源
    assert resp.json()['last_edited_by'] == 'bob'
    assert resp.json()['last_edited_at']
    login(c)
    owner_view = c.get(f'/api/trips/{trip_id}').json()
    assert owner_view['last_edited_by'] == 'bob'


def test_member_save_days_version_conflict(client, trip_id):
    c, _ = client
    login(c)
    token = c.post(f'/api/trips/{trip_id}/collaborators/invite').json()['token']
    login(c, 'bob', 'password2')
    c.post('/api/collaborators/accept', json={'token': token})
    detail = c.get(f'/api/trips/{trip_id}').json()
    body = {'days': detail['days'], 'version': detail['version'] + 5}
    assert c.put(f'/api/trips/{trip_id}/days', json=body).status_code == 409


def test_inspiration_themes_and_route(client):
    c, places = client
    login(c)
    themes = c.get('/api/inspiration/themes', params={'city': '杭州'}).json()['themes']
    assert len(themes) >= 6 and all(t['label'] for t in themes)
    async def fake_route(city, label, desc):
        return {'title': '老城漫步', 'intro': '穿过三条老巷', 'stops': [
            {'name': '景点1', 'why': 'a'}, {'name': '景点2', 'why': 'b'}, {'name': '景点3', 'why': 'c'}, {'name': '景点4', 'why': 'd'}]}
    monkey = pytest.MonkeyPatch()
    monkey.setattr('backend.api.inspiration.planning.inspiration_route', fake_route)
    try:
        resp = c.post('/api/inspiration', json={'city': '杭州', 'theme_id': 'citywalk'})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data['title'] == '老城漫步' and len(data['stops']) == 4
        assert all(stop['place']['id'] for stop in data['stops'])
    finally:
        monkey.undo()


def test_inspiration_requires_min_stops(client, monkeypatch):
    c, _ = client
    login(c)
    async def thin(city, label, desc):
        return {'title': 't', 'intro': 'i', 'stops': [{'name': '不存在的地点', 'why': 'x'}]}
    async def empty(city, keyword):
        return []
    monkeypatch.setattr('backend.api.inspiration.planning.inspiration_route', thin)
    monkeypatch.setattr('backend.api.inspiration.amap.search_places', empty)
    resp = c.post('/api/inspiration', json={'city': '杭州', 'theme_id': 'night'})
    assert resp.status_code == 503


def test_inspiration_themes_are_guest_accessible(client):
    c, _ = client
    resp = c.get('/api/inspiration/themes', params={'city': '杭州'})
    assert resp.status_code == 200
    assert len(resp.json()['themes']) >= 6
