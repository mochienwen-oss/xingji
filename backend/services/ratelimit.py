"""匿名端点限流：进程内令牌桶，按「路径规则 + 客户端 IP」计数。

单机 uvicorn 单 worker 下有效；多 worker 各自独立计数（需要全局配额时应前置 nginx limit_req）。
RATE_LIMIT_DISABLED=1 时整体关闭，默认开启。
"""
import logging
import math
import os
import re
import time
from typing import NamedTuple

from . import redis_bus

log = logging.getLogger(__name__)

class Rule(NamedTuple):
    pattern: re.Pattern
    capacity: float  # 桶容量，即允许的瞬时突发次数
    rate: float      # 每秒补充的令牌数

# 只覆盖会烧钱或打外部接口的匿名/半匿名路径，其余接口零开销。
RULES = [
    # B10 账户端点：发信/验 token/改密都可能被刷，容量更紧，且必须精确锚定路径，
    # 否则 /api/account/password 会误伤 /api/account/password/forgot 与 /password/reset。
    Rule(re.compile(r'^/api/account/verify-email$'), 20, 1 / 10),
    Rule(re.compile(r'^/api/account/email/resend$'), 5, 1 / 60),
    Rule(re.compile(r'^/api/account/email$'), 10, 1 / 30),
    Rule(re.compile(r'^/api/account/password/forgot$'), 5, 1 / 60),
    Rule(re.compile(r'^/api/account/password/reset$'), 10, 1 / 30),
    Rule(re.compile(r'^/api/account/password$'), 10, 1 / 30),
    Rule(re.compile(r'^/api/account/terms$'), 10, 1 / 30),
    # DELETE /api/account（注销，DELETE 无独立子路径）也走同一档限流。
    Rule(re.compile(r'^/api/account$'), 10, 1 / 30),
    # B7 账户/协作写操作：放在通用规则之前，容量更紧。
    Rule(re.compile(r'^/api/collaborators/accept$'), 10, 1 / 10),
    Rule(re.compile(r'^/api/trips/\d+/days$'), 30, 1 / 2),
    Rule(re.compile(r'^/api/trips/\d+/guide$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/trips/\d+/budget$'), 20, 1 / 5),
    Rule(re.compile(r'^/api/plaza$'), 30, 1 / 2),
    Rule(re.compile(r'^/api/planning/chat(/stream)?$'), 10, 1 / 6),
    # P1-1 探索页主生成端点：匿名可访问的主 LLM 费用面，与 chat/stream 同档（容量 10、每 6s 补 1）。
    Rule(re.compile(r'^/api/planning/session/stream$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/planning/preview$'), 12, 1 / 10),
    Rule(re.compile(r'^/api/planning/preview/assistant/stream$'), 8, 1 / 8),
    Rule(re.compile(r'^/api/trips/from-preview$'), 6, 1 / 10),
    # 分享码加入：8 位码仍可能与码空间擦肩，收紧到 5 次突发、每 30s 补 1，极大抬高枚举成本。
    Rule(re.compile(r'^/api/trips/join$'), 5, 1 / 30),
    # 列表/分享/邀请/导出等此前零覆盖的路径：分享页与导出会读全量数据或外部缓存。
    Rule(re.compile(r'^/api/trips/shared$'), 30, 1 / 2),
    Rule(re.compile(r'^/api/trips/\d+/join-code$'), 20, 1 / 10),
    Rule(re.compile(r'^/api/trips/\d+/visibility$'), 20, 1 / 10),
    Rule(re.compile(r'^/api/trips/\d+/restore$'), 10, 1 / 30),
    Rule(re.compile(r'^/api/trips/\d+/share$'), 20, 1 / 10),
    Rule(re.compile(r'^/api/trips/\d+/collaborators(/[^/]+)?$'), 10, 1 / 10),
    Rule(re.compile(r'^/api/trips/\d+/expenses'), 30, 1 / 5),
    Rule(re.compile(r'^/api/account/export$'), 3, 1 / 60),
    Rule(re.compile(r'^/api/trips$'), 20, 1 / 5),
    # 分享入口的专用档位必须排在通用的 ^/api/shares/{token}$ 之前：match() 命中第一条就返回，
    # 放到后面会让 60 次/3s 的通用档位顶掉 view（30/2s）与 fork（6/30s）。
    Rule(re.compile(r'^/api/shares/view$'), 30, 1 / 2),
    Rule(re.compile(r'^/api/shares/fork$'), 6, 1 / 30),
    Rule(re.compile(r'^/api/shares/[^/]+$'), 60, 1 / 3),
    # 公开分享落地页（GET /s/{token}）匿名可访问且服务端渲染整页 HTML：与分享读取同档，
    # 避免攻击者用不存在的 token 无限刷渲染与磁盘读。
    Rule(re.compile(r'^/s/[^/]+$'), 60, 1 / 2),
    Rule(re.compile(r'^/api/plaza/\d+/fork$'), 6, 1 / 30),
    # A11 UGC 举报：匿名也能提交，必须比通用行程规则更紧；每 IP 每小时最多 3 条。
    Rule(re.compile(r'^/api/trips/\d+/report$'), 3, 1 / 3600),
    Rule(re.compile(r'^/api/shares/[^/]+/report$'), 3, 1 / 3600),
    Rule(re.compile(r'^/api/admin'), 10, 1 / 60),
    Rule(re.compile(r'^/api/(login|register)$'), 10, 1 / 60),
    Rule(re.compile(r'^/api/trips/\d+$'), 60, 1.0),
    Rule(re.compile(r'^/api/trips/\d+/days/\d+/routes$'), 30, 1 / 5),
    # 真实路由是 /api/trips/{trip_id}/days/{day_index}/nearby（旧规则少一段，永不命中）。
    Rule(re.compile(r'^/api/trips/\d+/days/\d+/nearby$'), 30, 1 / 3),
    Rule(re.compile(r'^/api/trips/\d+/assistant(/stream)?$'), 20, 1 / 3),
    Rule(re.compile(r'^/api/trips/\d+/guide/outline$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/trips/\d+/days/\d+/optimize$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/trips/\d+/budget/estimate$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/inspiration$'), 10, 1 / 6),
    Rule(re.compile(r'^/api/places'), 60, 1.0),
    Rule(re.compile(r'^/api/discover'), 60, 1.0),
]

