"""B6：登录状态下修改密码。

改密成功后 session_version+1 并用新版本重写当前会话 cookie：同一浏览器立即继续可用，
其他持有旧 cookie 的会话下一次请求 401。新旧密码相同也按修改处理（版本照常 +1），
用户不会因为“看起来没变”而反复提交。
"""
from sqlalchemy import select

import backend.db as app_db
from backend.auth import read_token
from backend.db import User
from tests.conftest import login

CURRENT_WRONG = '当前密码错误'
PASSWORD_BLANK = '新密码不能全是空格'
OLD_PASSWORD = 'password1'
NEW_PASSWORD = 'newpassword7'


def _change(c, current=OLD_PASSWORD, new=NEW_PASSWORD):
    return c.post('/api/account/password',
                  json={'current_password': current, 'new_password': new})


def _version(username='alice'):
    with app_db.Session() as db:
        return db.scalar(select(User.session_version).where(User.username == username))


def test_change_password_requires_login(client):
    """未登录：401，且不因为 body 合法与否改变语义。"""
    c, _ = client
    resp = _change(c)
    assert resp.status_code == 401
    assert resp.json()['detail'] == '请先登录'
    assert _version() == 0


def test_change_password_rejects_wrong_current_password(client):
    """当前密码错：401“当前密码错误”，不动版本、不动当前会话、不改密码。"""
    c, _ = client
    assert login(c).status_code == 200
    resp = _change(c, current='not-my-password')
    assert resp.status_code == 401
    assert resp.json()['detail'] == CURRENT_WRONG
    assert _version() == 0
    assert c.get('/api/me').status_code == 200, '失败的改密不能踢掉当前会话'
    c.post('/api/logout')
    assert login(c, 'alice', OLD_PASSWORD).status_code == 200, '密码必须保持不变'


def test_change_password_rejects_blank_and_out_of_range(client):
    """全空白是 B5 同款 422 文案；长度不足/超长由 schema 拦成 422。"""
    c, _ = client
    login(c)
    blank = _change(c, new=' ' * 8)
    assert blank.status_code == 422
    assert blank.json()['detail'] == PASSWORD_BLANK
    assert _change(c, new='short7').status_code == 422
    assert _change(c, new='x' * 201).status_code == 422
    assert _change(c, current='x' * 201).status_code == 422
    assert _change(c, current='').status_code == 422
    assert _version() == 0


def test_change_password_keeps_current_session_and_drops_stale_cookie(client):
    """成功：当前 cookie 换成新版本立即有效；旧 cookie 401；新旧密码登录结果互换。"""
    c, _ = client
    assert login(c).status_code == 200
    old_cookie = c.cookies.get('trip_session')
    assert old_cookie

    resp = _change(c)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'ok': True}
    new_cookie = resp.cookies.get('trip_session')
    assert new_cookie and new_cookie != old_cookie, '必须换发新版本 cookie'
    assert _version() == 1
    old_uid, _old_version, old_nonce = read_token(old_cookie)
    assert read_token(new_cookie) == (old_uid, 1, old_nonce)

    assert c.get('/api/me').status_code == 200, '当前会话马上继续可用'
    # 换掉 cookie jar 里的值，模拟另一个还拿着旧版本 cookie 的浏览器
    c.cookies.clear()
    c.cookies.set('trip_session', old_cookie)
    stale = c.get('/api/me')
    assert stale.status_code == 401
    assert stale.json()['detail'] == '请先登录'
    c.cookies.clear()
    c.cookies.set('trip_session', new_cookie)
    assert c.get('/api/me').status_code == 200

    c.post('/api/logout')
    assert login(c, 'alice', OLD_PASSWORD).status_code == 401
    assert login(c, 'alice', NEW_PASSWORD).status_code == 200


def test_change_password_allows_same_password_but_still_bumps_version(client):
    """新旧相同允许，但版本仍 +1，其他会话照样失效。"""
    c, _ = client
    assert login(c).status_code == 200
    old_cookie = c.cookies.get('trip_session')

    resp = _change(c, new=OLD_PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'ok': True}
    assert _version() == 1
    assert resp.cookies.get('trip_session') != old_cookie
    assert c.get('/api/me').status_code == 200

    c.post('/api/logout')
    assert login(c, 'alice', OLD_PASSWORD).status_code == 200
