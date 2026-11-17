import asyncio
from copy import deepcopy

import pytest

from backend.services import amap
from backend.services.errors import ServiceError
from tests.conftest import login


@pytest.mark.anyio
async def test_find_places_batches_concurrently_and_returns_all_keys(monkeypatch):
    active = 0
    peak = 0
    batches = []

    async def fake(path, params):
        nonlocal active, peak
        ids = params['id'].split('|')
        batches.append(ids)
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02)
            return {'pois': [{'id': pid, 'name': f'地点{pid}', 'location': '110.1,25.2'} for pid in ids]}
        finally:
            active -= 1

    monkeypatch.setattr(amap, 'amap', fake)
    ids = [str(i) for i in range(25)]
    result = await amap.find_places(ids)
    assert set(result) == set(ids)
    assert [len(batch) for batch in batches] == [10, 10, 5]
    assert 1 < peak <= 4
    assert amap.AMAP_BATCH_CONCURRENCY == 4
    assert amap.AMAP_TASK_TIMEOUT_SECONDS == 20.0


@pytest.mark.anyio
async def test_find_places_drops_only_the_timed_out_batch(monkeypatch):
    async def fake(path, params):
        ids = params['id'].split('|')
        if '15' in ids:
            await asyncio.sleep(5)
        return {'pois': [{'id': pid, 'name': f'地点{pid}', 'location': '110.1,25.2'} for pid in ids]}

    monkeypatch.setattr(amap, 'amap', fake)
    monkeypatch.setattr(amap, 'AMAP_TASK_TIMEOUT_SECONDS', 0.01)
    result = await amap.find_places([str(i) for i in range(25)])
    assert '15' not in result
    assert len(result) == 15


@pytest.mark.anyio
async def test_find_places_drops_only_the_failing_batch(monkeypatch):
    async def fake(path, params):
        ids = params['id'].split('|')
        if '5' in ids:
            raise ServiceError('模拟的批次失败')
        return {'pois': [{'id': pid, 'name': f'地点{pid}', 'location': '110.1,25.2'} for pid in ids]}

    monkeypatch.setattr(amap, 'amap', fake)
    result = await amap.find_places([str(i) for i in range(25)])
    assert '5' not in result
    assert len(result) == 15


@pytest.mark.anyio
async def test_update_routes_keeps_order_and_degrades_timed_out_segment(monkeypatch):
    stops = [{'place': {'id': pid, 'location': f'110.{pid},25.{pid}'}} for pid in ('1', '2', '3')]
    days = [{'stops': stops}]

    async def fake(a, b, mode, city):
        if a['id'] == '1':
            await asyncio.sleep(5)
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 300,
                'distance': 800, 'polyline': [], 'source_time': '2026-01-01T00:00:00Z'}

    monkeypatch.setattr(amap, 'route_between', fake)
    monkeypatch.setattr(amap, 'AMAP_TASK_TIMEOUT_SECONDS', 0.01)
    await amap.update_routes(days, 'walking', '桂林')
    routes = days[0]['routes']
    assert [(route['origin'], route['destination']) for route in routes] == [('1', '2'), ('2', '3')]
    assert routes[0]['duration'] is None
    assert routes[0]['distance'] is None
    assert routes[0]['polyline'] == []
    assert routes[1]['duration'] == 300


@pytest.mark.anyio
async def test_update_routes_reuses_old_segment_without_fetching(monkeypatch):
    calls = []

    async def fake(a, b, mode, city):
        calls.append((a['id'], b['id']))
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 300,
                'distance': 800, 'polyline': [], 'source_time': '2026-01-01T00:00:00Z'}

    monkeypatch.setattr(amap, 'route_between', fake)
    stops = [{'place': {'id': pid, 'location': f'110.{pid},25.{pid}'}} for pid in ('1', '2', '3')]
    old = [{'routes': [{'origin': '1', 'destination': '2', 'mode': 'walking',
                        'duration': 600, 'distance': 900, 'polyline': []}]}]
    days = [{'stops': stops}]
    await amap.update_routes(days, 'walking', '桂林', old)
    assert calls == [('2', '3')]
    assert [route['duration'] for route in days[0]['routes']] == [600, 300]


def test_save_days_still_succeeds_when_one_segment_times_out(client, monkeypatch):
    c, places = client
    assert login(c).status_code == 200
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    days = deepcopy(created['days'])
    for place in places[1:3]:
        days[0]['stops'].append({'place': place, 'duration': 60, 'reason': ''})

    async def fake(a, b, mode, city):
        if a['id'] == days[0]['stops'][0]['place']['id']:
            await asyncio.sleep(5)
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 300,
                'distance': 800, 'polyline': [], 'source_time': '2026-01-01T00:00:00Z'}

    monkeypatch.setattr(amap, 'route_between', fake)
    monkeypatch.setattr(amap, 'AMAP_TASK_TIMEOUT_SECONDS', 0.01)
    response = c.put(f"/api/trips/{created['id']}/days", json={'days': days})
    assert response.status_code == 200
    routes = response.json()['days'][0]['routes']
    assert [route['duration'] for route in routes] == [None, 300]
