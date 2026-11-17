"""账户一次性 token：只存 sha256、同一用户同 kind 单活跃、消费用条件 UPDATE 保证只成功一次。

明文 token 只返回给调用方（用于拼邮件链接），不落库、不写日志。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DBSession

from ..db import AccountToken
from .tokens import hash_token, new_token

KIND_VERIFY_EMAIL = 'verify_email'
KIND_CHANGE_EMAIL = 'change_email'
KIND_RESET_PASSWORD = 'reset_password'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def create(db: DBSession, user_id: int, kind: str, email: str | None, ttl_seconds: int) -> str:
    """生成新 token 并返回明文；同 user+kind 的旧未用 token 先标记 used_at（单活跃）。

    不 commit：由端点在完成业务写入后统一提交，避免半成品状态。
    """
    now = _now()
    db.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user_id,
            AccountToken.kind == kind,
            AccountToken.used_at.is_(None),
        )
        .values(used_at=_iso(now))
    )
    token = new_token(32)
    db.add(AccountToken(
        user_id=user_id,
        kind=kind,
        token_hash=hash_token(token),
        email=email,
        created_at=_iso(now),
        expires_at=_iso(now + timedelta(seconds=ttl_seconds)),
        used_at=None,
    ))
    return token


def invalidate(db: DBSession, user_id: int, kinds: tuple[str, ...]) -> int:
    """把该用户指定 kind 的未用 token 全部作废，返回影响行数（不 commit）。

    create 只清理单个 kind；resend 需要一次作废 verify_email 与 change_email。
    """
    if not kinds:
        return 0
    result = db.execute(
        update(AccountToken)
        .where(
            AccountToken.user_id == user_id,
            AccountToken.kind.in_(tuple(kinds)),
            AccountToken.used_at.is_(None),
        )
        .values(used_at=_iso(_now()))
    )
    return result.rowcount or 0


def delete_unused(db: DBSession, user_id: int, kind: str) -> int:
    """删除该用户该 kind 未使用的 token（发信失败、回滚 pending 时用，不 commit）。"""
    result = db.execute(
        delete(AccountToken).where(
            AccountToken.user_id == user_id,
            AccountToken.kind == kind,
            AccountToken.used_at.is_(None),
        )
    )
    return result.rowcount or 0


def consume(db: DBSession, plaintext: str, kind: str) -> AccountToken | None:
    """原子消费：只有把 used_at 从未空改成已用且 rowcount=1 才返回行，重复/并发消费一律 None。"""
    token_hash = hash_token(plaintext or '')
    now = _iso(_now())
    result = db.execute(
        update(AccountToken)
        .where(
            AccountToken.token_hash == token_hash,
            AccountToken.kind == kind,
            AccountToken.used_at.is_(None),
            AccountToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if result.rowcount != 1:
        return None
    return db.scalar(select(AccountToken).where(AccountToken.token_hash == token_hash))


def latest_created_at(db: DBSession, user_id: int, kind: str) -> datetime | None:
    """最近一次同 kind token 的创建时间（找回密码冷却用）；解析失败按没有处理。"""
    raw = db.scalar(
        select(AccountToken.created_at)
        .where(AccountToken.user_id == user_id, AccountToken.kind == kind)
        .order_by(AccountToken.created_at.desc())
        .limit(1)
    )
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)



