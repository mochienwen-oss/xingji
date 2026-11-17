"""需求：真实第三方联调发现高德个人 Key 的搜索接口并发配额很小（回 10021 CUQPS），
但行程生成会并行搜索多个关键词；README.md:3/83 要求能正常生成行程，不能让一次瞬时
并发超限把整页打成 503。这里验证：
- 10021（CUQPS）会退避重试，重试成功则请求正常返回；
- 重试用尽后给出「并发/稍后重试」的可操作提示，而不是误导成 Key 权限问题；
- Key 权限类确定性错误不重试，避免放大配额消耗；
- 地点缓存命中/未命中计数能被 /api/metrics 观测（README.md:102）。
"""
import httpx
import pytest

from backend.services import amap
from backend.services.errors import ServiceError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('failed', request=httpx.Request('GET', 'https://restapi.amap.com'),
                                        response=httpx.Response(self.status_code))

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return FakeResponse(payload)


def cuqps_payload():
    return {'status': '0', 'infocode': '10021', 'info': 'CUQPS_HAS_EXCEEDED_THE_LIMIT'}


def ok_payload():
    return {'status': '1', 'infocode': '10000', 'pois': []}


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(round(seconds, 3))

    monkeypatch.setattr(amap.asyncio, 'sleep', fake_sleep)
    monkeypatch.setenv('AMAP_WEB_KEY', 'test-key')
    return recorded


@pytest.mark.anyio
async def test_cuqps_is_retried_then_succeeds(monkeypatch, sleeps):
    client = FakeClient([cuqps_payload(), cuqps_payload(), ok_payload()])
    monkeypatch.setattr(amap, 'shared_client', lambda: client)

    data = await amap.amap('/v5/place/text', {'keywords': '西湖', 'region': '杭州'})

    assert data['status'] == '1'
    # 前两次并发超限都退避重试，第三次成功；退避时间递增。
    assert client.calls == 3
    assert sleeps == [amap.AMAP_RETRY_BASE_SECONDS, amap.AMAP_RETRY_BASE_SECONDS * 2]


@pytest.mark.anyio
async def test_cuqps_exhausted_reports_actionable_error(monkeypatch, sleeps):
    client = FakeClient([cuqps_payload()])
    monkeypatch.setattr(amap, 'shared_client', lambda: client)

    with pytest.raises(ServiceError) as excinfo:
        await amap.amap('/v5/place/text', {'keywords': '西湖'})

    assert client.calls == amap.AMAP_MAX_ATTEMPTS
    message = str(excinfo.value)
    assert '并发' in message and '稍后' in message
    # 不能再把并发超限误报成 Key 类型/权限问题。
    assert '权限' not in message


@pytest.mark.anyio
async def test_permission_error_is_not_retried(monkeypatch, sleeps):
    client = FakeClient([{'status': '0', 'infocode': '10009', 'info': 'USERKEY_PLAT_NOMATCH'}])
    monkeypatch.setattr(amap, 'shared_client', lambda: client)

    with pytest.raises(ServiceError) as excinfo:
        await amap.amap('/v5/place/text', {'keywords': '西湖'})

    assert client.calls == 1
    assert sleeps == []
    assert '10009' in str(excinfo.value)


@pytest.mark.anyio
async def test_place_cache_stats_count_hits_and_misses(monkeypatch):
    amap.reset_place_cache()
    calls = []

    async def batch(place_ids):
        calls.append(list(place_ids))
        return {pid: {'id': pid, 'name': pid, 'location': '120.1,30.2'} for pid in place_ids}

    monkeypatch.setattr(amap, '_find_batch', batch)
    await amap.find_places(['A', 'B'])
    await amap.find_places(['A', 'C'])
    stats = amap.cache_stats()

    # 第一次 A/B 都是未命中，第二次 A 命中、C 未命中；C 会重新回源，A 不会。
    assert stats['place_hits'] == 1
    assert stats['place_misses'] == 3
    assert stats['place_entries'] == 3
    assert calls == [['A', 'B'], ['C']]
    amap.reset_place_cache()
