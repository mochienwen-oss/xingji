"""模型响应失败鲁棒化：内容级失败重试、容错解析与准确文案。

上游偶发截断 JSON、缺 choices/content（线上日志见 Unterminated string / KeyError: content），
这类"内容不可用"要和 5xx 一样重试；本文件手写 fake httpx.AsyncClient 静态复现，
monkeypatch 掉 AsyncClient 与退避时间，绝不发真实网络请求。
"""
import asyncio
import json
import logging

import httpx
import pytest

from backend.services import llm

REPLY = {'reply': '好的', 'changed': True}
TRUNCATED = '{"reply": "好的", "changed"'
AUTH_ERROR = '模型服务认证失败，请检查 API Key 和模型使用权限。'
NETWORK_ERROR = '无法连接模型服务或请求超时，请检查网络后重试。'
FORMAT_ERROR = '模型返回内容不完整或格式无效，请重试。'
EMPTY_ERROR = '模型没有返回有效内容，请重试。'
LENGTH_ERROR = '模型输出超过长度限制，请简化旅行需求后重试。'


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch):
    """固定配置、零退避和独立信号量：用例毫秒级结束，也不污染其它测试的闸门。"""
    monkeypatch.setenv('LLM_BASE_URL', 'https://model.test/v1')
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_MODEL', 'test-model')
    monkeypatch.setattr(llm, 'LLM_RETRY_ATTEMPTS', 2)
    monkeypatch.setattr(llm, 'LLM_RETRY_BACKOFF_SECONDS', 0.0)
    monkeypatch.setattr(llm, 'SEMAPHORE', asyncio.Semaphore(4))


def _payload(content, finish_reason='stop'):
    """拼一个 chat/completions 响应体；content 传 None 复现结构缺失。"""
    return {'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}]}


def _json_reply(value=REPLY, ensure_ascii=False):
    return json.dumps(value, ensure_ascii=False)


class _Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request('POST', 'https://model.test/v1/chat/completions')

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f'HTTP {self.status_code}', request=self.request, response=self)

    def json(self):
        return self._payload


