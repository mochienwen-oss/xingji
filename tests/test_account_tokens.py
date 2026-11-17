"""B3：一次性账户 token 的哈希存储、单活跃、原子消费与清理。"""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import backend.db as app_db
from backend.db import AccountToken, User
from backend.services import account_tokens, maintenance


def _user_id(username='alice'):
    with app_db.Session() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _create(kind=account_tokens.KIND_VERIFY_EMAIL, ttl=3600, email='alice@example.com', username='alice'):
    """在独立会话里创建 token 并提交，模拟端点层的统一 commit。"""
    with app_db.Session() as db:
        token = account_tokens.create(db, _user_id(username), kind, email, ttl)
        db.commit()
    return token


def _tokens():
    with app_db.Session() as db:
        return list(db.scalars(select(AccountToken).order_by(AccountToken.id)).all())


def test_create_returns_plaintext_but_stores_only_sha256(client):
    token = _create()
    assert isinstance(token, str) and len(token) >= 40
    rows = _tokens()
    assert len(rows) == 1
    row = rows[0]
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.token_hash != token
    assert row.kind == account_tokens.KIND_VERIFY_EMAIL
    assert row.email == 'alice@example.com'
    assert row.used_at is None
    created = datetime.fromisoformat(row.created_at)
    expires = datetime.fromisoformat(row.expires_at)
    assert created.tzinfo is not None and expires.tzinfo is not None
    assert timedelta(minutes=59) < expires - created <= timedelta(hours=1)


def test_consume_once_then_second_call_returns_none(client):
    token = _create()
    with app_db.Session() as db:
        row = account_tokens.consume(db, token, account_tokens.KIND_VERIFY_EMAIL)
        assert row is not None and row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        db.commit()
    with app_db.Session() as db:
        assert account_tokens.consume(db, token, account_tokens.KIND_VERIFY_EMAIL) is None
    assert _tokens()[0].used_at is not None


def test_consume_requires_matching_kind(client):
    token = _create()
    with app_db.Session() as db:
        assert account_tokens.consume(db, token, account_tokens.KIND_CHANGE_EMAIL) is None
    assert _tokens()[0].used_at is None, 'kind 不匹配不能消费 token'


def test_consume_rejects_expired_token(client):
    token = _create(ttl=-60)
    with app_db.Session() as db:
        assert account_tokens.consume(db, token, account_tokens.KIND_VERIFY_EMAIL) is None


def test_new_token_invalidates_previous_token_of_same_kind(client):
    first = _create()
    second = _create()
    rows = _tokens()
    assert rows[0].used_at is not None, '同 user+kind 的新 token 必须让旧 token 立即失效'
    assert rows[1].used_at is None
    with app_db.Session() as db:
        assert account_tokens.consume(db, first, account_tokens.KIND_VERIFY_EMAIL) is None
        assert account_tokens.consume(db, second, account_tokens.KIND_VERIFY_EMAIL) is not None


def test_single_active_is_scoped_to_user_and_kind(client):
    alice_verify = _create()
    alice_reset = _create(kind=account_tokens.KIND_RESET_PASSWORD, email=None)
    bob_verify = _create(username='bob', email='bob@example.com')
    with app_db.Session() as db:
        assert account_tokens.consume(db, alice_verify, account_tokens.KIND_VERIFY_EMAIL) is not None
        assert account_tokens.consume(db, alice_reset, account_tokens.KIND_RESET_PASSWORD) is not None
        assert account_tokens.consume(db, bob_verify, account_tokens.KIND_VERIFY_EMAIL) is not None


def test_latest_created_at_returns_utc_datetime(client):
    with app_db.Session() as db:
        assert account_tokens.latest_created_at(db, _user_id(), account_tokens.KIND_RESET_PASSWORD) is None
    _create(kind=account_tokens.KIND_RESET_PASSWORD, email=None)
    with app_db.Session() as db:
        latest = account_tokens.latest_created_at(db, _user_id(), account_tokens.KIND_RESET_PASSWORD)
    assert latest is not None and latest.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - latest).total_seconds()) < 5


def test_purge_expired_removes_dead_tokens_only(client):
    _create(ttl=-60)  # 已过期
    used = _create(kind=account_tokens.KIND_CHANGE_EMAIL, email='alice@example.com')
    with app_db.Session() as db:
        assert account_tokens.consume(db, used, account_tokens.KIND_CHANGE_EMAIL) is not None
        db.commit()
    _create(kind=account_tokens.KIND_RESET_PASSWORD, email=None)  # 有效未用
    with app_db.Session() as db:
        assert maintenance.purge_expired(db)['tokens'] == 2
    rows = _tokens()
    assert [row.kind for row in rows] == [account_tokens.KIND_RESET_PASSWORD]
    with app_db.Session() as db:
        assert maintenance.purge_expired(db)['tokens'] == 0
