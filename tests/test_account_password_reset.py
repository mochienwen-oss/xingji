"""B5：忘记密码与邮件重置。

重置链接只出现在邮件正文里（库里只有 sha256），所以测试统一从 mailer.send 捕获的正文取
`#reset=` 后面的明文 token，不从数据库反推；过期/重复消费用真实 token 构造。

设计说明（对应验收第 8 条）：/password/reset 只校验 token 本身（kind=reset_password、未消费、
未过期），不再查 email_verified_at——token 就是唯一凭证，而 /password/forgot 只对“email 非空
且已验证”的账号发信并落 token，所以未验证邮箱的账号没有任何途径拿到可用 token。手工往库里
插入 token 属于已经拿到数据库写权限的场景（那时直接改 password_hash 更省事），不构成额外威胁，
本轮不为此增加计划外的校验。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import backend.db as app_db
from backend.auth import hash_password
from backend.db import AccountToken, User
from backend.services import account_tokens, mailer, ratelimit
from tests.conftest import login

PASSWORD = 'password9'
NEW_PASSWORD = 'newpassword7'
INVALID_LINK = '链接无效或已过期'
PASSWORD_BLANK = '新密码不能全是空格'


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture(monkeypatch):
    """替身 mailer.send：记录每封信（含正文链接）并返回成功，测试不碰真实 SMTP。"""
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append({'to': to, 'subject': subject, 'text': text, 'html': html})
        return True

    monkeypatch.setattr(mailer, 'send', fake_send)
    return sent


def _reset_token(entry):
    """从重置邮件正文取明文 token；链接必须是 #reset=，不能是 B4 的 #verify=。"""
    text = entry['text']
    index = text.find('#reset=')
    assert index >= 0, f'邮件里没有重置链接：{text!r}'
    return text[index + len('#reset='):].splitlines()[0].strip()


def _create_user(username, email=None, verified=False, password=PASSWORD):
    """直接建用户：B5 只关心“邮箱是否存在且已验证”这两个字段。"""
    with app_db.Session() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email,
            email_verified_at=_stamp() if verified else None,
            accepted_terms_at=_stamp(),
        )
        db.add(user)
        db.commit()
        return user.id


def _user_fields(username):
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None, f'用户 {username} 不存在'
        return {
            'email': user.email,
            'email_verified_at': user.email_verified_at,
            'session_version': user.session_version,
        }


def _reset_rows(username):
    """该用户全部 reset_password token 的快照（含已消费的，便于断言作废）。"""
    with app_db.Session() as db:
        uid = db.scalar(select(User.id).where(User.username == username))
        rows = db.scalars(
            select(AccountToken)
            .where(
                AccountToken.user_id == uid,
                AccountToken.kind == account_tokens.KIND_RESET_PASSWORD,
            )
            .order_by(AccountToken.id)
        ).all()
        return [
            {'email': r.email, 'used_at': r.used_at, 'expires_at': r.expires_at}
            for r in rows
        ]


def _forgot(c, identifier):
    return c.post('/api/account/password/forgot', json={'identifier': identifier})


def _reset(c, token, password=NEW_PASSWORD):
    return c.post('/api/account/password/reset',
                  json={'token': token, 'new_password': password})


def _expire_reset_tokens(username):
    """把该用户的重置 token 全部改成 1 分钟前过期，模拟点开隔夜邮件。"""
    with app_db.Session() as db:
        uid = db.scalar(select(User.id).where(User.username == username))
        rows = db.scalars(
            select(AccountToken).where(
                AccountToken.user_id == uid,
                AccountToken.kind == account_tokens.KIND_RESET_PASSWORD,
            )
        ).all()
        for row in rows:
            row.expires_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.commit()


