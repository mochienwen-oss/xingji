"""匿名用户每日免费配额：进程内按 UTC 日期计数。

只统计匿名请求；登录用户由 main.RateLimitMiddleware 直接跳过。
单机单 worker 下有效，多 worker 各自计数；RATE_LIMIT_DISABLED 只关闭令牌桶，不影响这里。
"""
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone

from . import redis_bus

log = logging.getLogger(__name__)

_MAX_BUCKETS = 10000  # 防止按 IP 无限堆积：超限时先清掉两天前的日期桶
_DEFAULTS = {'llm': 30, 'amap': 300}
_ENV_NAMES = {'llm': 'ANON_LLM_DAILY', 'amap': 'ANON_AMAP_DAILY'}

# 精确路径集合：只用字符串相等判断，避免 /api/inspiration/themes 等轻量端点被误计数。
_LLM_PATHS = frozenset({
    '/api/planning/preview',
    '/api/planning/chat',
    '/api/planning/chat/stream',
    # P1-1 探索页主生成端点：匿名主入口，直接烧 LLM，必须计入每日配额。
    '/api/planning/session/stream',
    '/api/planning/preview/assistant/stream',
})
_AMAP_PATHS = frozenset({
    '/api/places',
    '/api/places/details',
    '/api/discover/nearby',
    '/api/discover/city-center',
    '/api/inspiration',
    # 分享页会补全整条行程的地点详情，刷新一次就是一批高德调用；匿名访问按 amap 计费。
    '/api/shares/view',
})

_buckets: dict[tuple[str, str, str], int] = {}  # (scope, IP, UTC 日期) -> 已用次数
_lock = threading.Lock()


def limit(scope: str) -> int:
    """读取 scope 的每日上限：每次调用都读环境变量；缺失、非法或负数回落默认值。0 表示关闭配额。"""
    default = _DEFAULTS.get(scope, 0)
    name = _ENV_NAMES.get(scope)
    if not name:
        return default
    try:
        value = int(os.getenv(name, '').strip())
    except (TypeError, ValueError):
        return default
    return default if value < 0 else value


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _prune_locked(today: str) -> None:
    """清掉两天前（含）的日期桶；调用方必须已持有 _lock。

    如果全是当天/昨天的桶，再按插入顺序强制淘汰约 10%（最早创建的优先）。
    极端内存压力下个别匿名用户的当日配额会被重置，这是为了守住 _MAX_BUCKETS。
    """
    cutoff = (date.fromisoformat(today) - timedelta(days=2)).isoformat()
    for bucket in [bucket for bucket in _buckets if bucket[2] <= cutoff]:
        del _buckets[bucket]
    if len(_buckets) >= _MAX_BUCKETS:
        overflow = max(1, len(_buckets) // 10)
        for bucket in list(_buckets)[:overflow]:
            del _buckets[bucket]


# Redis 日配额：INCR 后再判断是否超限。超过上限的请求也自增，避免并发穿透；
# key 按 UTC 日期分桶，两天后自动过期。
_QUOTA_LUA = '''
local used = redis.call('INCR', KEYS[1])
if used == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
if used > tonumber(ARGV[1]) then
  return 0
end
return 1
'''

async def hit_shared(scope: str, key: str) -> bool:
    """分布式日配额：配置 Redis 时按共享计数，否则回落到进程内 hit。"""
    cap = limit(scope)
    if cap == 0:
        return True
    client = redis_bus.client()
    if client is None:
        return hit(scope, key)
    bucket = f'xingji:quota:{scope}:{_today()}:{key}'
    try:
        return bool(int(await client.eval(_QUOTA_LUA, 1, bucket, cap, 172800)))
    except Exception as exc:  # noqa: BLE001 - Redis 故障时降级本地计数，保证业务可用
        log.warning('Redis 配额不可用，降级到进程内计数：%s', type(exc).__name__)
        redis_bus.mark_failure()
        return hit(scope, key)

def hit(scope: str, key: str) -> bool:
    """登记一次请求；True 表示放行，False 表示当天配额已用完。"""
    cap = limit(scope)
    if cap == 0:
        return True
    with _lock:
        today = _today()
        if len(_buckets) >= _MAX_BUCKETS:
            _prune_locked(today)
        bucket = (scope, key, today)
        used = _buckets.get(bucket, 0)
        if used >= cap:
            return False
        _buckets[bucket] = used + 1
        return True


def reset() -> None:
    """清空所有计数（测试用）。"""
    with _lock:
        _buckets.clear()


def scope_for_path(path: str) -> str | None:
    """只映射匿名可访问的高成本端点；其他路径返回 None，不计数。"""
    if path in _LLM_PATHS:
        return 'llm'
    if path in _AMAP_PATHS:
        return 'amap'
    return None
