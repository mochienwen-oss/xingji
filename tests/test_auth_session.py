"""B1：cookie 的 session_version 必须与 users.session_version 一致；旧三段 token 仍可用。"""
import base64
import hashlib
import hmac
import time

from sqlalchemy import select

import backend.db as app_db
from backend import auth
from backend.api.dependencies import db_session
from backend.db import User
from backend.main import app
from tests.conftest import login


def _user_id(username='alice'):
    with app_db.Session() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _use_token(c, token):
    """覆盖浏览器里的会话 cookie：先清掉登录写入的 jar，再手工设置。"""
    c.cookies.clear()
    c.cookies.set('trip_session', token)


def _legacy_token(user_id, expires=None):
    expires = int(time.time()) + 60 if expires is None else expires
    payload = f'{user_id}:{expires}'
    sig = hmac.new(auth.SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f'{payload}:{sig}'.encode()).decode()


def test_login_then_me_is_ok(client):
    c, _ = client
    assert login(c).status_code == 200
    response = c.get('/api/me')
    assert response.status_code == 200
    assert response.json()['username'] == 'alice'


def test_legacy_cookie_still_works_for_version_zero_user(client):
    c, _ = client
    login(c)
    _use_token(c, _legacy_token(_user_id()))
    assert c.get('/api/me').status_code == 200


def test_token_version_mismatch_is_rejected_as_unauthenticated(client):
    c, _ = client
    login(c)
    _use_token(c, auth.make_token(_user_id(), 1))
    response = c.get('/api/me')
    assert response.status_code == 401
    assert response.json() == {'detail': '请先登录'}


def test_bumped_session_version_invalidates_existing_cookie(client):
    c, _ = client
    login(c)
    with app_db.Session() as db:
        user = db.get(User, _user_id())
        user.session_version = 1
        db.commit()
    assert c.get('/api/me').status_code == 401


def test_matching_version_cookie_is_accepted_after_mismatch(client):
    c, _ = client
    login(c)
    alice = _user_id()
    _use_token(c, auth.make_token(alice, 1))
    assert c.get('/api/me').status_code == 401
    _use_token(c, auth.make_token(alice, 0))
    assert c.get('/api/me').status_code == 200


def test_expired_legacy_cookie_is_rejected(client):
    c, _ = client
    login(c)
    _use_token(c, _legacy_token(_user_id(), int(time.time()) - 1))
    assert c.get('/api/me').status_code == 401

def test_db_session_dependency_uses_configured_factory(client):
    """回归：测试通常覆盖 db_session，真实依赖也必须能打开会话，而不是 500。"""
    c, _ = client
    app.dependency_overrides.pop(db_session, None)
    response = c.get('/api/me')
    assert response.status_code == 401
    assert response.json()['detail'] == '请先登录'
