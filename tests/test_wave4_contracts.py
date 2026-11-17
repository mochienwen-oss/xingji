"""Wave4 契约：删除行程即撤销分享/邀请/公开状态，恢复不复活旧授权。"""
from tests.conftest import login


def _create_trip(c):
    resp = c.post('/api/trips', json={'city': '杭州', 'days': 1, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_delete_revokes_share_invite_and_public_state(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    share = c.post(f"/api/trips/{trip['id']}/share")
    assert share.status_code == 200, share.text
    share_token = share.json()['token']
    invite = c.post(f"/api/trips/{trip['id']}/collaborators/invite")
    assert invite.status_code == 200, invite.text
    invite_token = invite.json()['token']
    assert c.put(f"/api/trips/{trip['id']}/visibility", json={'is_public': True}).status_code == 200

    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    assert c.post(f"/api/trips/{trip['id']}/restore").status_code == 200

    # 恢复后：详情还在，但对外分享/邀请/广场公开都已撤销。
    detail = c.get(f"/api/trips/{trip['id']}")
    assert detail.status_code == 200
    assert detail.json()['is_public'] is False
    assert c.post('/api/shares/view', json={'token': share_token}).status_code == 404
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': invite_token}).status_code == 404
    assert all(item['id'] != trip['id'] for item in c.get('/api/plaza').json()['trips'])


def test_owner_can_revoke_one_share_link(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    token = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    assert c.post('/api/shares/view', json={'token': token}).status_code == 200
    assert c.delete(f'/api/shares/{token}').json() == {'ok': True}
    assert c.post('/api/shares/view', json={'token': token}).status_code == 404
    # 幂等：重复撤销仍是 200
    assert c.delete(f'/api/shares/{token}').status_code == 200

    login(c, 'bob', 'password2')
    other = c.post(f"/api/trips/{trip['id']}/share")
    assert other.status_code == 404, '非 owner 不能撤销分享'


def test_accept_invite_consumes_token_atomically(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    token = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    # 邀请已被原子删除：再次提交看到的是「无效」而不是「已过期/已使用」。
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 404
