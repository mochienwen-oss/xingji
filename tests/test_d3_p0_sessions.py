"""D3 P0 会话安全回归：登出吊销与用户主键复用。

两条都是「旧 cookie 还能打开别人/已登出的账号」级别的漏洞，必须锁死：
- logout 只清浏览器 cookie 时，被复制走的 token 在 7 天内仍可继续用；
- SQLite 的 INTEGER PRIMARY KEY 在删除最高 id 后会复用该 id，只绑定 uid 的
  token 会让旧 cookie 直接落到新注册账号上。
"""

from sqlalchemy import select

import backend.db as app_db
from backend.db import User
from backend.services import mailer
from tests.conftest import login

def _register(c, username, email):
    return c.post('/api/register', json={
        'username': username,
        'password': 'password9',
        'email': email,
        'accept_terms': True,
    })

def test_logout_revokes_token_server_side(client):
    """登出后把同一枚 cookie 塞回去也必须 401，而不是继续有效 7 天。"""
    c, _ = client
    assert login(c).status_code == 200
    token = c.cookies.get('trip_session')
    assert token, '登录应下发会话 cookie'
    assert c.get('/api/me').status_code == 200

    assert c.post('/api/logout').status_code == 200
    c.cookies.set('trip_session', token)
    assert c.get('/api/me').status_code == 401, '登出必须吊销服务端会话'

    # 吊销只针对旧会话，重新登录应恢复正常
    assert login(c).status_code == 200
    assert c.get('/api/me').json()['username'] == 'alice'

def test_deleted_user_id_reuse_does_not_admit_old_cookie(client, monkeypatch):
    """删除最高 id 用户后新账号复用同一 id，旧 cookie 不能接管新账号。"""
    c, _ = client
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: True)

    assert _register(c, 'carol', 'carol@example.com').status_code == 200
    old_token = c.cookies.get('trip_session')
    assert old_token
    with app_db.Session() as db:
        carol = db.scalar(select(User).where(User.username == 'carol'))
        reused_id = carol.id
        db.delete(carol)
        db.commit()

    assert _register(c, 'dave', 'dave@example.com').status_code == 200
    with app_db.Session() as db:
        dave = db.scalar(select(User).where(User.username == 'dave'))
        assert dave.id == reused_id, '前置条件：SQLite 复用了被删除用户的 id'
        assert dave.session_nonce, '新账号必须写入会话盐'

    # 先清掉注册 dave 时下发的新 cookie，确保请求里只剩旧 token
    c.cookies.clear()
    c.cookies.set('trip_session', old_token)
    assert c.get('/api/me').status_code == 401, '旧账号的 cookie 不得接管复用 id 的新账号'
