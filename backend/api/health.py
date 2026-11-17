"""健康检查：给负载均衡/监控用的只读探活，不鉴权、不限流、不写库。"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .. import __version__, db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get('/api/health')
def health():
    """执行一次 SELECT 1 验证数据库可用；失败只回降级状态，不抛异常也不泄漏路径。"""
    try:
        # 通过模块属性取 engine，测试才能 monkeypatch backend.db.engine 换掉真实库。
        with db.engine.connect() as conn:
            conn.execute(text('SELECT 1'))
    except SQLAlchemyError as exc:
        logger.warning('健康检查失败：%s', type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={'status': 'degraded', 'db': 'error', 'version': __version__},
        )
    return {'status': 'ok', 'db': 'ok', 'version': __version__}