class _Client:
    """按顺序回放 replies（用完最后一个就重复它），并记录每次 POST。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, _Response) else _Response(reply)


def _use_client(monkeypatch, replies):
    fake = _Client(replies)
    monkeypatch.setattr(llm, 'shared_client', lambda *args, **kwargs: fake)
    return fake


class _StreamResponse:
    def __init__(self, script):
        self._script = list(script)
        self.status_code = 200
        self.request = httpx.Request('POST', 'https://model.test/v1/chat/completions')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            yield item


class _StreamClient:
    """按顺序回放每轮流式脚本（最后一个脚本重复用）。"""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def stream(self, method, url, **kwargs):
        self.calls.append((url, kwargs))
        script = self.scripts.pop(0) if len(self.scripts) > 1 else self.scripts[0]
        return _StreamResponse(script)


def _use_stream_client(monkeypatch, scripts):
    fake = _StreamClient(scripts)
    monkeypatch.setattr(llm, 'shared_client', lambda *args, **kwargs: fake)
    return fake


def _sse(*chunks, done=True):
    """把增量正文拼成 SSE 行，done=True 时补 [DONE] 收尾。"""
    lines = ['data: ' + json.dumps({'choices': [{'delta': {'content': chunk}}]}) for chunk in chunks]
    if done:
        lines.append('data: [DONE]')
    return lines


def _connect_error():
    return httpx.ConnectError('boom', request=httpx.Request('POST', 'https://model.test/v1/chat/completions'))


def _messages():
    return [{'role': 'user', 'content': '你好'}]


@pytest.mark.anyio
async def test_truncated_json_then_complete_retries(monkeypatch):
    """首次截断 JSON（线上报错原文场景）、第二次完整：重试后正常返回。"""
    fake = _use_client(monkeypatch, [_payload(TRUNCATED), _payload(_json_reply())])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_truncated_json_twice_keeps_format_error_copy(monkeypatch):
    """两次都截断：保持前端已在用的"格式无效"文案。"""
    fake = _use_client(monkeypatch, [_payload(TRUNCATED)])

    with pytest.raises(llm.ModelOutputError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == FORMAT_ERROR
    assert excinfo.value.status_code == 502
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_missing_content_then_success_retries(monkeypatch):
    """message.content=None 属于内容级失败，第二次拿到正文就该成功。"""
    fake = _use_client(monkeypatch, [_payload(None), _payload(_json_reply())])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 2


@pytest.mark.parametrize('content', [None, '', '   '])
@pytest.mark.anyio
async def test_unusable_content_twice_reports_empty_reply(monkeypatch, content):
    """content 缺失/空串耗尽重试：用"没有返回有效内容"而不是"格式无效"。"""
    fake = _use_client(monkeypatch, [_payload(content)])

    with pytest.raises(llm.ModelOutputError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == EMPTY_ERROR
    assert len(fake.calls) == 2


@pytest.mark.parametrize('payload', [{}, {'choices': []}, {'choices': ['bad']}, {'choices': [{'finish_reason': 'stop'}]}])
@pytest.mark.anyio
async def test_broken_structure_retries_then_reports_empty_reply(monkeypatch, payload):
    """choices 缺失、message 缺失等结构问题同样重试，耗尽后报"没有返回有效内容"。"""
    fake = _use_client(monkeypatch, [payload])

    with pytest.raises(llm.ModelOutputError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == EMPTY_ERROR
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_fenced_json_succeeds_on_first_call(monkeypatch):
    """模型把 JSON 包在 markdown 代码围栏里：容错解析，不浪费重试次数。"""
    fenced = '\n```json\n' + _json_reply() + '\n```\n'
    fake = _use_client(monkeypatch, [_payload(fenced)])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 1


@pytest.mark.anyio
async def test_prose_around_json_succeeds_on_first_call(monkeypatch):
    """JSON 前后带说明文字：取第一个 { 到最后一个 } 的子串救回。"""
    fake = _use_client(monkeypatch, [_payload('这是结果：' + _json_reply() + '，请查收。')])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 1


def test_loads_reply_tolerates_fence_prose_and_rejects_garbage():
    body = _json_reply()
    assert llm._loads_reply(body) == REPLY
    assert llm._loads_reply('```json\n' + body + '\n```') == REPLY
    assert llm._loads_reply('结果如下：' + body + ' 希望有帮助') == REPLY
    with pytest.raises(ValueError):
        llm._loads_reply(TRUNCATED)


@pytest.mark.anyio
async def test_finish_reason_length_retries_then_reports_length_limit(monkeypatch):
    """finish_reason=length 纳入重试，耗尽后保持前端依赖的超长文案。"""
    fake = _use_client(monkeypatch, [_payload(_json_reply(), finish_reason='length')])

    with pytest.raises(llm.ModelOutputError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == LENGTH_ERROR
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_finish_reason_length_then_complete_succeeds(monkeypatch):
    """长度截断只是一次抖动：第二次完整就正常返回。"""
    fake = _use_client(monkeypatch, [
        _payload(_json_reply(), finish_reason='length'),
        _payload(_json_reply()),
    ])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_retryable_http_status_is_retried(monkeypatch):
    """回归：5xx 仍然重试。"""
    fake = _use_client(monkeypatch, [_Response({}, status_code=500), _payload(_json_reply())])

    result = await llm.model_json(_messages())

    assert result == REPLY
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_auth_error_is_not_retried(monkeypatch):
    """回归：401 是配置错误，不重试，直接给认证文案。"""
    fake = _use_client(monkeypatch, [_Response({}, status_code=401)])

    with pytest.raises(llm.ServiceError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == AUTH_ERROR
    assert not isinstance(excinfo.value, llm.ModelOutputError)
    assert len(fake.calls) == 1


@pytest.mark.anyio
async def test_non_object_json_reports_format_error(monkeypatch):
    """回归：正文解析成功但不是 JSON 对象，仍报"格式无效"。"""
    fake = _use_client(monkeypatch, [_payload('[]')])

    with pytest.raises(llm.ModelOutputError) as excinfo:
        await llm.model_json(_messages())

    assert str(excinfo.value) == FORMAT_ERROR
    assert len(fake.calls) == 2


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.mark.anyio
async def test_failure_log_records_attempt_and_length_not_content(monkeypatch):
    """失败日志只记异常类型/次数/正文长度，不落模型原文。"""
    handler = _ListHandler()
    llm.log.addHandler(handler)
    try:
        _use_client(monkeypatch, [_payload(TRUNCATED)])
        with pytest.raises(llm.ModelOutputError):
            await llm.model_json(_messages())
    finally:
        llm.log.removeHandler(handler)

    joined = '\n'.join(handler.messages)
    assert 'Model reply not valid JSON' in joined
    assert 'attempt=1' in joined and f'chars={len(TRUNCATED)}' in joined
    assert TRUNCATED not in joined and '好的' not in joined


@pytest.mark.anyio
async def test_stream_retries_before_any_emit(monkeypatch):
    """流式：还没推字时传输错误可以重放整轮。"""
    fake = _use_stream_client(monkeypatch, [[_connect_error()], _sse('{"reply":"你', '好"}')])
    emitted = []

    result = await llm.model_json([], on_reply=emitted.append)

    assert result == {'reply': '你好'}
    assert len(fake.calls) == 2
    assert ''.join(emitted) == '你好'
    assert fake.calls[0][1]['json']['stream'] is True


@pytest.mark.anyio
async def test_stream_incomplete_without_emit_retries(monkeypatch):
    """流式：没收到 [DONE]/finish_reason 且尚未推字，本轮视为不可用并重试。"""
    incomplete = ['data: ' + json.dumps({'choices': [{'delta': {'content': '{"updates":'}}]})]
    fake = _use_stream_client(monkeypatch, [incomplete, _sse('{"reply":"你', '好"}')])
    emitted = []

    result = await llm.model_json([], on_reply=emitted.append)

    assert result == {'reply': '你好'}
    assert len(fake.calls) == 2


@pytest.mark.anyio
async def test_stream_never_replays_after_emit(monkeypatch):
    """流式：已经推过字后出错绝不重放，直接交给上层报网络错误。"""
    script = _sse('{"reply":"你', done=False) + [_connect_error()]
    fake = _use_stream_client(monkeypatch, [script])
    emitted = []

    with pytest.raises(llm.ServiceError) as excinfo:
        await llm.model_json([], on_reply=emitted.append)

    assert str(excinfo.value) == NETWORK_ERROR
    assert len(fake.calls) == 1
    assert emitted == ['你']
