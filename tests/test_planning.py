import json
import pytest
from backend.services import llm, planning
from backend.services.errors import ServiceError

@pytest.mark.anyio
async def test_model_rejects_unknown_poi(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':json.dumps({'days':[{'stops':[{'id':'invented','duration':60}]}]})}}]}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Response()
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test')
    monkeypatch.delenv('LLM_BASE_URL', raising=False)
    monkeypatch.setattr(llm, 'shared_client', Client)
    with pytest.raises(ServiceError):
        await planning.generate_plan({'days':1}, [{'id':'real'}])

@pytest.mark.anyio
async def test_custom_model_gateway(monkeypatch):
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'choices': [{'message': {'content': json.dumps({'days': [{'stops': [{'id': 'real', 'duration': 60}]}]})}}]}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1/')
    monkeypatch.setenv('LLM_API_KEY', 'gateway-test-key')
    monkeypatch.setenv('LLM_MODEL', 'enterprise-model')
    monkeypatch.setattr(llm, 'shared_client', Client)
    result = await planning.generate_plan({'days': 1}, [{'id': 'real'}])
    assert result[0]['stops'][0]['place']['id'] == 'real'
    assert calls[0][0] == 'https://example.test/v1/chat/completions'
    assert calls[0][1]['json']['model'] == 'enterprise-model'
    assert calls[0][1]['headers']['Authorization'] == 'Bearer gateway-test-key'

