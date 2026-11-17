"""进程内复用的出站 HTTP 客户端。

高德搜索/详情/路线都是短请求，如果每次调用都新建 AsyncClient，就要反复做
TCP/TLS 握手，也很难把连接数控制在可预期的范围。这里按「事件循环 + 用途」
复用一个客户端：生产环境只有一个循环，连接池全程共享；测试环境每个 TestClient
有独立循环，检测到循环变化时自动新建，避免把连接借给已经关闭的循环。
"""
import asyncio
import os

import httpx

_DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=8.0)

# name -> (创建它的事件循环, 客户端)。按用途分开：高德是短超时，模型调用需要
# 更长的读超时，共用一个 Timeout 配置会让两者互相牵制。
_clients: dict[str, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def _limits() -> httpx.Limits:
    return httpx.Limits(
        max_connections=int(os.getenv('HTTP_MAX_CONNECTIONS', '120')),
        max_keepalive_connections=int(os.getenv('HTTP_MAX_KEEPALIVE', '40')),
        keepalive_expiry=30.0,
    )


def shared_client(name: str = 'default', timeout: httpx.Timeout | None = None) -> httpx.AsyncClient:
    """返回当前事件循环可用的共享客户端。

    同一 (循环, name) 只建一次；循环切换（测试里每个 TestClient 一个循环）时
    新建客户端。旧循环的客户端无法在此处 await 关闭，由 close_shared_client
    或进程退出兜底。
    """
    loop = asyncio.get_running_loop()
    entry = _clients.get(name)
    if entry is None or entry[1].is_closed or entry[0] is not loop:
        _clients[name] = (loop, httpx.AsyncClient(
            timeout=timeout or _DEFAULT_TIMEOUT,
            limits=_limits(),
            follow_redirects=False,
        ))
    return _clients[name][1]


async def close_shared_client() -> None:
    """应用关闭时释放连接；重复调用安全。"""
    clients = [client for _, client in _clients.values()]
    _clients.clear()
    for client in clients:
        if client.is_closed:
            continue
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 - 关闭失败不应阻塞进程退出
            pass
