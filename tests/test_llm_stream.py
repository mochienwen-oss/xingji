import json

import pytest

from backend.services import llm, planning


def test_reply_stream_waits_for_complete_escapes_and_ignores_nested_reply():
    """生产侧的增量解码器：转义/代理项未到齐时不能提前吐出半个字符。"""
    def read(*chunks):
        stream, raw, text = llm._ReplyStream(), '', ''
        for chunk in chunks:
            raw += chunk
            text = stream.feed(raw)
        return text

    assert read('{"other":{"reply":"wrong"},"reply":"你\\u', '597d', '"}') == '你好'
    assert read('{"reply":"\\ud83d', '\\ude03"}') == '😃'
    assert read('{"reply":"a\\', 'n"}') == 'a\n'


@pytest.mark.anyio
async def test_model_stream_emits_real_reply_pieces(monkeypatch):
    chunks = ['{"reply":"你', '\\u597d', '","updates":{}}']

    class Response:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            for chunk in chunks:
                yield 'data: ' + json.dumps({'choices':[{'delta':{'content':chunk}}]})
            yield 'data: [DONE]'

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            assert kwargs['json']['stream'] is True
            return Response()

    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1')
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_MODEL', 'test-model')
    monkeypatch.setattr(llm, 'shared_client', Client)
    emitted = []
    result = await llm.model_json([], on_reply=emitted.append)
    assert emitted == ['你', '好']
    assert result['reply'] == ''.join(emitted)


def test_planning_chat_stream_emits_before_final_result(client, monkeypatch):
    c, _ = client

    async def chat(messages, current, on_reply=None):
        on_reply('你')
        on_reply('好')
        return {'reply':'你好','updates':{},'place_keywords':[]}

    monkeypatch.setattr(planning, 'planning_chat', chat)
    response = c.post('/api/planning/chat/stream', json={'messages':[{'role':'user','content':'你好'}], 'current':{}})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['kind'] for event in events] == ['delta', 'delta', 'done']
    assert ''.join(event['text'] for event in events[:-1]) == events[-1]['reply']
