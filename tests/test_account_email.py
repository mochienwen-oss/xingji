"""B4：邮箱验证、修改邮箱与重发。

账户 token 只存 sha256，明文只出现在邮件链接里，所以测试统一从 mailer.send 捕获的正文取
token（#verify= / #change-email= 都支持），不从数据库反推；过期/重复消费用真实 token 构造。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import backend.db as app_db
from backend.db import AccountToken, User
from backend.services import account_tokens, mailer
from tests.conftest import login

PASSWORD = 'password9'


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture(monkeypatch):
    """替身 mailer.send：记录每封信（含正文链接）并返回成功。"""
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append({'to': to, 'subject': subject, 'text': text, 'html': html})
        return True

    monkeypatch.setattr(mailer, 'send', fake_send)
    return sent


def _link_token(entry, marker=None):
    """从邮件正文取明文 token；#change-email= 与 #verify= 两种链接都认。"""
    text = entry['text']
    markers = ([marker] if marker else []) + ['#change-email=', '#verify=']
    for candidate in markers:
        index = text.find(candidate)
        if index >= 0:
            return text[index + len(candidate):].splitlines()[0].strip().strip('。，,')
    raise AssertionError(f'邮件里没有验证链接：{text!r}')


def _register(c, monkeypatch, username='carol', email='carol@example.com'):
    sent = _capture(monkeypatch)
    resp = c.post('/api/register', json={
        'username': username, 'password': PASSWORD, 'email': email, 'accept_terms': True,
    })
    assert resp.status_code == 200, resp.text
    return sent


def _user_id(username='carol'):
    with app_db.Session() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _fields(username='carol'):
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        return {
            'email': user.email,
            'pending_email': user.pending_email,
            'email_verified_at': user.email_verified_at,
        }


def _tokens(username='carol', kind=None):
    with app_db.Session() as db:
        query = select(AccountToken).where(AccountToken.user_id == _user_id(username))
        if kind:
            query = query.where(AccountToken.kind == kind)
        rows = db.scalars(query.order_by(AccountToken.id)).all()
        return [
            {'kind': r.kind, 'email': r.email, 'used_at': r.used_at, 'expires_at': r.expires_at}
            for r in rows
        ]


def test_verify_email_token_marks_email_verified(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert len(sent) == 1
    assert sent[0]['to'] == 'carol@example.com'
    assert '验证' in sent[0]['subject']
    token = _link_token(sent[0], '#verify=')

    c.post('/api/logout')  # 公开端点：没有会话也能验证
    resp = c.post('/api/account/verify-email', json={'token': token})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'ok': True, 'email': 'carol@example.com', 'kind': 'verify_email'}

    fields = _fields()
    assert fields['email'] == 'carol@example.com'
    assert fields['email_verified_at'] is not None
    assert fields['pending_email'] is None
    login(c, 'carol', PASSWORD)
    assert c.get('/api/me').json()['email_verified'] is True


def test_verify_email_rejects_unknown_used_and_expired(client, monkeypatch):
    c, _ = client
    unknown = c.post('/api/account/verify-email', json={'token': 'not-a-real-token'})
    assert unknown.status_code == 400
    assert unknown.json()['detail'] == '链接无效或已过期'

    sent = _register(c, monkeypatch)
    token = _link_token(sent[0])
    assert c.post('/api/account/verify-email', json={'token': token}).status_code == 200
    again = c.post('/api/account/verify-email', json={'token': token})
    assert again.status_code == 400
    assert again.json()['detail'] == '链接无效或已过期'

    expired_sent = _register(c, monkeypatch, username='dave', email='dave@example.com')
    expired_token = _link_token(expired_sent[0])
    with app_db.Session() as db:
        row = db.scalar(select(AccountToken).where(AccountToken.user_id == _user_id('dave')))
        row.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.commit()
    expired = c.post('/api/account/verify-email', json={'token': expired_token})
    assert expired.status_code == 400
    assert expired.json()['detail'] == '链接无效或已过期'
    assert _fields('dave')['email_verified_at'] is None