@pytest.mark.anyio
async def test_generation_retries_invalid_model_output_once(monkeypatch):
    calls = []
    async def model(messages, max_tokens=4000):
        calls.append(messages[:])
        if len(calls) == 1:
            raise llm.ModelOutputError('模型返回内容不完整或格式无效，请重试。')
        return {'days':[{'stops':[{'id':'real','duration':60}]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    result = await planning.generate_plan({'days':1}, [{'id':'real'}])
    assert len(calls) == 2
    assert '完整的 JSON' in calls[1][-1]['content']
    assert result[0]['stops'][0]['place']['id'] == 'real'

@pytest.mark.anyio
async def test_generation_does_not_retry_service_failures(monkeypatch):
    calls = []
    async def model(messages, max_tokens=4000):
        calls.append(1)
        raise ServiceError('模型服务认证失败')
    monkeypatch.setattr(planning, 'model_json', model)
    with pytest.raises(ServiceError, match='认证失败'):
        await planning.generate_plan({'days':1}, [{'id':'real'}])
    assert len(calls) == 1

@pytest.mark.anyio
async def test_truncated_nonstream_response_has_specific_error(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'finish_reason':'length','message':{'content':'{"days":['}}]}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Response()
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1')
    monkeypatch.setenv('LLM_API_KEY', 'test')
    monkeypatch.setenv('LLM_MODEL', 'test')
    monkeypatch.setattr(llm, 'shared_client', Client)
    with pytest.raises(llm.ModelOutputError, match='长度限制'):
        await llm.model_json([])

@pytest.mark.anyio
async def test_custom_gateway_does_not_reuse_deepseek_credentials(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'old-key')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.setenv('LLM_MODEL', 'enterprise-model')
    with pytest.raises(ServiceError, match='LLM_API_KEY'):
        await planning.generate_plan({'days': 1}, [{'id': 'real'}])

@pytest.mark.anyio
async def test_local_edit_preserves_unrelated_stops(monkeypatch):
    async def model(messages, max_tokens=4000):
        return {'reply':'已调整','actions':[{'type':'duration','place_id':'a','duration':60}]}
    monkeypatch.setattr(planning, 'model_json', model)
    days=[{'stops':[{'place':{'id':'a'},'duration':90,'reason':''}, {'place':{'id':'b'},'duration':120,'reason':'保留'}], 'routes':[]}]
    result=await planning.suggest_edits({'days':1}, [{'id':'a'},{'id':'b'}], '缩短第一站', days)
    assert result['days'][0]['stops'][0]['duration']==60
    assert result['days'][0]['stops'][1] == days[0]['stops'][1]
    assert days[0]['stops'][0]['duration']==90

@pytest.mark.anyio
async def test_local_edit_rejects_unknown_place(monkeypatch):
    async def model(messages, max_tokens=4000):
        return {'reply':'已添加','actions':[{'type':'add','place_id':'invented','day':1,'position':2}]}
    monkeypatch.setattr(planning, 'model_json', model)
    days=[{'stops':[{'place':{'id':'a'},'duration':90,'reason':''}], 'routes':[]}]
    with pytest.raises(ServiceError):
        await planning.suggest_edits({'days':1}, [{'id':'a'}], '添加景点', days)


@pytest.mark.anyio
async def test_ai_can_move_between_backlog_and_itinerary_without_duplicates(monkeypatch):
    async def model(messages, max_tokens=4000):
        return {'reply':'调整建议','actions':[
            {'type':'unplan','place_id':'a'},
            {'type':'plan','place_id':'b','day':1,'position':1}]}
    monkeypatch.setattr(planning, 'model_json', model)
    a={'place':{'id':'a'},'duration':90,'reason':'保留'}
    b={'place':{'id':'b'},'duration':60,'reason':'','activity':'展览','fixed_time':'10:30'}
    days=[{'stops':[a], 'routes':[], 'start_time':'09:00'}]
    result=await planning.suggest_edits({'days':1}, [{'id':'a'},{'id':'b'}], '交换待规划地点', days, [b])
    assert result['changed']
    assert result['days'][0]['stops'] == [b] and result['backlog'] == [a]
    assert result['days'][0]['start_time'] == '09:00'
    assert days[0]['stops'] == [a]


@pytest.mark.anyio
async def test_ai_add_reuses_existing_backlog_stop(monkeypatch):
    async def model(messages, max_tokens=4000):
        return {'reply':'调整建议','actions':[{'type':'add','place_id':'b','day':1,'position':2}]}
    monkeypatch.setattr(planning, 'model_json', model)
    days=[{'stops':[{'place':{'id':'a'},'duration':90,'reason':''}], 'routes':[]}]
    backlog=[{'place':{'id':'b'},'duration':60,'reason':'','activity':'展览'}]
    result=await planning.suggest_edits({'days':1}, [{'id':'a'},{'id':'b'}], '加上展览', days, backlog)
    assert result['days'][0]['stops'][1] == backlog[0]
    assert result['backlog'] == []


@pytest.mark.anyio
async def test_generation_retries_overlapping_scenic_subplaces(monkeypatch):
    calls=[]
    async def model(messages, max_tokens=4000):
        calls.append(messages[:])
        ids=['parent','child'] if len(calls)==1 else ['parent','other']
        return {'days':[{'stops':[{'id':pid,'duration':60} for pid in ids]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    places=[{'id':'parent','name':'测试景区','address':'景区地址'},
            {'id':'child','name':'观景台','address':'测试景区内'},
            {'id':'other','name':'老街','address':'老街地址'}]
    result=await planning.generate_plan({'days':1}, places)
    assert len(calls)==2 and [s['place']['id'] for s in result[0]['stops']] == ['parent','other']


@pytest.mark.anyio
async def test_generation_keeps_explicit_scenic_subplace(monkeypatch):
    async def model(messages, max_tokens=4000):
        return {'days':[{'stops':[{'id':'parent','duration':60},{'id':'child','duration':30}]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    places=[{'id':'parent','name':'测试景区','address':'景区地址'},
            {'id':'child','name':'观景台','address':'测试景区内'}]
    result=await planning.generate_plan({'days':1}, places, explicit_place_ids=['child'])
    assert [s['place']['id'] for s in result[0]['stops']] == ['parent','child']

@pytest.mark.anyio
async def test_generate_plan_uses_plan_compose_and_injects_memory(monkeypatch):
    seen = []
    async def model(messages, max_tokens=4000):
        seen.append(messages[:])
        return {'days':[{'stops':[{'id':'real','duration':60}]}]}
    monkeypatch.setattr(planning, 'model_json', model)
    await planning.generate_plan({'days':1}, [{'id':'real'}], memories=[{'key':'pace_preference','value':'不喜欢赶'}])
    assert '每日行程编排' in seen[0][1]['content']
    dynamic = seen[0][2]['content']
    assert '长期记忆' in dynamic and '不喜欢赶' in dynamic
    assert '用户修改要求' not in seen[0][-1]['content']


@pytest.mark.anyio
async def test_suggest_edits_selects_trip_prompt_and_memory(monkeypatch):
    seen = []
    async def model(messages, max_tokens=4000):
        seen.append(messages[:])
        return {'reply':'不动','actions':[]}
    monkeypatch.setattr(planning, 'model_json', model)
    days = [{'stops':[{'place':{'id':'a'},'duration':90,'reason':''}], 'routes':[]}]
    await planning.suggest_edits({'days':1}, [{'id':'a'}], '保持原样', days,
                                 mode='trip', trip_id=12, version=3,
                                 memories=[{'key':'pace_preference','value':'慢慢走'}])
    assert '已保存行程修改' in seen[0][1]['content']
    dynamic = seen[0][2]['content']
    assert '行程ID' in dynamic and '12' in dynamic and '慢慢走' in dynamic


def test_prompt_dynamic_text_serializes_datetime():
    from datetime import datetime, timezone
    from backend.services.harness.prompts import registry
    messages = registry.build('plan_compose', dynamic={'expires_at': datetime(2026,1,1,tzinfo=timezone.utc)})
    assert '2026-01-01' in messages[2]['content']


def _fake_registry(monkeypatch, messages):
    """固定 registry.build 的输出，把断言聚焦在“兜底契约插在哪”。"""
    def build(name, dynamic=None, history=None, **kwargs):
        return [dict(message) for message in messages]
    monkeypatch.setattr(planning.registry, 'build', build)


def test_scenario_fallback_is_inserted_without_overwriting_dynamic_json(monkeypatch):
    """0.3.0：部署漏场景文件时，内联兜底契约必须插在动态 JSON 之前，不能覆盖它。

    动态 JSON 携带需求、候选地点与当前行程；被覆盖会直接改变模型契约，影响所有规划请求。
    """
    dynamic = {'需求': {'city': '杭州'}, '候选地点': [{'id': 'p1'}]}
    _fake_registry(monkeypatch, [
        {'role': 'system', 'content': '全局规则'},
        {'role': 'system', 'content': json.dumps(dynamic, ensure_ascii=False)},
    ])
    monkeypatch.setattr(planning, 'read_scenario', lambda name: None)

    messages = planning._scenario_messages('plan_compose', dynamic, fallback='兜底契约')
    assert [message['role'] for message in messages] == ['system', 'system', 'system']
    assert messages[0]['content'] == '全局规则'
    assert messages[1]['content'] == '兜底契约'
    assert json.loads(messages[2]['content']) == dynamic, '动态 JSON 不能被兜底消息覆盖'


def test_scenario_messages_keep_contract_when_scenario_file_exists(monkeypatch):
    """正常路径：场景文件存在时不插入兜底，保持静态规则 + 场景契约 + 动态 JSON 三条。"""
    _fake_registry(monkeypatch, [
        {'role': 'system', 'content': '全局规则'},
        {'role': 'system', 'content': '场景契约'},
        {'role': 'system', 'content': '动态 JSON'},
    ])
    monkeypatch.setattr(planning, 'read_scenario', lambda name: '场景内容')
    monkeypatch.setattr(planning.registry, 'fingerprints',
                        lambda name, dynamic: {'static': 's', 'scenario': 'c', 'dynamic': 'd'})

    messages = planning._scenario_messages('plan_compose', {}, fallback='兜底契约')
    assert [message['content'] for message in messages] == ['全局规则', '场景契约', '动态 JSON']

