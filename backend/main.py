import asyncio
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager, suppress
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from .auth import read_token
from .db import engine, prepare_database
from .services import accounts, live, mailer, maintenance, metrics, quota, ratelimit, redis_bus, request_limits
from .services.errors import ServiceError
from .services.http_pool import close_shared_client
from .api import health, account, auth, inspiration, planning, trips, shares, budget, reports, ops, pages

logger = logging.getLogger('trip')
MAINTENANCE_INTERVAL_SECONDS = 3600  # 过期数据清理频率：请求路径不再做清理


async def _maintenance_loop() -> None:
    """按小时清理过期数据：放到线程里跑，避免同步数据库操作阻塞事件循环。"""
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        try:
            counts = await asyncio.to_thread(maintenance.purge_expired_once)
            if any(counts.values()):
                logger.info('后台清理：过期邀请 %s 条，过期/已用账户 token %s 条，过期软删行程 %s 条',
                            counts['invites'], counts['tokens'], counts['trips'])
        except Exception:
            logger.warning('后台清理失败，已跳过', exc_info=True)

# 访问日志挂到 uvicorn.error：uvicorn 自带 handler，生产环境无需额外日志配置。
access_logger = logging.getLogger('uvicorn.error')

@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite（本地开发/测试）在这里自动建表并补列；PostgreSQL 的表结构只由 Alembic 管理，
    # 这里只校验迁移是否已执行，缺表时直接抛错给出可操作的提示。
    prepare_database(engine)
    # Redis 是可选的跨 worker 共享状态；未配置或连接失败时各服务回退进程内实现，
    # 启动只记 warning，不阻断服务。
    await redis_bus.initialize()
    # 启动清理只是尽力而为：清理失败（锁/磁盘）记 warning，不能拖垮启动。
    try:
        counts = maintenance.purge_expired_once()
        logger.info('启动清理：过期邀请 %s 条，过期/已用账户 token %s 条，过期软删行程 %s 条',
                    counts['invites'], counts['tokens'], counts['trips'])
    except Exception:
        logger.warning('启动清理失败，已跳过', exc_info=True)
    maintenance_task = asyncio.create_task(_maintenance_loop(), name='trip-maintenance')
    if not mailer.configured():
        logger.warning('SMTP 未配置（缺少 SMTP_HOST 或 SMTP_FROM），验证与重置邮件不会发送')
    try:
        yield
    finally:
        # 进程退出时释放实时房间、Redis 订阅与共享连接池，避免开发环境反复
        # reload 留下后台任务和半开连接。
        maintenance_task.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance_task
        await live.shutdown()
        await redis_bus.close()
        await close_shared_client()

app = FastAPI(title='行迹 API', lifespan=lifespan)
# 纯文本/JSON/静态资源统一压缩；starlette 默认排除 text/event-stream 与 font/woff2，
# 所以 SSE 不会被缓冲或压缩。
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