def test_forgot_is_generic_and_only_mails_verified_accounts(client, monkeypatch):
    """不存在、未验证、已验证三种账号的 forgot 响应必须完全一致，只有已验证的才发信。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('unverified', email='unverified@example.com')
    _create_user('verified', email='verified@example.com', verified=True)

    responses = [
        _forgot(c, 'ghost'),                    # 不存在的用户名
        _forgot(c, 'ghost@example.com'),        # 不存在的邮箱
        _forgot(c, 'unverified'),               # 用户名：有邮箱但未验证
        _forgot(c, 'unverified@example.com'),   # 邮箱：有邮箱但未验证
        _forgot(c, 'not-an-email@'),            # 含 @ 但格式非法，按不存在处理
    ]
    # B10：forgot 限流为 5 次/60 秒，第 6 次会 429。本用例只验证响应一致性，
    # 不计限流行为，清桶后继续跑“已验证”这一种。
    ratelimit.reset()
    responses.append(_forgot(c, 'verified'))     # 已验证：唯一会发信的一类
    assert [resp.status_code for resp in responses] == [200] * len(responses)
    assert all(resp.json() == {'ok': True} for resp in responses)

    assert len(sent) == 1, '只有已验证邮箱会发信'
    assert sent[0]['to'] == 'verified@example.com'
    assert '重置' in sent[0]['subject']
    assert '#reset=' in sent[0]['text'] and '#verify=' not in sent[0]['text']
    assert _reset_token(sent[0])

    assert _reset_rows('unverified') == [], '未验证邮箱不能落 token'
    rows = _reset_rows('verified')
    assert len(rows) == 1
    assert rows[0]['email'] == 'verified@example.com'
    assert rows[0]['used_at'] is None
    expires = datetime.fromisoformat(rows[0]['expires_at'])
    minutes = (expires - datetime.now(timezone.utc)).total_seconds() / 60
    assert 25 <= minutes <= 35, '重置 token 有效期 30 分钟'


def test_forgot_validates_identifier_shape(client):
    """空/过长 identifier 是字段错误（422），不是账号存在性信息。"""
    c, _ = client
    assert c.post('/api/account/password/forgot', json={'identifier': ''}).status_code == 422
    assert c.post('/api/account/password/forgot', json={'identifier': 'x' * 255}).status_code == 422
    assert c.post('/api/account/password/forgot', json={}).status_code == 422


def test_forgot_cools_down_for_sixty_seconds(client, monkeypatch):
    """同一账号 60 秒内只发一封：仍 200，但不发信、也不作废上一封的链接。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)

    assert _forgot(c, 'verified').json() == {'ok': True}
    assert len(sent) == 1
    first_rows = _reset_rows('verified')
    assert len(first_rows) == 1

    again = _forgot(c, 'verified')
    assert again.status_code == 200 and again.json() == {'ok': True}
    assert len(sent) == 1, '冷却期内不能重复发信'
    assert _reset_rows('verified') == first_rows, '冷却期内不能顺手作废上一封的链接'

    # 冷却窗口过去后可以再发，并作废旧链接（同一用户同 kind 只保留一个未用 token）
    with app_db.Session() as db:
        uid = db.scalar(select(User.id).where(User.username == 'verified'))
        for row in db.scalars(
            select(AccountToken).where(
                AccountToken.user_id == uid,
                AccountToken.kind == account_tokens.KIND_RESET_PASSWORD,
            )
        ).all():
            row.created_at = (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat()
        db.commit()

    assert _forgot(c, 'verified@example.com').json() == {'ok': True}
    assert len(sent) == 2
    rows = _reset_rows('verified')
    assert len(rows) == 2
    assert rows[0]['used_at'] is not None, '旧链接要作废'
    unused = [row for row in rows if row['used_at'] is None]
    assert len(unused) == 1, '任何时刻只保留一个可用的重置 token'


def test_reset_password_flow(client, monkeypatch):
    """重置成功后：旧密码 401、新密码 200、不自动登录。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)

    assert _forgot(c, 'verified@example.com').status_code == 200
    token = _reset_token(sent[0])
    resp = _reset(c, token)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'ok': True}
    assert 'set-cookie' not in resp.headers, '重置不自动登录、不写 cookie'

    c.post('/api/logout')
    old = login(c, 'verified', PASSWORD)
    assert old.status_code == 401
    assert old.json()['detail'] == '用户名或密码错误'
    new = login(c, 'verified', NEW_PASSWORD)
    assert new.status_code == 200, new.text
    assert c.get('/api/me').status_code == 200
    assert _reset_rows('verified')[0]['used_at'] is not None
    assert _user_fields('verified')['session_version'] == 1


def test_reset_token_is_single_use(client, monkeypatch):
    """同一 token 第二次 400，且不会把密码改成第二次的内容。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)
    assert _forgot(c, 'verified').status_code == 200
    token = _reset_token(sent[0])

    assert _reset(c, token).status_code == 200
    again = _reset(c, token, 'another-pass1')
    assert again.status_code == 400
    assert again.json()['detail'] == INVALID_LINK

    assert _user_fields('verified')['session_version'] == 1, '重复消费不能再次 +1'
    c.post('/api/logout')
    assert login(c, 'verified', NEW_PASSWORD).status_code == 200
    assert login(c, 'verified', 'another-pass1').status_code == 401


