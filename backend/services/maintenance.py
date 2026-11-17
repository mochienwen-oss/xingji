"""后台维护：删除过期的协作邀请、账户 token，以及超过保留期的软删除行程。

启动时跑一次，之后由 main.py 的维护循环每小时跑一次；请求路径不再做清理，
避免每个列表请求都全表扫描并逐行删除。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..db import (
    AccountToken,
    Expense,
    ShareLink,
    Trip,
    TripBudget,
    TripCollaborator,
    TripInvite,
)

log = logging.getLogger(__name__)

PURGE_DAYS = 7  # 软删除行程保留天数，过期后彻底清除

def purge_soft_deleted_trips(db: Session) -> int:
    """删除超过 PURGE_DAYS 的软删除行程及全部派生数据，返回删除的行程数。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PURGE_DAYS)).isoformat()
    expired = db.scalars(select(Trip).where(Trip.deleted_at.is_not(None), Trip.deleted_at < cutoff)).all()
    for row in expired:
        db.execute(delete(ShareLink).where(ShareLink.trip_id == row.id))
        db.execute(delete(Expense).where(Expense.trip_id == row.id))
        db.execute(delete(TripBudget).where(TripBudget.trip_id == row.id))
        # 派生授权行必须一起删：残留的协作者/邀请会随主键复用到别人的新行程上。
        db.execute(delete(TripCollaborator).where(TripCollaborator.trip_id == row.id))
        db.execute(delete(TripInvite).where(TripInvite.trip_id == row.id))
        db.delete(row)
    return len(expired)

def purge_expired(db: Session) -> dict[str, int]:
    """删除过期邀请、过期/已用 token 与过期软删行程，统一 commit。

    历史邀请的 expires_at 可能为空（老库由 ensure_schema 补列）：业务层按
    created_at + 7 天兜底判断，这里不猜测、不删除，避免误删仍可用的邀请。
    """
    now = datetime.now(timezone.utc).isoformat()
    invites = db.execute(
        delete(TripInvite).where(
            TripInvite.expires_at.is_not(None),
            TripInvite.expires_at < now,
        )
    ).rowcount or 0
    # 已用 token 即使没过期也没有价值：启动维护与账户流程共用这一处清理。
    tokens = db.execute(
        delete(AccountToken).where(
            or_(AccountToken.expires_at < now, AccountToken.used_at.is_not(None))
        )
    ).rowcount or 0
    trips = purge_soft_deleted_trips(db)
    db.commit()
    return {'invites': invites, 'tokens': tokens, 'trips': trips}

def purge_expired_once() -> dict[str, int]:
    """开一个短会话跑一次清理，供启动/定时任务在事件循环外调用。"""
    from .. import db as app_db

    with app_db.Session() as session:
        return purge_expired(session)
