"""运营只读指标端点：给外部 uptime 探针和首周告警使用。

端点受 ADMIN_TOKEN 保护；未配置时返回 404，行为和举报管理端点一致，避免暴露管理面。
返回 JSON 而不是 Prometheus 文本：首周外部探针只需要几个固定字段，JSON 更容易直接看，
也避免为了一个端点引入额外依赖。
"""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text

from .. import db as app_db
from ..services import amap, analytics, metrics
from .dependencies import require_admin

router = APIRouter()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _db_probe() -> dict:
    """只做 SELECT 1；异常只返回类型名，不把连接串或 SQL 细节带出去。"""
    try:
        with app_db.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'ok': True}
    except Exception as exc:  # noqa: BLE001 - 探针必须把任何数据库错误变成可读状态
        return {'ok': False, 'error': type(exc).__name__}


def _disk_probe() -> dict:
    try:
        usage = shutil.disk_usage(_PROJECT_ROOT)
        return {
            'ok': True,
            'free_bytes': usage.free,
            'total_bytes': usage.total,
            'free_percent': round(usage.free / usage.total * 100, 1) if usage.total else 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': type(exc).__name__}


def _pool_probe() -> dict | None:
    """连接池状态不建立连接；不同 SQLAlchemy 池实现可能没有 status()。"""
    pool = getattr(app_db.engine, 'pool', None)
    status = getattr(pool, 'status', None)
    if not callable(status):
        return None
    try:
        return {'status': str(status())}
    except Exception:  # noqa: BLE001
        return None


@router.get('/api/metrics')
def metrics_snapshot(_: None = Depends(require_admin)):
    snapshot = metrics.snapshot()
    snapshot['db'] = _db_probe()
    snapshot['disk'] = _disk_probe()
    snapshot['pool'] = _pool_probe()
    snapshot['analytics'] = analytics.summary(days=14)
    snapshot['amap'] = amap.cache_stats()
    return snapshot