def test_reset_rejects_expired_token(client, monkeypatch):
    """过期 token 400，密码保持不变。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)
    assert _forgot(c, 'verified').status_code == 200
    token = _reset_token(sent[0])
    _expire_reset_tokens('verified')

    resp = _reset(c, token)
    assert resp.status_code == 400
    assert resp.json()['detail'] == INVALID_LINK
    c.post('/api/logout')
    assert login(c, 'verified', PASSWORD).status_code == 200
    assert login(c, 'verified', NEW_PASSWORD).status_code == 401


def test_reset_rejects_unknown_token(client):
    """不存在的 token 与已过期/已消费同一文案，不泄露 token 状态。"""
    c, _ = client
    resp = _reset(c, 'not-a-real-reset-token')
    assert resp.status_code == 400
    assert resp.json()['detail'] == INVALID_LINK


def test_reset_validates_new_password(client, monkeypatch):
    """全空白/过短/过长都是 422，且失败不消费 token、不改密码。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)
    assert _forgot(c, 'verified').status_code == 200
    token = _reset_token(sent[0])

    blank = _reset(c, token, ' ' * 8)
    assert blank.status_code == 422
    assert blank.json()['detail'] == PASSWORD_BLANK
    assert _reset(c, token, 'short1').status_code == 422
    assert _reset(c, token, 'x' * 201).status_code == 422

    # 校验失败发生在消费 token 之前：密码未变，token 仍可用
    c.post('/api/logout')
    assert login(c, 'verified', PASSWORD).status_code == 200
    assert _reset_rows('verified')[0]['used_at'] is None
    assert _reset(c, token).status_code == 200
    c.post('/api/logout')
    assert login(c, 'verified', NEW_PASSWORD).status_code == 200


def test_reset_invalidates_existing_session_cookie(client, monkeypatch):
    """重置后旧 session cookie 立即失效（session_version 用 SQL 表达式 +1）。"""
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('verified', email='verified@example.com', verified=True)

    assert login(c, 'verified', PASSWORD).status_code == 200
    assert c.get('/api/me').status_code == 200

    assert _forgot(c, 'verified').status_code == 200
    assert _reset(c, _reset_token(sent[0])).status_code == 200

    stale = c.get('/api/me')
    assert stale.status_code == 401
    assert stale.json()['detail'] == '请先登录'
    assert _user_fields('verified')['session_version'] == 1


def test_forgot_never_issues_token_for_unverified_email(client, monkeypatch):
    """未验证邮箱/无邮箱的账号：forgot 200 但不落 token，任何 token 都换不到密码。

    实现说明：reset 端点只信任 token 本身，不复查 email_verified_at；这里的保证来自
    “发不出 token”——库里没有该用户的 reset_token，构造任意字符串也一律 400。
    """
    c, _ = client
    sent = _capture(monkeypatch)
    _create_user('unverified', email='unverified@example.com')
    _create_user('noemail')

    for identifier in ('unverified', 'unverified@example.com', 'noemail'):
        resp = _forgot(c, identifier)
        assert resp.status_code == 200 and resp.json() == {'ok': True}
    assert sent == []
    assert _reset_rows('unverified') == []
    assert _reset_rows('noemail') == []

    forged = _reset(c, 'handmade-reset-token')
    assert forged.status_code == 400
    assert forged.json()['detail'] == INVALID_LINK
    c.post('/api/logout')
    assert login(c, 'unverified', PASSWORD).status_code == 200


def test_forgot_survives_mailer_failure(client, monkeypatch):
    """发信失败/抛异常只记日志：响应仍是同一个 200，不泄露账号状态。"""
    c, _ = client
    _create_user('verified', email='verified@example.com', verified=True)
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: False)
    resp = _forgot(c, 'verified')
    assert resp.status_code == 200
    assert resp.json() == {'ok': True}

    _create_user('failing', email='failing@example.com', verified=True)

    def boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(mailer, 'send', boom)
    raised = _forgot(c, 'failing@example.com')
    assert raised.status_code == 200
    assert raised.json() == {'ok': True}