_buckets: dict[tuple[str, int], tuple[float, float]] = {}  # (key, 规则序号) -> (令牌数, 上次刷新时间)
_MAX_BUCKETS = 10000  # 防止按 IP 无限堆积：超过上限时清掉一小时未活跃的桶

def enabled() -> bool:
    return os.getenv('RATE_LIMIT_DISABLED', '').strip().lower() not in ('1', 'true', 'yes')

def reset() -> None:
    """清空所有计数（测试用）。"""
    _buckets.clear()

def match(path: str) -> Rule | None:
    """返回命中的规则；未命中即不限流。"""
    for rule in RULES:
        if rule.pattern.match(path):
            return rule
    return None

# Redis 令牌桶：整个读-改-写在一段 Lua 里完成，多个 worker 并发时不会超发。
# KEYS[1] 是桶 key；ARGV = 容量、每秒补充、当前时间、过期秒数。
_TOKEN_BUCKET_LUA = '''
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(data[1])
local updated = tonumber(data[2])
if tokens == nil or updated == nil then
  tokens = capacity
  updated = now
end
tokens = math.min(capacity, tokens + (now - updated) * rate)
if tokens < 1 then
  redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
  local wait = math.ceil((1 - tokens) / rate)
  if wait < 1 then wait = 1 end
  return {0, wait}
end
tokens = tokens - 1
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return {1, 0}
'''

async def check_shared(path: str, key: str) -> tuple[bool, int]:
    """分布式令牌桶：配置了 Redis 时跨 worker 共享，否则回落到进程内 check。

    Redis 调用失败时按内存实现继续放行/限流，保证限流组件本身不会成为单点故障。
    """
    if not enabled():
        return True, 0
    rule = match(path)
    if rule is None:
        return True, 0
    client = redis_bus.client()
    if client is None:
        return check(path, key)
    index = RULES.index(rule)
    bucket = f'xingji:ratelimit:{index}:{key}'
    try:
        result = await client.eval(
            _TOKEN_BUCKET_LUA, 1, bucket,
            rule.capacity, rule.rate, time.time(), 3600,
        )
        return bool(int(result[0])), int(result[1])
    except Exception as exc:  # noqa: BLE001 - Redis 故障时降级到本地桶，避免全站 429/500
        log.warning('Redis 限流不可用，降级到进程内计数：%s', type(exc).__name__)
        redis_bus.mark_failure()
        return check(path, key)

def _prune_buckets(now: float) -> None:
    """条目数达到上限时回收空间；调用方无需持锁（进程内单线程使用）。

    先清一小时未活跃的桶；若全是活跃桶，再按最近使用时间强制淘汰约 10%。
    极端情况下会重置少量客户端的令牌桶（等同于提前补充令牌），这是为了
    保证字典有硬上限，避免伪造 IP 把进程内存打满。
    """
    if len(_buckets) < _MAX_BUCKETS:
        return
    for old_key, (_, seen) in list(_buckets.items()):
        if now - seen > 3600:
            _buckets.pop(old_key, None)
    if len(_buckets) >= _MAX_BUCKETS:
        overflow = max(1, len(_buckets) // 10)
        for old_key, _ in sorted(_buckets.items(), key=lambda item: item[1][1])[:overflow]:
            _buckets.pop(old_key, None)

def check(path: str, key: str) -> tuple[bool, int]:
    """判断这次请求能否放行，返回 (是否放行, 需要等待的整数秒)。"""
    if not enabled():
        return True, 0
    rule = match(path)
    if rule is None:
        return True, 0
    index = RULES.index(rule)
    now = time.monotonic()
    # 清理放在限流分支之前：被限流的来源同样会更新条目，不能让它绕过内存上限。
    _prune_buckets(now)
    tokens, updated = _buckets.get((key, index), (rule.capacity, now))
    tokens = min(rule.capacity, tokens + (now - updated) * rule.rate)
    if tokens < 1:
        _buckets[(key, index)] = (tokens, now)
        return False, max(1, math.ceil((1 - tokens) / rule.rate))
    _buckets[(key, index)] = (tokens - 1, now)
    return True, 0
