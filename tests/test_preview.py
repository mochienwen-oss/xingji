import asyncio
import json

from backend.api import trips as trips_api
from backend.services import agent, amap, planning
from tests.conftest import login


def test_guest_preview_preserves_user_request_and_only_saves_on_request(client, monkeypatch):
    c, _ = client
    received = {}

    async def generate(request, candidates, **kwargs):
        received.update(kwargs)
        return [{'stops':[{'place':candidates[0], 'duration':90, 'reason':''}]}]

    monkeypatch.setattr(planning, 'generate_plan', generate)
    response = c.post('/api/planning/preview', json={'city':'桂林','days':1,'conversation':[{'role':'user','content':'带老人，少走路'}]})
    assert response.status_code == 200
    preview = response.json()
    assert preview['id'] == 0 and received['instruction'] == '带老人，少走路'
    payload = {key:preview[key] for key in ('request','days','backlog','conversation')}
    assert c.post('/api/trips/from-preview', json=payload).status_code == 401
    assert login(c).status_code == 200
    assert c.get('/api/trips').json() == []
    saved = c.post('/api/trips/from-preview', json=payload)
    assert saved.status_code == 201
    assert saved.json()['id'] != 0
    assert len(c.get('/api/trips').json()) == 1


def test_preview_assistant_stream_does_not_persist(client, monkeypatch):
    c, _ = client
    preview = c.post('/api/planning/preview', json={'city':'桂林','days':1}).json()

    async def run(state):
        assert state['trip_id'] == 0
        yield {'events':[{'kind':'delta','text':'已调整'}, {'kind':'done','days':state['days'], 'backlog':[], 'reply':'已调整','changed':True}]}

    monkeypatch.setattr(agent, 'run_stream', run)
    response = c.post('/api/planning/preview/assistant/stream', json={
        'request':preview['request'],'days':preview['days'],'backlog':[], 'message':'少走路','history':[]})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['kind'] for event in events] == ['delta','done']
    assert login(c).status_code == 200
    assert c.get('/api/trips').json() == []


def test_preview_assistant_stream_sends_heartbeat_while_model_thinks(client, monkeypatch):
    c, _ = client
    preview = c.post('/api/planning/preview', json={'city':'桂林','days':1}).json()

    async def slow_run(state):
        await asyncio.sleep(0.12)
        yield {'events':[{'kind':'delta','text':'已调整'}, {'kind':'done','days':state['days'], 'backlog':[], 'reply':'已调整','changed':True}]}

    monkeypatch.setattr(agent, 'run_stream', slow_run)
    monkeypatch.setattr(trips_api, 'SSE_HEARTBEAT_SECONDS', 0.05)
    response = c.post('/api/planning/preview/assistant/stream', json={
        'request':preview['request'],'days':preview['days'],'backlog':[], 'message':'少走路','history':[]})
    lines = response.text.splitlines()
    assert response.status_code == 200
    assert lines.count(': ping') >= 1
    events = [json.loads(line[6:]) for line in lines if line.startswith('data: ')]
    assert [event['kind'] for event in events] == ['delta','done']


def test_preview_save_rejects_unknown_or_duplicate_places(client):
    c, _ = client
    preview = c.post('/api/planning/preview', json={'city':'桂林','days':1}).json()
    assert login(c).status_code == 200
    body = {key:preview[key] for key in ('request','days','backlog','conversation')}
    body['days'][0]['stops'][0]['place']['id'] = 'unknown'
    assert c.post('/api/trips/from-preview', json=body).status_code == 422
    body['backlog'] = [body['days'][0]['stops'][0]]
    assert c.post('/api/trips/from-preview', json=body).status_code == 422

def test_preview_rejects_places_from_another_city(client, monkeypatch):
    c, _ = client

    async def search(city, keyword):
        return [dict(id='B1', name='故宫', address='', location='116.397,39.917',
                     opentime='', cost='', source_time='2026-01-01T00:00:00Z', city='北京市')]

    monkeypatch.setattr(amap, 'search_places', search)
    response = c.post('/api/planning/preview', json={'city': 'Suzhou', 'days': 1})
    assert response.status_code == 422
    assert '中文城市名' in response.json()['detail']
