import json
from copy import deepcopy

import pytest

from backend.services import agent, planning
from backend.services.agent import graph, tools
from backend.services.errors import ServiceError
from tests.conftest import login


@pytest.mark.anyio
async def test_graph_emits_each_tool_and_route_event_with_time(monkeypatch):
    places = [
        {'id': str(i), 'name': f'景点{i}', 'location': f'110.{i},25.{i}'}
        for i in range(1, 4)
    ]
    seen = {}

    def current_time():
        return {'now': '2026-11-05 12:30', 'time': '12:30', 'weekday': '星期四', 'timezone': 'Asia/Shanghai'}

    async def keywords(context, days, backlog):
        seen['keywords'] = context
        return ['景点2', '景点3']

    async def search(city, keyword):
        return [places[1] if keyword == '景点2' else places[2]]

    async def suggest(request, candidates, context, days, backlog, on_reply=None, **kwargs):
        seen['context'] = context
        return {'changed': True, 'reply': '已调整', 'backlog': [], 'days': [
            {'stops': [{'place': place, 'duration': 90, 'reason': ''} for place in places]}
        ]}

    async def routes(days, mode, city, old):
        # 路由节点现在整批调用一次 update_routes，由它返回每天的完整路段列表；
        # 这里按相邻站点生成每段，验证 route_seg 事件仍逐段下发。
        stops = days[0]['stops']
        days[0]['routes'] = [
            {'origin': first['place']['id'], 'destination': second['place']['id'],
             'duration': 300, 'distance': 800, 'polyline': [[[110, 25], [111, 26]]]}
            for first, second in zip(stops, stops[1:])
        ]

    monkeypatch.setattr(tools, 'get_current_time', current_time)
    monkeypatch.setattr(planning, 'adjustment_keywords', keywords)
    monkeypatch.setattr(tools, 'search_places', search)
    monkeypatch.setattr(tools, 'suggest_edits', suggest)
    monkeypatch.setattr(tools, 'update_routes', routes)
    state = {'message': '明天怎么走', 'context': '用户最新要求：明天怎么走',
             'request': {}, 'days': [{'stops': [{'place': places[0], 'duration': 90}]}],
             'backlog': [], 'candidates': {'1': places[0]}, 'city': '桂林', 'transport': 'walking'}
    outputs = [chunk async for chunk in graph.run_stream(state)]
    events = [item for chunk in outputs for item in chunk.get('events', [])]
    assert [item['kind'] for item in events].count('tool_start') == 2
    assert [item['kind'] for item in events].count('pin') == 2
    assert [item['kind'] for item in events].count('route_seg') == 2
    assert events[-1]['kind'] == 'done'
    assert len(events[-1]['days'][0]['routes']) == 2
    assert '2026-11-05 12:30' in seen['keywords'] and '2026-11-05 12:30' in seen['context']


def test_stream_never_saves_unconfirmed_or_failed_suggestion(client, monkeypatch):
    c, _ = client
    assert login(c).status_code == 200
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    before = deepcopy(created['days'])
    modified = deepcopy(before)
    modified[0]['stops'][0]['duration'] = 120
    suggestion = {'days': modified, 'backlog': [], 'reply': '建议调整', 'changed': True}

    async def failed(state):
        yield {'suggestion': suggestion}
        raise ServiceError('路线失败')

    monkeypatch.setattr(agent, 'run_stream', failed)
    response = c.post(f"/api/trips/{created['id']}/assistant/stream",
                      json={'message': '调整', 'history': [], 'version': 0})
    assert '路线失败' in response.text and '"kind": "saved"' not in response.text
    after_failure = c.get(f"/api/trips/{created['id']}").json()
    assert after_failure['days'] == before and after_failure['version'] == 0

    async def succeeded(state):
        yield {'suggestion': suggestion}
        yield {'events': [{'kind': 'done', **suggestion}]}

    monkeypatch.setattr(agent, 'run_stream', succeeded)
    response = c.post(f"/api/trips/{created['id']}/assistant/stream",
                      json={'message': '调整', 'history': [], 'version': 0})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [item['kind'] for item in events] == ['done', 'saved']
    after_success = c.get(f"/api/trips/{created['id']}").json()
    assert after_success['days'] == before and after_success['version'] == 1
    assert after_success['conversation'][-1]['content'] == '建议调整'


