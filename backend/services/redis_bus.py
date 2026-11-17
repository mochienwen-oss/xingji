"""可选的 Redis 共享状态。

单进程部署不配置 REDIS_URL 时，限流、匿名日配额与实时在线名单全部回退到
进程内实现，行为和以前完全一致。配置 REDIS_URL 后，这些跨请求/跨 worker 的
状态改由 Redis 保存，多个 uvicorn worker 之间才能共享同一份计数和在线名单。

设计取舍：
- Redis 只是可选增强，不是硬依赖。未安装 redis 包或连接失败时记 warning 并
  回退内存实现，服务仍可用；生产多 worker 应显式配置并监控连接。
- 这里只懒加载一个异步客户端；同步代码路径（单元测试直接调用的 hit/check）
  仍走各自模块的内存实现。
"""
import logging
import os
import time

log = logging.getLogger(__name__)

# Redis 故障后的短暂退避：避免每个请求都等一次连接超时、刷一条 warning。
# 30 秒后自动重试，网络恢复后无需重启进程。
FAILURE_BACKOFF_SECONDS = 30.0

_client = None
_available = False
_initialized = False
_disabled_until = 0.0


def url() -> str:
    return os.getenv('REDIS_URL', '').strip()


def configured() -> bool:
    return bool(url())


def available() -> bool:
    return _available


def client():
    """返回可用的异步 Redis 客户端；未配置/不可用/退避期内返回 None。"""
    if not _available or _client is None:
        return None
    return None if time.monotonic() < _disabled_until else _client


def mark_failure() -> None:
    """一次 Redis 调用失败后暂停使用，让后续请求立即回退内存实现。"""
    global _disabled_until
    _disabled_until = time.monotonic() + FAILURE_BACKOFF_SECONDS


async def initialize() -> bool:
    """启动时探测 Redis；失败不阻断启动，由调用方决定是否告警。"""
    global _client, _available, _initialized
    _initialized = True
    target = url()
    if not target:
        return False
    try:
        from redis.asyncio import from_url
    except ImportError:
        log.error('配置了 REDIS_URL 但未安装 redis 包，共享状态回退到进程内存；请安装 backend/requirements.txt')
        return False
    candidate = None
    try:
        candidate = from_url(
            target,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            health_check_interval=30,
        )
        await candidate.ping()
    except Exception as exc:  # noqa: BLE001 - 连接失败只降级，不拖垮应用启动
        log.warning('Redis 连接失败，共享状态回退到进程内存：%s', type(exc).__name__)
        try:
            await candidate.aclose()
        except Exception:  # noqa: BLE001
            pass
        return False
    _client, _available = candidate, True
    log.info('Redis 共享状态已启用：%s', _redact(target))
    return True


async def close() -> None:
    """关闭共享客户端；重复调用安全。"""
    global _client, _available
    client, _client, _available = _client, None, False
    if client is not None:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 - 关闭失败不阻塞进程退出
            pass



def _redact(target: str) -> str:
    """日志里不输出密码。"""
    if '@' not in target:
        return target
    scheme, rest = target.split('://', 1) if '://' in target else ('', target)
    tail = rest.rsplit('@', 1)[-1]
    return f'{scheme}://***@{tail}' if scheme else f'***@{tail}'
