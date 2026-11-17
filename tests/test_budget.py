import json
import pytest
from tests.conftest import login
from backend.db import Trip
import backend.db as app_db
from backend.services import amap, budget
from backend.services.errors import ServiceError


def test_places_are_reloaded_without_persisting_new_snapshots(client, monkeypatch):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    with app_db.Session() as db:
        stored = json.loads(db.get(Trip, trip['id']).data)
        assert stored['days'][0]['stops'][0]['place'] == {'id': places[0]['id']}
    async def updated(ids):
        return {places[0]['id']: {**places[0], 'name': '实时更新', 'photos': [{'url':'https://example.com/a.jpg','title':''}]}}
    monkeypatch.setattr(amap, 'find_places', updated)
    loaded = c.get(f"/api/trips/{trip['id']}").json()
    assert loaded['days'][0]['stops'][0]['place']['name'] == '实时更新'
    assert loaded['days'][0]['stops'][0]['place']['photos']
    async def fail(ids): raise ServiceError('unavailable')
    monkeypatch.setattr(amap, 'find_places', fail)
    unavailable = c.get(f"/api/trips/{trip['id']}").json()
    assert unavailable['place_notice'] and unavailable['days'][0]['stops'][0]['place']['id'] == places[0]['id']
    assert unavailable['days'][0]['stops'][0]['place']['verification']['status'] == 'unavailable'
    assert c.put(f"/api/trips/{trip['id']}/days", json={'days': loaded['days']}).status_code == 503
    with app_db.Session() as db:
        assert json.loads(db.get(Trip, trip['id']).data) == stored


def test_budget_expenses_and_share_privacy(client):
    c, places = client
    login(c)
    trip = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    base = f"/api/trips/{trip['id']}"
    assert c.put(base+'/budget', json={'amount_cents': 10000}).json()['amount_cents'] == 10000
    record = {'amount_cents': 12550, 'category': '餐饮', 'expense_date': '2026-10-03', 'place_id': places[0]['id'], 'note': 'private expense'}
    expense = c.post(base+'/expenses', json=record).json()
    assert c.get(base+'/budget').json()['expenses'][0]['amount_cents'] == 12550
    record['amount_cents'] = 9999
    assert c.put(base+f"/expenses/{expense['id']}", json=record).json()['amount_cents'] == 9999
    assert c.post(base+'/expenses', json={**record, 'amount_cents': -1}).status_code == 422
    token = c.post(base+'/share').json()['token']
    assert 'private expense' not in c.post('/api/shares/view', json={'token': token}).text
    login(c, 'bob', 'password2')
    assert c.get(base+'/budget').status_code == 404
    assert c.delete(base+f"/expenses/{expense['id']}").status_code == 404
    login(c)
    assert c.delete(base+f"/expenses/{expense['id']}").status_code == 200
    assert c.get(base+'/budget').json()['expenses'] == []


@pytest.mark.anyio
async def test_estimate_rejects_invalid_ranges(monkeypatch):
    async def model(messages, max_tokens):
        return {'items': [{'category': '餐饮', 'low': 500, 'high': 100, 'assumption': '两人'}]}
    monkeypatch.setattr(budget, 'model_json', model)
    with pytest.raises(ServiceError):
        await budget.estimate({'city':'桂林'}, [{'stops':[]}])
