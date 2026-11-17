"""Redis 共享状态：配置后走共享计数，故障时回退进程内实现。"""
from datetime import datetime, timezone

import pytest

from backend.services import live, quota, ratelimit, redis_bus


class FakeRedis:
    def __init__(self, reply=(1, 0), error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_bus, '_client', fake)
    monkeypatch.setattr(redis_bus, '_available', True)
    monkeypatch.setattr(redis_bus, '_disabled_until', 0.0)
    return fake


@pytest.mark.anyio
async def test_rate_limit_uses_shared_bucket_when_redis_is_available(fake_redis):
    fake_redis.reply = [1, 0]
    allowed, retry = await ratelimit.check_shared('/api/planning/preview', '203.0.113.7')
    assert (allowed, retry) == (True, 0)
    script, count, key = fake_redis.calls[0][:3]
    assert 'redis.call' in script and count == 1
    assert key.startswith('xingji:ratelimit:')
    assert key.endswith('203.0.113.7')


@pytest.mark.anyio
async def test_rate_limit_shared_denial_returns_wait_seconds(fake_redis):
    fake_redis.reply = [0, 7]
    assert await ratelimit.check_shared('/api/planning/preview', 'ip') == (False, 7)


@pytest.mark.anyio
async def test_rate_limit_falls_back_to_local_bucket_on_redis_error(fake_redis):
    fake_redis.error = RuntimeError('redis down')
    local = ratelimit.check

    def failing_local(path, key):
        return False, 9

    ratelimit.check = failing_local
    try:
        assert await ratelimit.check_shared('/api/planning/preview', 'ip') == (False, 9)
    finally:
        ratelimit.check = local


@pytest.mark.anyio
async def test_quota_uses_shared_counter_keyed_by_utc_date(monkeypatch, fake_redis):
    monkeypatch.setenv('ANON_LLM_DAILY', '3')
    fake_redis.reply = 1
    assert await quota.hit_shared('llm', '198.51.100.9') is True
    key = fake_redis.calls[0][2]
    today = datetime.now(timezone.utc).date().isoformat()
    assert key == f'xingji:quota:llm:{today}:198.51.100.9'
    fake_redis.reply = 0
    assert await quota.hit_shared('llm', '198.51.100.9') is False


@pytest.mark.anyio
async def test_quota_falls_back_to_local_counter_on_redis_error(fake_redis):
    fake_redis.error = RuntimeError('redis down')
    monkeypatch_local = quota.hit

    def failing_local(scope, key):
        return False

    quota.hit = failing_local
    try:
        assert await quota.hit_shared('llm', 'ip') is False
    finally:
        quota.hit = monkeypatch_local


class FakeLiveRedis:
    """只实现 presence 用到的 ZSET 命令，足够验证跨 worker 在线名单读取。"""

    def __init__(self, members):
        self.members = list(members)

    async def zremrangebyscore(self, key, low, high):
        return 0

    async def zrangebyscore(self, key, low, high):
        return list(self.members)


@pytest.mark.anyio
async def test_online_count_reads_cross_worker_presence_from_redis(monkeypatch):
    members = [
        '{"connection_id":"a","user_id":1,"username":"alice"}',
        '{"connection_id":"b","user_id":1,"username":"alice"}',
        '{"connection_id":"c","user_id":2,"username":"bob"}',
        'not-json',
    ]
    fake = FakeLiveRedis(members)
    monkeypatch.setattr(redis_bus, '_client', fake)
    monkeypatch.setattr(redis_bus, '_available', True)
    monkeypatch.setattr(redis_bus, '_disabled_until', 0.0)
    live._shared_presence.clear()
    try:
        assert await live.online_count_shared(42) == 2
        # 读取结果写入本地缓存，同步 online_count 也能直接命中。
        assert live.online_count(42) == 2
    finally:
        live._shared_presence.clear()


@pytest.mark.anyio
async def test_online_count_falls_back_to_local_when_redis_fails(monkeypatch):
    class Broken:
        async def zremrangebyscore(self, *args):
            raise RuntimeError('down')

    monkeypatch.setattr(redis_bus, '_client', Broken())
    monkeypatch.setattr(redis_bus, '_available', True)
    monkeypatch.setattr(redis_bus, '_disabled_until', 0.0)
    assert await live.online_count_shared(999999) == 0