def test_verify_email_ignores_other_token_kinds(client, monkeypatch):
    c, _ = client
    _register(c, monkeypatch)
    with app_db.Session() as db:
        reset = account_tokens.create(
            db, _user_id(), account_tokens.KIND_RESET_PASSWORD, None, 3600
        )
        db.commit()
    resp = c.post('/api/account/verify-email', json={'token': reset})
    assert resp.status_code == 400
    assert _fields()['email_verified_at'] is None
    with app_db.Session() as db:
        row = db.scalar(
            select(AccountToken).where(AccountToken.token_hash == account_tokens.hash_token(reset))
        )
        assert row.used_at is None, 'kind 不符不能消费 token'


def test_change_email_requires_login_and_current_password(client):
    c, _ = client
    anonymous = c.post('/api/account/email',
                       json={'email': 'new@example.com', 'password': 'whatever1'})
    assert anonymous.status_code == 401

    login(c)
    wrong = c.post('/api/account/email',
                   json={'email': 'new@example.com', 'password': 'wrong-password'})
    assert wrong.status_code == 401
    assert wrong.json()['detail'] == '密码错误'
    fields = _fields('alice')
    assert fields['email'] is None
    assert fields['pending_email'] is None


def test_change_email_rejects_invalid_address(client):
    c, _ = client
    login(c)
    resp = c.post('/api/account/email', json={'email': 'not-an-email', 'password': 'password1'})
    assert resp.status_code == 422
    assert _fields('alice')['pending_email'] is None


def test_change_email_rejects_same_and_taken_address(client, monkeypatch):
    c, _ = client
    _capture(monkeypatch)
    with app_db.Session() as db:
        alice = db.scalar(select(User).where(User.username == 'alice'))
        alice.email = 'alice@example.com'
        alice.email_verified_at = _stamp()
        bob = db.scalar(select(User).where(User.username == 'bob'))
        bob.email = 'bob@example.com'
        bob.pending_email = 'bob-pending@example.com'
        db.commit()

    login(c)
    same = c.post('/api/account/email', json={'email': 'ALICE@example.com', 'password': 'password1'})
    assert same.status_code == 409
    assert same.json()['detail'] == '新邮箱与当前邮箱相同。'

    taken = c.post('/api/account/email', json={'email': 'bob@example.com', 'password': 'password1'})
    assert taken.status_code == 409
    assert taken.json()['detail'] == '这个邮箱已绑定其他账号，请换一个或直接登录。'

    pending_taken = c.post('/api/account/email',
                           json={'email': 'bob-pending@example.com', 'password': 'password1'})
    assert pending_taken.status_code == 409
    assert _fields('alice')['pending_email'] is None


def test_change_email_pends_then_swaps_on_verify(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    sent.clear()

    resp = c.post('/api/account/email',
                  json={'email': '  Carol.New@Example.COM ', 'password': PASSWORD})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'pending_email': 'carol.new@example.com', 'email_sent': True}
    assert len(sent) == 1
    assert sent[0]['to'] == 'carol.new@example.com'
    assert '新邮箱' in sent[0]['subject']
    change_token = _link_token(sent[0])

    fields = _fields()
    assert fields['email'] == 'carol@example.com', '验证前 email 不能变'
    assert fields['pending_email'] == 'carol.new@example.com'
    rows = _tokens(kind='change_email')
    assert len(rows) == 1
    assert rows[0]['email'] == 'carol.new@example.com'
    assert rows[0]['used_at'] is None

    c.post('/api/logout')
    done = c.post('/api/account/verify-email', json={'token': change_token})
    assert done.status_code == 200, done.text
    assert done.json() == {
        'ok': True, 'email': 'carol.new@example.com', 'kind': 'change_email',
    }
    fields = _fields()
    assert fields['email'] == 'carol.new@example.com'
    assert fields['pending_email'] is None
    assert fields['email_verified_at'] is not None


