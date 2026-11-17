"""首方产品事件日计数：回答“昨天多少人注册、多少生成成功”，不采集个人数据。

设计取舍：
- 只记 day + event + count，不记用户 id、IP、城市、行程或失败原因；
- 在服务端已确定结果后记录，不引入浏览器 SDK，也不怕广告拦截；
- 写入失败只告警，绝不影响用户请求；
- 用数据库唯一键做原子自增，多进程/多 worker 不会丢计数。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .. import db as app_db
from ..db import AnalyticsDaily

logger = logging.getLogger(__name__)

# 上线首周需要回答的 8 个问题；新增事件必须同步这里，避免用户可控字符串写进表。
EVENTS = (
    'register',
    'login',
    'generate_start',
    'generate_success',
    'generate_failure',
    'trip_save',
    'share',
    'fork',
)
_MAX_SUMMARY_DAYS = 90


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record(event: str) -> bool:
    """把一次事件累加到当天；未知事件、数据库异常都返回 False，不向上抛。"""
    if event not in EVENTS:
        logger.warning('忽略未登记的分析事件：%s', str(event)[:40])
        return False
    day = _today()
    try:
        with app_db.Session() as session:
            dialect = session.get_bind().dialect.name
            if dialect == 'postgresql':
                statement = postgres_insert(AnalyticsDaily)
            elif dialect == 'sqlite':
                statement = sqlite_insert(AnalyticsDaily)
            else:  # 兜底：非主力方言用先读后写，仍然只影响计数
                row = session.get(AnalyticsDaily, (day, event))
                if row is None:
                    session.add(AnalyticsDaily(day=day, name=event, count=1))
                else:
                    row.count = int(row.count or 0) + 1
                session.commit()
                return True
            session.execute(
                statement.values(day=day, name=event, count=1).on_conflict_do_update(
                    index_elements=[AnalyticsDaily.day, AnalyticsDaily.name],
                    set_={'count': AnalyticsDaily.count + 1},
                )
            )
            session.commit()
        return True
    except Exception:  # noqa: BLE001 - 分析失败不能影响主流程
        logger.warning('记录分析事件失败 event=%s', event, exc_info=True)
        return False


def summary(days: int = 14) -> dict:
    """返回最近 N 天（含今天）的按天计数，供受 ADMIN_TOKEN 保护的 /api/metrics 读取。"""
    days = max(1, min(int(days or 14), _MAX_SUMMARY_DAYS))
    start = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    result: dict[str, dict[str, int]] = {}
    try:
        with app_db.Session() as session:
            rows = session.execute(
                select(AnalyticsDaily.day, AnalyticsDaily.name, AnalyticsDaily.count)
                .where(AnalyticsDaily.day >= start)
                .order_by(AnalyticsDaily.day, AnalyticsDaily.name)
            ).all()
        for day, name, count in rows:
            result.setdefault(day, {})[name] = int(count or 0)
    except Exception:  # noqa: BLE001
        logger.warning('读取分析汇总失败', exc_info=True)
        return {'days': days, 'by_day': {}, 'error': 'unavailable'}
    return {'days': days, 'by_day': result}


def reset() -> None:
    """测试用：清空计数表。"""
    with app_db.Session() as session:
        session.query(AnalyticsDaily).delete()
        session.commit()
