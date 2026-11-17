"""P1-5 请求体大小上限：Content-Length 预检与无长度流式累计都回 413，正常请求不受影响。"""

import json

import pytest

from backend.main import app
from tests.conftest import login

_TWO_MB = 2 * 1024 * 1024
_JSON_HEADERS = {'content-type': 'application/json'}
_DETAIL = '请求体过大，请减少内容后重试。'


def _sized_body(size: int) -> bytes:
    """构造恰好 size 字节的 JSON 请求体；超限场景下它不会被解析，形状只需保持合法 JSON。"""
    head = b'{"username": "'
    tail = b'", "password": "password1"}'
    return head + b'a' * (size - len(head) - len(tail)) + tail


def _post(c, body: bytes):
    return c.post('/api/login', content=body, headers=_JSON_HEADERS)


def test_oversize_body_with_content_length_returns_413(client):
    c, _ = client
    response = _post(c, _sized_body(_TWO_MB + 1))
    assert response.status_code == 413
    assert response.json()['detail'] == _DETAIL
    # 413 也经过 RequestIdMiddleware：带 X-Request-ID，访问日志可追踪
    assert response.headers.get('x-request-id')


def test_default_limit_boundary_and_normal_requests(client):
    c, _ = client
    # 常规登录不受影响
    assert login(c).status_code == 200
    # 恰好等于上限：不拒（超过才拒），穿过中间件到达端点，因 username 超长被 422
    assert _post(c, _sized_body(_TWO_MB)).status_code == 422
    # 超限一字节：413
    assert _post(c, _sized_body(_TWO_MB + 1)).status_code == 413


def test_stream_without_content_length_within_limit_still_works(client):
    c, _ = client
    body = json.dumps({'username': 'alice', 'password': 'password1'}).encode('utf-8')
    # 生成器 body：httpx 走 chunked、无 Content-Length，靠 receive 侧累计放行
    response = c.post('/api/login', content=iter([body]), headers=_JSON_HEADERS)
    assert response.status_code == 200


def test_oversize_stream_without_content_length_returns_413(client):
    c, _ = client
    body = _sized_body(_TWO_MB + 1)
    response = c.post('/api/login', content=iter([body]), headers=_JSON_HEADERS)
    assert response.status_code == 413
    assert response.json()['detail'] == _DETAIL


@pytest.mark.anyio
async def test_chunked_stream_aborts_mid_body(client, monkeypatch):
    monkeypatch.setenv('REQUEST_MAX_BODY_BYTES', '64')
    calls = {'receive': 0}
    # 4 块各 20B：20/40/60 都放行，第 4 块把累计推到 80 > 64，取到即中止
    messages = [
        {'type': 'http.request', 'body': b'a' * 20, 'more_body': True},
        {'type': 'http.request', 'body': b'b' * 20, 'more_body': True},
        {'type': 'http.request', 'body': b'c' * 20, 'more_body': True},
        {'type': 'http.request', 'body': b'd' * 20, 'more_body': False},
    ]

    async def receive():
        calls['receive'] += 1
        return messages[calls['receive'] - 1]

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': '/api/login',
        'raw_path': b'/api/login',
        'root_path': '',
        'query_string': b'',
        'headers': [(b'content-type', b'application/json')],
        'client': ('127.0.0.1', 60000),
        'server': ('testserver', 80),
    }
    await app(scope, receive, send)
    assert sent[0]['type'] == 'http.response.start' and sent[0]['status'] == 413
    assert json.loads(sent[-1]['body'])['detail'] == _DETAIL
    # 第 4 块被取走后立即中止：应用最多只见到前 3 块，body 解析从未完成
    assert calls['receive'] == 4


def test_env_override_and_disable(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('REQUEST_MAX_BODY_BYTES', '1024')
    assert _post(c, _sized_body(1024)).status_code == 422
    assert _post(c, _sized_body(1025)).status_code == 413
    monkeypatch.setenv('REQUEST_MAX_BODY_BYTES', '0')  # 0 = 关闭
    assert _post(c, _sized_body(_TWO_MB + 1)).status_code == 422


def test_invalid_env_falls_back_to_default(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('REQUEST_MAX_BODY_BYTES', 'not-a-number')
    assert _post(c, _sized_body(_TWO_MB + 1)).status_code == 413
    monkeypatch.setenv('REQUEST_MAX_BODY_BYTES', '-5')  # 负数回落默认，而不是当作关闭
    assert _post(c, _sized_body(_TWO_MB + 1)).status_code == 413