def test_place_details_accepts_sixty_collected_ids(client):
    c, _ = client
    assert c.post('/api/places/details', json={'ids': [str(i) for i in range(60)]}).status_code == 200
    assert c.post('/api/places/details', json={'ids': [str(i) for i in range(61)]}).status_code == 422


def test_real_graph_stream_returns_preview_without_saving_trip(client, monkeypatch):
    c, _ = client
    assert login(c).status_code == 200
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    before = deepcopy(created['days'])

    async def keywords(context, days, backlog):
        assert '当前北京时间' in context
        return []

    async def suggest(request, candidates, context, days, backlog, on_reply=None, **kwargs):
        seen = kwargs
        assert seen['mode'] == 'trip'
        assert seen['trip_id'] == created['id']
        assert seen['version'] == 0
        assert seen['memories'] == []
        assert seen['history'] == []
        if on_reply:
            on_reply('建议')
        proposed = deepcopy(days)
        proposed[0]['stops'][0]['duration'] = 120
        return {'days': proposed, 'backlog': backlog, 'reply': '建议延长游览', 'changed': True}

    monkeypatch.setattr(planning, 'adjustment_keywords', keywords)
    monkeypatch.setattr(tools, 'suggest_edits', suggest)
    response = c.post(f"/api/trips/{created['id']}/assistant/stream",
                      json={'message': '多待一会儿', 'history': [], 'version': 0})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert response.status_code == 200
    assert any(item['kind'] == 'status' for item in events)
    assert any(item['kind'] == 'delta' and item['text'] == '建议' for item in events)
    assert any(item['kind'] == 'day_done' for item in events)
    done = next(item for item in events if item['kind'] == 'done')
    assert done['days'][0]['stops'][0]['duration'] == 120
    assert events[-1]['kind'] == 'saved'
    after = c.get(f"/api/trips/{created['id']}").json()
    assert after['days'] == before and after['version'] == 1
    assert c.post(f"/api/trips/{created['id']}/assistant/stream",
                  json={'message': '再调整', 'history': [], 'version': 0}).status_code == 409


@pytest.mark.anyio
async def test_suggest_edits_forwards_trip_scene_and_memories(monkeypatch):
    seen = {}

    async def model(messages, max_tokens=4000, on_reply=None):
        seen['messages'] = messages
        return {'reply': '不动', 'actions': []}

    monkeypatch.setattr(planning, 'model_json', model)
    request = {'city': '桂林', 'days': 1, 'transport': 'walking'}
    days = [{'stops': [{'place': {'id': '1', 'name': '象鼻山'}, 'duration': 90}]}]
    candidates = [{'id': '1', 'name': '象鼻山'}]
    result = await tools.suggest_edits(
        request, candidates, '慢一点', days, [],
        mode='trip', trip_id=7, version=3,
        memories=[{'category': 'pace', 'key': 'pace', 'value': '慢'}],
        history=[{'role': 'assistant', 'content': '好的'}],
    )
    assert result['changed'] is False
    assert '已保存行程修改' in seen['messages'][1]['content']
    dynamic = seen['messages'][2]['content']
    assert '"行程ID":7' in dynamic and '"行程版本":3' in dynamic
    assert '慢' in dynamic
    # 历史消息在动态段之后、本轮要求之前，顺序与模型看到的一致。
    assert [(m['role'], m['content']) for m in seen['messages'][3:]] == [
        ('assistant', '好的'), ('user', '用户本轮要求：慢一点')]


@pytest.mark.anyio
async def test_planning_chat_includes_current_china_time(monkeypatch):
    seen = []

    async def model(messages, max_tokens):
        seen.extend(messages)
        return {'reply': '可以', 'updates': {}, 'place_keywords': []}

    monkeypatch.setattr(planning, 'model_json', model)
    await planning.planning_chat([{'role': 'user', 'content': '明天去桂林'}], {})
    assert '当前北京时间' in seen[1]['content']
    assert '+0800' in seen[1]['content']
