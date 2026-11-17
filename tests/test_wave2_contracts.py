"""Wave 2 契约闭环：trip 响应形状、guide/adopt 版本 CAS、一次性邀请、凭分享链接复制。"""
import json

from tests.conftest import login


def _create(c, **extra):
    body = {'city': '桂林', 'days': 2, **extra}
    resp = c.post('/api/trips', json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _flags(payload):
    """两个契约字段必须存在且是布尔值。"""
    assert isinstance(payload['is_owner'], bool)
    assert isinstance(payload['is_public'], bool)
    return payload['is_owner'], payload['is_public']


def test_trip_content_responses_expose_owner_and_visibility(client):
    c, _ = client
    login(c)
    trip = _create(c)
    assert _flags(trip) == (True, False)

    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert _flags(detail) == (True, False)

    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days': detail['days'], 'version': detail['version']})
    assert saved.status_code == 200, saved.text
    assert _flags(saved.json()) == (True, False)
    assert saved.json()['version'] == detail['version'] + 1

    adopted = c.post(f"/api/trips/{trip['id']}/guide/adopt",
                     json={'assignments': [{'day': 2, 'place_id': '3'}]})
    assert adopted.status_code == 200, adopted.text
    assert _flags(adopted.json()) == (True, False)
    assert adopted.json()['id'] == trip['id'] and adopted.json()['version'] == saved.json()['version'] + 1
    assert adopted.json()['days'][1]['stops'][-1]['place']['id'] == '3'

    preview = c.post('/api/planning/preview', json={'city': '桂林', 'days': 1})
    assert preview.status_code == 200, preview.text
    assert preview.json()['id'] == 0 and _flags(preview.json()) == (True, False)
    payload = {key: preview.json()[key] for key in ('request', 'days', 'backlog', 'conversation')}
    from_preview = c.post('/api/trips/from-preview', json=payload)
    assert from_preview.status_code == 201, from_preview.text
    assert _flags(from_preview.json()) == (True, False)

    # 公开只影响 is_public，不改变归属
    assert c.put(f"/api/trips/{trip['id']}/visibility", json={'is_public': True}).json() == {'is_public': True}
    assert _flags(c.get(f"/api/trips/{trip['id']}").json()) == (True, True)
    mine = next(item for item in c.get('/api/trips').json() if item['id'] == trip['id'])
    assert _flags(mine) == (True, True)

    # 广场 fork：副本对 bob 是私有 owner，且返回完整行程内容
    login(c, 'bob', 'password2')
    forked = c.post(f"/api/plaza/{trip['id']}/fork")
    assert forked.status_code == 201, forked.text
    copy = forked.json()
    assert _flags(copy) == (True, False)
    assert copy['city'] == '桂林' and copy['request']['city'] == '桂林'
    assert copy['days'] and copy['conversation'] == []


def test_collaborator_sees_is_owner_false_in_detail_and_shared_list(client):
    c, _ = client
    login(c)
    trip = _create(c)
    token = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200

    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert _flags(detail) == (False, False)

    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days': detail['days']})
    assert saved.status_code == 200, saved.text
    assert _flags(saved.json()) == (False, False)

    adopted = c.post(f"/api/trips/{trip['id']}/guide/adopt",
                     json={'assignments': [{'day': 1, 'place_id': '3'}]})
    assert adopted.status_code == 200, adopted.text
    assert _flags(adopted.json()) == (False, False)

    item = next(x for x in c.get('/api/trips/shared').json()['trips'] if x['id'] == trip['id'])
    assert _flags(item) == (False, False) and item['role'] == 'edit'

    # owner 公开后，协作者的详情与共享列表同步 is_public
    login(c)
    c.put(f"/api/trips/{trip['id']}/visibility", json={'is_public': True})
    login(c, 'bob', 'password2')
    assert _flags(c.get(f"/api/trips/{trip['id']}").json()) == (False, True)
    item = next(x for x in c.get('/api/trips/shared').json()['trips'] if x['id'] == trip['id'])
    assert _flags(item) == (False, True)


def test_invite_is_one_time_and_removal_revokes_pending_invites(client):
    c, _ = client
    login(c)
    trip = _create(c)
    token = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    # 一次性：同一 token 再次接受 404
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 404

    # owner 接受自己的邀请 422，且提示后令牌仍可发给别人
    login(c)
    own = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    resp = c.post('/api/collaborators/accept', json={'token': own})
    assert resp.status_code == 422
    assert resp.json()['detail'] == '不能接受自己发起的邀请。'
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': own}).status_code == 200  # 已是成员 → 200 幂等

    # owner 移除协作者：未接受的邀请同事务作废，旧链接无法把人加回来
    login(c)
    pending = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    members = c.get(f"/api/trips/{trip['id']}/collaborators").json()['members']
    bob_id = next(m['user_id'] for m in members if m['username'] == 'bob')
    assert c.delete(f"/api/trips/{trip['id']}/collaborators/{bob_id}").json() == {'ok': True}
    login(c, 'bob', 'password2')
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    assert c.post('/api/collaborators/accept', json={'token': pending}).status_code == 404


def test_guide_adopt_version_cas(client):
    c, _ = client
    login(c)
    trip = _create(c)
    assert trip['version'] == 0
    wrong = c.post(f"/api/trips/{trip['id']}/guide/adopt",
                   json={'assignments': [{'day': 1, 'place_id': '3'}], 'version': 7})
    assert wrong.status_code == 409
    assert '重新打开行程' in wrong.json()['detail']
    assert c.get(f"/api/trips/{trip['id']}").json()['days'][0]['stops'][0]['place']['id'] == '1'

    ok = c.post(f"/api/trips/{trip['id']}/guide/adopt",
                json={'assignments': [{'day': 1, 'place_id': '3'}], 'version': 0})
    assert ok.status_code == 200, ok.text
    assert ok.json()['version'] == 1
    # 不带 version 的老客户端仍可写入
    legacy = c.post(f"/api/trips/{trip['id']}/guide/adopt",
                    json={'assignments': [{'day': 2, 'place_id': '4'}]})
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()['version'] == 2
    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert [s['place']['id'] for s in detail['days'][0]['stops']] == ['1', '3']


def test_share_link_fork_copies_private_trip_without_conversation(client):
    c, _ = client
    login(c)
    messages = [{'role': 'user', 'content': '预算 3000，同行有老人'}, {'role': 'assistant', 'content': '已按轻松节奏安排'}]
    trip = c.post('/api/trips', json={'city': '桂林', 'days': 1, 'conversation': messages}).json()
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    # 私密行程（未公开）也能凭链接复制；但必须登录
    c.post('/api/logout')
    assert c.post('/api/shares/fork', json={'token': token}).status_code == 401
    login(c, 'bob', 'password2')
    forked = c.post('/api/shares/fork', json={'token': token})
    assert forked.status_code == 201, forked.text
    copy = forked.json()
    assert copy['id'] != trip['id'] and copy['version'] == 0
    assert _flags(copy) == (True, False)
    assert copy['conversation'] == []
    assert '同行有老人' not in json.dumps(copy, ensure_ascii=False)
    assert copy['request']['city'] == '桂林' and copy['days'][0]['stops']
    assert copy['title'] == trip['title']

    # 副本归属 bob，内容可继续读取；原行程不受影响
    assert any(item['id'] == copy['id'] for item in c.get('/api/trips').json())
    detail = c.get(f"/api/trips/{copy['id']}").json()
    assert detail['is_owner'] is True and detail['conversation'] == []
    assert detail['days'][0]['stops']
    login(c)
    assert c.get(f"/api/trips/{trip['id']}").json()['conversation'] == messages

    login(c, 'bob', 'password2')
    bad = c.post('/api/shares/fork', json={'token': 'not-a-real-token'})
    assert bad.status_code == 404
    assert bad.json()['detail'] == '分享链接无效或已失效。'
