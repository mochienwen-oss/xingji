"""B10：模型并发闸门的排队上限、快速 503 与令牌释放。

闸门是进程级单例（backend/services/llm.py:SEMAPHORE），测试里换成独立信号量，
避免依赖真实并发；LLM_QUEUE_TIMEOUT_SECONDS 直接调小到 0.05，保证用例毫秒级结束。
"""
import asyncio
import json

import pytest

from backend.services import llm
from backend.services.errors import ServiceError


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch):
    """model_json 先校验配置：固定成 DeepSeek 分支，避免本机 LLM_BASE_URL 干扰。"""
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.delenv('LLM_BASE_URL', raising=False)
    monkeypatch.setattr(llm, 'LLM_QUEUE_TIMEOUT_SECONDS', 0.05)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """只实现 model_json 非流式分支需要的 AsyncClient 协议。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def _fake_client(content: dict) -> _FakeClient:
    payload = {'choices': [{'finish_reason': 'stop',
                            'message': {'content': json.dumps(content, ensure_ascii=False)}}]}
    return _FakeClient(payload)


@pytest.mark.anyio
async def test_full_gate_fails_fast_with_503(monkeypatch):
    gate = asyncio.Semaphore(1)
    await gate.acquire()
    monkeypatch.setattr(llm, 'SEMAPHORE', gate)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(ServiceError) as excinfo:
        await llm.model_json([{'role': 'user', 'content': '{}'}])
    elapsed = loop.time() - started

    assert excinfo.value.status_code == 503
    assert str(excinfo.value) == 'AI 服务繁忙，请稍后重试。'
    # 必须是从 asyncio.TimeoutError 转出来的，而不是被外层 ValueError 分支吞掉。
    assert isinstance(excinfo.value.__cause__, asyncio.TimeoutError)
    assert elapsed < 1.0
    # 超时的请求没有拿到令牌，绝不能 release，否则并发上限会被凭空放大。
    assert gate._value == 0


@pytest.mark.anyio
async def test_success_acquires_and_releases_gate(monkeypatch):
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(llm, 'SEMAPHORE', gate)
    fake = _fake_client({'reply': 'ok', 'changed': False})
    monkeypatch.setattr(llm, 'shared_client', lambda *args, **kwargs: fake)

    result = await llm.model_json([{'role': 'user', 'content': '你好'}])

    assert result == {'reply': 'ok', 'changed': False}
    assert gate._value == 1
    assert fake.calls and fake.calls[0][0] == 'https://api.deepseek.com/chat/completions'


@pytest.mark.anyio
async def test_upstream_failure_still_releases_gate(monkeypatch):
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(llm, 'SEMAPHORE', gate)

    class _BrokenClient(_FakeClient):
        async def post(self, url, **kwargs):
            raise ValueError('broken payload')

    monkeypatch.setattr(llm, 'shared_client', lambda *args, **kwargs: _BrokenClient({}))

    with pytest.raises(llm.ModelOutputError):
        await llm.model_json([{'role': 'user', 'content': 'x'}])
    assert gate._value == 1


@pytest.mark.anyio
async def test_timeout_does_not_leak_tokens(monkeypatch):
    gate = asyncio.Semaphore(1)
    await gate.acquire()
    monkeypatch.setattr(llm, 'SEMAPHORE', gate)

    for _ in range(3):
        with pytest.raises(ServiceError) as excinfo:
            await llm.model_json([{'role': 'user', 'content': 'x'}])
        assert excinfo.value.status_code == 503
        assert gate._value == 0

    gate.release()
    assert gate._value == 1
