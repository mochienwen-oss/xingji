"""高并发加固的回归测试：地点详情缓存、模型瞬时故障重试、安全响应头。"""
import json

import httpx
import pytest

from backend.services import amap, llm
from tests.conftest import login


@pytest.mark.anyio
async def test_find_places_reuses_cached_detail(monkeypatch):
    calls = []

    async def fake(path, params):
        ids = params['id'].split('|')
        calls.append(ids)
        return {'pois': [{'id': pid, 'name': f'地点{pid}', 'location': '110.1,25.2'} for pid in ids]}

    monkeypatch.setattr(amap, 'amap', fake)
    await amap.find_places(['1', '2'])
    await amap.find_places(['2', '3'])

    # 第二次只有 3 需要回源，2 走 5 分钟 TTL 缓存。
    assert calls == [['1', '2'], ['3']]


@pytest.mark.anyio
async def test_model_json_retries_transient_transport_error(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://model.local/v1')
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_MODEL', 'test-model')
    monkeypatch.setattr(llm, 'LLM_QUEUE_TIMEOUT_SECONDS', 0.5)
    monkeypatch.setattr(llm, 'LLM_RETRY_ATTEMPTS', 2)
    monkeypatch.setattr(llm, 'LLM_RETRY_BACKOFF_SECONDS', 0.0)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'finish_reason': 'stop',
                                 'message': {'content': json.dumps({'ok': True})}}]}

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError('boom', request=httpx.Request('POST', url))
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(llm, 'shared_client', lambda **kwargs: fake)
    result = await llm.model_json([{'role': 'user', 'content': '{}'}])
    assert result == {'ok': True}
    assert fake.calls == 2


def test_api_responses_carry_security_headers(client):
    c, _places = client
    response = c.get('/api/health')
    assert response.status_code == 200
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'SAMEORIGIN'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'strict-origin-when-cross-origin'
    assert response.headers['x-permitted-cross-domain-policies'] == 'none'
    assert response.headers['strict-transport-security'] == 'max-age=31536000; includeSubDomains'
    permissions = response.headers['permissions-policy']
    assert 'geolocation=(self)' in permissions
    assert 'camera=()' in permissions
    csp = response.headers['content-security-policy-report-only']
    assert "default-src 'self'" in csp
    assert 'https://webapi.amap.com' in csp
    # 只观察不拦截：不能出现强制版的 CSP，否则高德地图会被浏览器拦掉。
    assert 'content-security-policy' not in response.headers

def test_login_cookie_has_secure_flags_under_https(client, monkeypatch):
    """生产 HTTPS 下会话 cookie 必须带 Secure，避免明文 HTTP 请求把它带出去。"""
    c, _places = client
    monkeypatch.setenv('COOKIE_SECURE', 'true')
    response = login(c)
    assert response.status_code == 200
    raw = response.headers['set-cookie']
    attrs = {part.strip().lower() for part in raw.split(';')}
    assert raw.startswith('trip_session=')
    assert 'secure' in attrs
    assert 'httponly' in attrs
    assert 'samesite=lax' in attrs
    assert 'path=/' in attrs


def test_login_cookie_omits_secure_on_plain_http(client, monkeypatch):
    """本地 HTTP 只能不要 Secure，否则浏览器不会保存 cookie，登录看起来成功却掉线。"""
    c, _places = client
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    response = login(c)
    assert response.status_code == 200
    attrs = {part.strip().lower() for part in response.headers['set-cookie'].split(';')}
    assert 'secure' not in attrs
    assert 'httponly' in attrs
    assert 'samesite=lax' in attrs
