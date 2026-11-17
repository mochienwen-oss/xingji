import asyncio
import json
import time

import pytest

from backend import db as app_db
from backend.api import planning as planning_api
from backend.api import trips as trips_api
from backend.db import Trip
from backend.services import agent
from backend.services import planning as planning_service
from backend.services.errors import ServiceError
from tests.conftest import login


class SavingAgent:
    def __init__(self, reply='建议调整'):
        self.reply = reply

    async def run_stream(self, state):
        yield {'events': [{'kind': 'delta', 'text': '好的'}]}
        yield {'suggestion': {'days': state['days'], 'backlog': [], 'reply': self.reply, 'changed': True}}
        yield {'events': [{'kind': 'done', 'days': state['days']}]}


class FailingAgent:
    async def run_stream(self, state):
        yield {'events': [{'kind': 'delta', 'text': '稍等'}]}
        raise ServiceError('模型不可用')


def _items(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _create_trip(c):
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    request_session = app_db.Session()
    row = request_session.get(Trip, created['id'])
    data = json.loads(row.data)
    request_session.close()
    return created, row, data


def _state(data, message='调整节奏'):
    return {'message': message, 'days': data['days'], 'backlog': data.get('backlog', []),
            'city': '桂林', 'transport': data['request']['transport'], 'request': data['request']}


@pytest.mark.anyio
async def test_drive_agent_saves_even_when_queue_is_never_consumed(client):
    c, _ = client
    assert login(c).status_code == 200
    created, row, data = _create_trip(c)
    version = created['version']
    queue = asyncio.Queue()
    state = _state(data)

    await trips_api._drive_agent(SavingAgent(), state, data, row, version, queue)

    items = _items(queue)
    assert [item['kind'] for item in items if item is not None] == ['delta', 'done', 'saved']
    assert items[-1] is None
    assert state['completed'] is True
    with app_db.Session() as session:
        saved = session.get(Trip, created['id'])
        stored = json.loads(saved.data)
    assert saved.version == version + 1
    assert stored['conversation'][-2:] == [
        {'role': 'user', 'content': '调整节奏'},
        {'role': 'assistant', 'content': '建议调整'},
    ]


@pytest.mark.anyio
async def test_drive_agent_does_not_save_when_agent_fails(client, monkeypatch):
    c, _ = client
    assert login(c).status_code == 200
    created, row, data = _create_trip(c)
    version = created['version']
    before = json.loads(row.data).get('conversation', [])
    saved_calls = []
    real_save = trips_api._save_data

    def spy(session, target, payload, current_version):
        saved_calls.append(current_version)
        return real_save(session, target, payload, current_version)

    monkeypatch.setattr(trips_api, '_save_data', spy)
    queue = asyncio.Queue()
    state = _state(data)

    await trips_api._drive_agent(FailingAgent(), state, data, row, version, queue)

    items = _items(queue)
    assert saved_calls == []
    assert [item['kind'] for item in items if item is not None] == ['delta', 'error']
    assert items[-2]['message'] == '模型不可用'
    assert items[-1] is None
    with app_db.Session() as session:
        unchanged = session.get(Trip, created['id'])
        stored = json.loads(unchanged.data)
    assert unchanged.version == version
    assert stored.get('conversation', []) == before


def test_assistant_stream_saves_after_done_even_if_client_disconnects(client, monkeypatch):
    c, _ = client
    assert login(c).status_code == 200
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    version = created['version']

    async def fake_stream(state):
        yield {'events': [{'kind': 'delta', 'text': '好的'}]}
        yield {'suggestion': {'days': state['days'], 'backlog': [], 'reply': '建议调整', 'changed': True}}
        yield {'events': [{'kind': 'done', 'days': state['days']}]}

    monkeypatch.setattr(agent, 'run_stream', fake_stream)
    saw_done = False
    with c.stream('POST', f"/api/trips/{created['id']}/assistant/stream",
                  json={'message': '调整', 'history': [], 'version': version}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith('data: '):
                continue
            if json.loads(line[6:]).get('kind') == 'done':
                saw_done = True
                break
    assert saw_done

    deadline = time.monotonic() + 3
    saved = None
    while time.monotonic() < deadline:
        with app_db.Session() as session:
            saved = session.get(Trip, created['id'])
            saved_version = saved.version or 0
            saved_data = json.loads(saved.data)
        if saved_version == version + 1:
            break
        time.sleep(0.02)
    else:
        pytest.fail('done 后断开连接仍未保存对话')
    assert saved_data['conversation'][-1] == {'role': 'assistant', 'content': '建议调整'}


def test_planning_stream_emits_ping_heartbeat_and_done(client, monkeypatch):
    c, _ = client

    async def slow_chat(messages, current, on_reply=None):
        await asyncio.sleep(0.2)
        if on_reply:
            on_reply('好')
        return {'reply': '好', 'updates': {}, 'place_keywords': []}

    monkeypatch.setattr(planning_service, 'planning_chat', slow_chat)
    monkeypatch.setattr(planning_api, 'PLANNING_SSE_HEARTBEAT_SECONDS', 0.01)
    response = c.post('/api/planning/chat/stream',
                      json={'messages': [{'role': 'user', 'content': '你好'}], 'current': {}})
    assert response.status_code == 200
    lines = response.text.splitlines()
    assert ': ping' in lines
    events = [json.loads(line[6:]) for line in lines if line.startswith('data: ')]
    assert events[-1]['kind'] == 'done'
    assert ''.join(event['text'] for event in events if event['kind'] == 'delta') == events[-1]['reply']