class RateLimitMiddleware:
    """ASGI 中间件：先做令牌桶限流，再对匿名用户计每日免费配额；静态资源和其它接口直接透传。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            path = scope.get('path', '')
            client = scope.get('client')
            key = client[0] if client else 'unknown'
            allowed, retry = await ratelimit.check_shared(path, key)
            if not allowed:
                response = JSONResponse(status_code=429, headers={'Retry-After': str(retry)},
                                        content={'detail': f'操作太频繁，请 {retry} 秒后重试'})
                await response(scope, receive, send)
                return
            quota_scope = quota.scope_for_path(path)
            if quota_scope is not None:
                # 只按令牌能否解析判断匿名；不查数据库，也不额外探测 session_version。
                token = Request(scope).cookies.get(accounts.SESSION_COOKIE, '')
                if read_token(token) is None and not await quota.hit_shared(quota_scope, key):
                    response = JSONResponse(
                        status_code=429,
                        headers={'Retry-After': '3600'},
                        content={'detail': '今天的免费体验次数已用完，请登录后继续。'},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)

# 地图：脚本来自 webapi.amap.com，瓦片/字体等资源走 https。connect-src 保留 self 与高德域名，
# 便于后续把前端直连高德的能力打开时不至于被 CSP 挡掉；目前前端只连本站 API。
_CSP_REPORT_ONLY = (
    b"default-src 'self'; "
    b"script-src 'self' 'unsafe-inline' https://webapi.amap.com https://*.amap.com; "
    b"style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data: blob: https:; "
    b"font-src 'self' data:; "
    b"connect-src 'self' https://*.amap.com; "
    b"frame-src https://*.amap.com; "
    b"object-src 'none'; base-uri 'self'; form-action 'self'"
)
# 定位用于「附近」，摄像头/麦克风/支付没有业务用途，直接禁用。
_PERMISSIONS_POLICY = b'geolocation=(self), camera=(), microphone=(), payment=()'

_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')

class RequestIdMiddleware:
    """纯 ASGI 中间件：透传/生成 X-Request-ID，并记录一行访问日志。

    不用 BaseHTTPMiddleware：后者会把响应包成 anyio 流，可能缓冲并破坏 SSE。
    日志只含 method/path/status/耗时/request_id，不记录 cookie、Authorization 与 body。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request_id = self._request_id(scope)
        path = scope.get('path', '')
        status = 500
        started = time.perf_counter()
        cache_control = self._cache_control(path)

        async def send_with_request_id(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                skip = {b'x-request-id', b'x-content-type-options', b'referrer-policy',
                        b'x-frame-options', b'cache-control', b'content-security-policy-report-only',
                        b'permissions-policy', b'x-permitted-cross-domain-policies',
                        b'strict-transport-security'}
                headers = [(key, value) for key, value in message.get('headers', []) if key.lower() not in skip]
                headers.extend((
                    (b'x-request-id', request_id.encode('latin-1')),
                    (b'x-content-type-options', b'nosniff'),
                    (b'referrer-policy', b'strict-origin-when-cross-origin'),
                    (b'x-frame-options', b'SAMEORIGIN'),
                    (b'cache-control', cache_control),
                    # CSP 先 report-only：高德地图会注入内联脚本与多域名瓦片，直接强拦会白屏。
                    # 用 report-only 观察真实违规后再收紧，避免上线时把地图打死。
                    (b'content-security-policy-report-only', _CSP_REPORT_ONLY),
                    (b'permissions-policy', _PERMISSIONS_POLICY),
                    (b'x-permitted-cross-domain-policies', b'none'),
                    (b'strict-transport-security', b'max-age=31536000; includeSubDomains'),
                ))
                message['headers'] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed = time.perf_counter() - started
            # 指标记录放在 finally：异常、429、客户端断开都算一次请求，供外部探针做 5xx/429 告警。
            metrics.observe_request(scope.get('method', '-'), path, status, elapsed)
            # 分享/邀请 token 不能进日志：能读日志的人不应因此拿到访问凭据。
            access_logger.info('%s %s %s %.3fs request_id=%s',
                               scope.get('method', '-'), metrics.redact_path(path),
                               status, elapsed, request_id)

    @staticmethod
    def _cache_control(path: str) -> bytes:
        """接口一律不缓存；带指纹的构建产物长缓存，入口 HTML 每次回源校验。"""
        if path.startswith('/api/'):
            return b'no-store'
        if path.startswith('/s/'):
            return b'no-store'
        if path.startswith('/assets/'):
            return b'public, max-age=31536000, immutable'
        if path.startswith('/fonts/'):
            return b'public, max-age=2592000'
        if path in ('/favicon.svg', '/og-cover.png'):
            return b'public, max-age=86400'
        return b'no-cache'

    @staticmethod
    def _request_id(scope) -> str:
        for key, value in scope.get('headers') or ():
            if key.lower() == b'x-request-id':
                candidate = value.decode('latin-1').strip()
                # request id 会原样写回响应头并进日志：只收安全字符，挡住换行注入。
                if _REQUEST_ID_RE.fullmatch(candidate):
                    return candidate
                break
        return secrets.token_hex(8)

# 请求体上限放在限流内侧：超大请求也要先扣限流令牌/匿名配额，垃圾流量无法借 413 绕开限流。
app.add_middleware(request_limits.BodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
# 请求 ID 放在限流外层：429/413 也带 X-Request-ID；纯 ASGI 透传，不缓冲 SSE。
app.add_middleware(RequestIdMiddleware)

@app.exception_handler(ServiceError)
async def service_error(_request: Request, exc: ServiceError):
    # 上游错误的语义由 ServiceError.status_code 决定：默认 503，配置类 502，配额类 429。
    status = getattr(exc, 'status_code', 503) or 503
    metrics.record_error('upstream')
    headers = {'Retry-After': '30'} if status == 429 else None
    return JSONResponse(status_code=status, content={'detail': str(exc)}, headers=headers)

@app.exception_handler(OperationalError)
async def database_operational_error(request: Request, exc: OperationalError):
    """SQLite 锁冲突映射 503；其它 OperationalError 仍走通用 500，详情不暴露 SQL。"""
    message = str(getattr(exc, 'orig', exc)).lower()
    if 'database is locked' in message or 'database is busy' in message:
        metrics.record_error('database_busy')
        logger.warning('数据库繁忙，返回 503：%s %s', request.method, request.url.path)
        return JSONResponse(status_code=503, headers={'Retry-After': '5'}, content={'detail': '服务繁忙，请稍后重试。'})
    metrics.record_error('database')
    logger.error('数据库操作失败：%s %s', request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={'detail': '服务暂时不可用，请稍后重试'})

@app.exception_handler(PoolTimeoutError)
async def pool_timeout_error(request: Request, exc: PoolTimeoutError):
    """连接池排队超时说明服务过载：返回 503 让客户端退避，而不是 500 或挂住。"""
    metrics.record_error('pool_timeout')
    logger.warning('连接池等待超时：%s %s', request.method, request.url.path)
    return JSONResponse(status_code=503, headers={'Retry-After': '5'}, content={'detail': '服务繁忙，请稍后重试。'})

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """兜底未预期异常：统一 500 通用文案，堆栈只进日志。

    HTTPException / ServiceError / 校验错误各有专用处理器，不会被这里吞掉:
    该处理器注册在 ServerErrorMiddleware 上，只接管没有专用处理器的异常。
    """
    metrics.record_error('unhandled')
    logger.exception('未处理异常 %s %s', request.method, request.url.path)
    return JSONResponse(status_code=500, content={'detail': '服务暂时不可用，请稍后重试'})

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(planning.router)
app.include_router(trips.router)
app.include_router(shares.router)
app.include_router(budget.router)
app.include_router(inspiration.router)
app.include_router(reports.router)
app.include_router(ops.router)

dist = pages.DIST
if pages.available():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    app.mount('/fonts', StaticFiles(directory=dist / 'fonts'), name='fonts')
    # 页面路由集中在 api/pages.py；这里只负责按构建产物是否存在注册。
    app.include_router(pages.router)