def test_change_email_verify_rejects_when_pending_changed(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    sent.clear()
    assert c.post('/api/account/email',
                  json={'email': 'first@example.com', 'password': PASSWORD}).status_code == 200
    token = _link_token(sent[0])

    with app_db.Session() as db:
        carol = db.scalar(select(User).where(User.username == 'carol'))
        carol.pending_email = 'second@example.com'
        db.commit()

    resp = c.post('/api/account/verify-email', json={'token': token})
    assert resp.status_code == 400
    assert resp.json()['detail'] == '链接无效或已过期'
    fields = _fields()
    assert fields['email'] == 'carol@example.com'
    assert fields['pending_email'] == 'second@example.com', '旧链接不能覆盖新 pending'


def test_change_email_send_failure_returns_503_and_clears_pending(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200

    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: False)
    resp = c.post('/api/account/email',
                  json={'email': 'new@example.com', 'password': PASSWORD})
    assert resp.status_code == 503
    assert resp.json()['detail'] == '当前环境未配置邮件服务，暂时无法发送验证邮件。'
    fields = _fields()
    assert fields['email'] == 'carol@example.com'
    assert fields['pending_email'] is None, '发送失败不能留下验证不了的 pending'
    assert _tokens(kind='change_email') == [], '失败的 token 要删掉'

    def boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(mailer, 'send', boom)
    raised = c.post('/api/account/email',
                    json={'email': 'other@example.com', 'password': PASSWORD})
    assert raised.status_code == 503
    assert raised.json()['detail'] == '当前环境未配置邮件服务，暂时无法发送验证邮件。'
    assert _fields()['pending_email'] is None
    assert _tokens(kind='change_email') == []


def test_resend_requires_login_and_an_email(client):
    c, _ = client
    assert c.post('/api/account/email/resend').status_code == 401

    login(c)  # alice 是旧账号，没有邮箱
    resp = c.post('/api/account/email/resend')
    assert resp.status_code == 400
    assert resp.json()['detail'] == '没有可验证的邮箱。'


def test_resend_rejects_verified_email_without_pending(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    resp = c.post('/api/account/email/resend')
    assert resp.status_code == 409
    assert resp.json()['detail'] == '当前邮箱已验证，无需重复验证。'


def test_resend_issues_new_token_and_invalidates_old(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    old = _link_token(sent[0])
    sent.clear()

    resp = c.post('/api/account/email/resend')
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'email_sent': True}
    assert len(sent) == 1
    assert sent[0]['to'] == 'carol@example.com'
    new = _link_token(sent[0])
    assert new != old

    stale = c.post('/api/account/verify-email', json={'token': old})
    assert stale.status_code == 400, '重发后旧 token 必须立即失效'
    assert c.post('/api/account/verify-email', json={'token': new}).status_code == 200
    assert _fields()['email_verified_at'] is not None


def test_resend_targets_pending_email(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    sent.clear()
    assert c.post('/api/account/email',
                  json={'email': 'new@example.com', 'password': PASSWORD}).status_code == 200
    first = _link_token(sent[0])
    sent.clear()

    resp = c.post('/api/account/email/resend')
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'email_sent': True, 'pending_email': 'new@example.com'}
    assert len(sent) == 1 and sent[0]['to'] == 'new@example.com'
    second = _link_token(sent[0])
    assert second != first

    assert c.post('/api/account/verify-email', json={'token': first}).status_code == 400
    assert c.post('/api/account/verify-email', json={'token': second}).status_code == 200
    fields = _fields()
    assert fields['email'] == 'new@example.com'
    assert fields['pending_email'] is None


def test_resend_send_failure_returns_503(client, monkeypatch):
    c, _ = client
    sent = _register(c, monkeypatch)
    original = _link_token(sent[0])

    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: False)
    resp = c.post('/api/account/email/resend')
    assert resp.status_code == 503
    assert resp.json()['detail'] == '当前环境未配置邮件服务，暂时无法发送验证邮件。'
    assert _fields()['email_verified_at'] is None
    # 发送失败整体回滚：注册时那封邮件里的链接仍然可用
    assert c.post('/api/account/verify-email', json={'token': original}).status_code == 200
