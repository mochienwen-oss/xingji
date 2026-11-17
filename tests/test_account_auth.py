"""B3：注册邮箱选填、条款必填、登录状态字段、/api/me 六字段与条款幂等。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import backend.db as app_db
from backend import auth as auth_core
from backend.api import auth as auth_api
from backend.db import AccountToken, User
from backend.services import accounts, mailer
from tests.conftest import login


def _payload(username='carol', password='password9', email='carol@example.com', accept_terms=True):
    body = {'username': username, 'password': password, 'accept_terms': accept_terms}
    if email is not None:
        body['email'] = email
    return body


def _register(c, **kwargs):
    return c.post('/api/register', json=_payload(**kwargs))


def test_normalize_email_rules():
    assert accounts.normalize_email('  Alice@Example.COM ') == 'alice@example.com'
    for bad in ['', '   ', 'alice', 'alice@example', 'a b@example.com', 'alice@exa mple.com',
                'alice@@example.com', 'ali\x00ce@example.com', 'alice@exam\nple.com']:
        with pytest.raises(ValueError):
            accounts.normalize_email(bad)
    with pytest.raises(ValueError):
        accounts.normalize_email('a' * 250 + '@example.com')
    assert len(accounts.normalize_email('a' * 240 + '@example.com')) == 252


def test_register_without_email_succeeds(client):
    c, _ = client
    for username, email in [('carol', None), ('dave', ''), ('erin', '   ')]:
        if email is None:
            resp = c.post('/api/register',
                          json={'username': username, 'password': 'password9', 'accept_terms': True})
        else:
            resp = _register(c, username=username, email=email)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['username'] == username
        assert body['email'] == ''
        assert body['email_sent'] is False
        assert body['email_verified'] is False
        assert 'trip_session' in resp.cookies
        with app_db.Session() as db:
            user = db.scalar(select(User).where(User.username == username))
            assert user is not None
            assert user.email is None
            assert db.scalar(select(AccountToken).where(AccountToken.user_id == user.id)) is None
    assert c.get('/api/me').json()['needs_email'] is True
    c.post('/api/logout')
    assert c.post('/api/login', json={'username': 'erin', 'password': 'password9'}).status_code == 200


def test_register_requires_terms_and_valid_email(client):
    c, _ = client
    assert _register(c, email='not-an-email').status_code == 422
    rejected = _register(c, accept_terms=False)
    assert rejected.status_code == 422
    assert rejected.json()['detail'] == '请先阅读并同意用户协议与隐私说明'
    missing_terms = c.post('/api/register',
                           json={'username': 'carol', 'password': 'password9', 'email': 'carol@example.com'})
    assert missing_terms.status_code == 422
    assert missing_terms.json()['detail'] == '请先阅读并同意用户协议与隐私说明'
    with app_db.Session() as db:
        assert db.scalar(select(User).where(User.username == 'carol')) is None


def test_register_success_sets_cookie_and_sends_verification(client, monkeypatch):
    c, _ = client
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append((to, subject, text, html))
        return True

    monkeypatch.setattr(mailer, 'send', fake_send)
    resp = _register(c, email='  Carol@Example.COM ')
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 注册响应与 /api/me 共用 accounts.user_state，字段保持一致，只额外带 email_sent。
    assert set(body) == {'username', 'email', 'email_verified', 'needs_terms', 'needs_email', 'accepted_terms_at', 'email_sent'}
    assert body['username'] == 'carol'
    assert body['email'] == 'carol@example.com'
    assert body['email_verified'] is False
    assert body['email_sent'] is True
    assert body['needs_terms'] is False
    assert body['needs_email'] is False
    assert body['accepted_terms_at'] is not None
    assert 'trip_session' in resp.cookies
    assert c.get('/api/me').json()['email'] == 'carol@example.com'
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == 'carol'))
        assert user.email == 'carol@example.com'
        assert user.email_verified_at is None
        assert user.accepted_terms_at is not None
        assert auth_core.read_token(c.cookies.get('trip_session')) == (user.id, user.session_version, user.session_nonce)
        token = db.scalar(select(AccountToken).where(AccountToken.user_id == user.id))
        assert token.kind == 'verify_email' and token.email == 'carol@example.com'
        assert token.used_at is None
        assert token.expires_at > datetime.now(timezone.utc).isoformat()
    assert len(sent) == 1
    to, subject, text, _html = sent[0]
    assert to == 'carol@example.com'
    assert '验证' in subject
    assert '#verify=' in text


def test_register_keeps_account_when_mail_unconfigured_or_failing(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: False)
    failed = _register(c, username='carol', email='carol@example.com')
    assert failed.status_code == 200
    assert failed.json()['email_sent'] is False
    with app_db.Session() as db:
        assert db.scalar(select(User).where(User.username == 'carol')) is not None

    def boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(mailer, 'send', boom)
    raised = _register(c, username='dave', email='dave@example.com')
    assert raised.status_code == 200
    assert raised.json()['email_sent'] is False
    c.post('/api/logout')
    assert c.post('/api/login', json={'username': 'carol', 'password': 'password9'}).status_code == 200


def test_register_rejects_taken_username_and_email(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: True)
    assert _register(c).status_code == 200
    dup_name = _register(c, username='carol', email='other@example.com')
    assert dup_name.status_code == 409
    assert dup_name.json()['detail'] == '用户名已被使用，请换一个。'
    dup_email = _register(c, username='carol2', email='CAROL@example.com')
    assert dup_email.status_code == 409
    assert dup_email.json()['detail'] == '这个邮箱已绑定其他账号，请换一个或直接登录。'
    with app_db.Session() as db:
        bob = db.scalar(select(User).where(User.username == 'bob'))
        bob.pending_email = 'pending@example.com'
        db.commit()
    pending = _register(c, username='dave', email='pending@example.com')
    assert pending.status_code == 409
    assert pending.json()['detail'] == '这个邮箱已绑定其他账号，请换一个或直接登录。'


def test_register_integrity_race_returns_409(client, monkeypatch):
    c, _ = client

    def racing_hash(password):
        # 模拟并发注册：预检查通过后、INSERT 之前另一个请求先占用了用户名。
        with app_db.Session() as other:
            other.add(User(username='carol', password_hash='placeholder'))
            other.commit()
        return auth_core.hash_password(password)

    monkeypatch.setattr(auth_api, 'hash_password', racing_hash)
    resp = _register(c)
    assert resp.status_code == 409
    assert resp.json()['detail'] == '用户名或邮箱已被使用，请换一个。'


def test_login_returns_account_state_for_legacy_user(client):
    c, _ = client
    resp = login(c)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {'username', 'email', 'email_verified', 'needs_terms', 'needs_email', 'accepted_terms_at'}
    assert body['username'] == 'alice'
    assert body['email'] == ''
    assert body['email_verified'] is False
    assert body['needs_email'] is True
    assert body['needs_terms'] is True
    assert body['accepted_terms_at'] is None
    assert 'trip_session' in resp.cookies


def test_login_reports_verified_email_and_terms(client):
    c, _ = client
    stamp = datetime.now(timezone.utc).isoformat()
    with app_db.Session() as db:
        alice = db.scalar(select(User).where(User.username == 'alice'))
        alice.email = 'alice@example.com'
        alice.email_verified_at = stamp
        alice.accepted_terms_at = stamp
        db.commit()
    body = login(c).json()
    assert body['email'] == 'alice@example.com'
    assert body['email_verified'] is True
    assert body['needs_email'] is False
    assert body['needs_terms'] is False
    assert body['accepted_terms_at'] == stamp


def test_login_failure_message_unchanged(client):
    c, _ = client
    resp = c.post('/api/login', json={'username': 'alice', 'password': 'wrong-password'})
    assert resp.status_code == 401
    assert resp.json()['detail'] == '用户名或密码错误'


def test_login_cookie_carries_session_version(client):
    c, _ = client
    with app_db.Session() as db:
        alice = db.scalar(select(User).where(User.username == 'alice'))
        alice.session_version = 3
        db.commit()
        alice_id = alice.id
    assert login(c).status_code == 200
    assert auth_core.read_token(c.cookies.get('trip_session')) == (alice_id, 3, '')
    assert c.get('/api/me').status_code == 200


def test_me_returns_six_account_fields(client):
    c, _ = client
    login(c)
    body = c.get('/api/me').json()
    assert set(body) == {'username', 'email', 'email_verified', 'needs_terms', 'needs_email', 'accepted_terms_at'}
    assert body['username'] == 'alice'
    assert body['needs_email'] is True
    assert body['needs_terms'] is True
    assert body['email_verified'] is False


def test_terms_requires_login_and_is_idempotent(client):
    c, _ = client
    assert c.post('/api/account/terms').status_code == 401
    login(c)
    first = c.post('/api/account/terms')
    assert first.status_code == 200
    stamp = first.json()['accepted_terms_at']
    assert stamp
    second = c.post('/api/account/terms')
    assert second.status_code == 200
    assert second.json()['accepted_terms_at'] == stamp
    with app_db.Session() as db:
        alice = db.scalar(select(User).where(User.username == 'alice'))
        assert alice.accepted_terms_at == stamp
    assert c.get('/api/me').json()['needs_terms'] is False
