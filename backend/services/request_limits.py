"""请求体大小上限：纯 ASGI 中间件，防止超大请求把端点的解析与内存打爆。

上限读环境变量 REQUEST_MAX_BODY_BYTES，每个请求都读一次（与 ratelimit/quota 的
env 约定一致，测试可用 monkeypatch 覆盖）：缺失/非法/负数回落默认 2097152（2MB），
0 表示关闭。有 Content-Length 的请求直接预检，超限不读 body 就回 413；
没有 Content-Length 的请求在 receive 侧逐块累计，超限即中止解析。
纯 ASGI 透传、不缓冲 body，不影响 SSE 响应。
"""

import os

from fastapi import HTTPException
from fastapi.responses import JSONResponse

_DEFAULT_LIMIT = 2097152  # 2MB；线上最大的合法请求（含地点照片的行程草稿）在 1MB 量级


_DETAIL = '请求体过大，请减少内容后重试。'


class _BodyTooLarge(HTTPException):
    """内部信号：请求体超过上限。继承 HTTPException(413) 是有意的：FastAPI 路由层会把
    body 读取期间的普通异常统一转成 400（"There was an error parsing the body"），
    但对 HTTPException 子类原样上抛（fastapi/routing.py 的 except HTTPException: raise），
    交给 ExceptionMiddleware 渲染 413；BodyLimitMiddleware 自己的 except 只兜"响应已开始"的极端情况。"""

    def __init__(self):
        super().__init__(status_code=413, detail=_DETAIL)


def max_body_bytes() -> int:
    """当前请求体字节上限；REQUEST_MAX_BODY_BYTES 非法或负数回落默认值，0 表示关闭。"""
    try:
        value = int(os.getenv('REQUEST_MAX_BODY_BYTES', str(_DEFAULT_LIMIT)))
    except ValueError:
        return _DEFAULT_LIMIT
    return value if value >= 0 else _DEFAULT_LIMIT


def _content_length(scope) -> int | None:
    """从 ASGI headers 取 Content-Length；缺失或非法时返回 None（改走流式累计路径）。"""
    for key, value in scope.get('headers') or []:
        if key == b'content-length':
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _reject(scope, receive, send):
    """照项目 429 的回包模式回 413，让外层的请求 ID 与访问日志照常工作。"""
    response = JSONResponse(status_code=413, content={'detail': _DETAIL})
    await response(scope, receive, send)


class BodyLimitMiddleware:
    """请求体大小上限中间件；注册顺序应放在限流内侧（先扣限流令牌，再拒超大包）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        limit = max_body_bytes()
        if limit <= 0:  # 0 = 关闭
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _reject(scope, receive, send)
            return
        received = 0
        started = False

        async def limited_receive():
            # 无 Content-Length 时逐块累计；有声明值也兜一道，防声明小于真实 body。
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            # 现网端点都在 body 解析完之后才开始回包，超限不会撞上已开始的响应；
            # 留此防御：若未来出现违反假设的流式端点，宁可上抛也不在响应中途塞第二个 start。
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                raise
            await _reject(scope, receive, send)
