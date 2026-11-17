from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, text

import backend.db as app_db
from backend.db import ensure_schema
from tests.conftest import login

def test_register_login_and_duplicate(client):
    c, _ = client
    r = c.post('/api/register', json={'username': 'carol', 'password': 'password9', 'email': 'carol@example.com', 'accept_terms': True})
    assert r.status_code == 200 and r.json()['username'] == 'carol'
    assert c.get('/api/me').json()['username'] == 'carol', '注册后应自动登录'
    assert c.post('/api/register', json={'username': 'carol', 'password': 'password9', 'email': 'carol2@example.com', 'accept_terms': True}).status_code == 409
    assert c.post('/api/register', json={'username': 'dave', 'password': 'short', 'email': 'dave@example.com', 'accept_terms': True}).status_code == 422

def test_trip_rename_soft_delete_restore(client):
    c, _ = client
    login(c)
    tid = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()['id']
    r = c.patch(f'/api/trips/{tid}', json={'title': '西湖三日'})
    assert r.status_code == 200 and r.json()['title'] == '西湖三日'
    assert c.get('/api/trips').json()[0]['title'] == '西湖三日'
    assert c.get(f'/api/trips/{tid}').json()['title'] == '西湖三日'
    trip = c.get(f'/api/trips/{tid}').json()
    saved = c.put(f'/api/trips/{tid}/days', json={'days': trip['days'], 'version': trip['version']})
    assert saved.status_code == 200 and saved.json()['title'] == '西湖三日'
    assert c.delete(f'/api/trips/{tid}').status_code == 200
    assert c.get(f'/api/trips/{tid}').status_code == 404, '已删除行程详情应 404'
    assert c.get('/api/trips').json() == []
    deleted = c.get('/api/trips', params={'deleted': 'true'}).json()
    assert [row['id'] for row in deleted] == [tid]
    assert c.post(f'/api/trips/{tid}/restore').status_code == 200
    assert [row['id'] for row in c.get('/api/trips').json()] == [tid]

def test_deleted_trip_isolated_and_purged_after_7_days(client):
    c, _ = client
    login(c)
    tid = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()['id']
    assert c.delete(f'/api/trips/{tid}').status_code == 200
    c.post('/api/logout')
    login(c, 'bob', 'password2')
    assert c.delete(f'/api/trips/{tid}').status_code == 404, '不能删除他人行程'
    with app_db.Session() as db:
        row = db.get(app_db.Trip, tid)
        row.deleted_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.commit()
    assert c.post(f'/api/trips/{tid}/restore').status_code == 404, '超过 7 天不可恢复'
    from backend.services import maintenance
    with app_db.Session() as db:
        maintenance.purge_expired(db)
    assert c.get('/api/trips', params={'deleted': 'true'}).json() == [], '过期行程应被清理任务清除'

def test_ensure_schema_migrates_legacy_trips():
    legacy = __import__('sqlalchemy').create_engine('sqlite://')
    with legacy.begin() as conn:
        conn.execute(text('CREATE TABLE trips (id INTEGER PRIMARY KEY, user_id INTEGER, city VARCHAR(80), data TEXT)'))
    ensure_schema(legacy)
    ensure_schema(legacy)  # 幂等
    cols = {c['name'] for c in inspect(legacy).get_columns('trips')}
    assert {'title', 'deleted_at', 'version'} <= cols


def test_stale_editor_cannot_overwrite_newer_changes(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    old_days = trip['days']
    updated_days = __import__('copy').deepcopy(old_days)
    updated_days[0]['stops'][0]['duration'] = 45
    saved = c.put(f"/api/trips/{trip['id']}/days", json={'days': updated_days, 'version': trip['version']})
    assert saved.status_code == 200
    stale = c.put(f"/api/trips/{trip['id']}/days", json={'days': old_days, 'version': trip['version']})
    assert stale.status_code == 409
    assert c.get(f"/api/trips/{trip['id']}").json()['days'][0]['stops'][0]['duration'] == 45


def test_ai_response_cannot_overwrite_concurrent_save(client, monkeypatch):
    import json
    from backend.services import planning
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    async def keywords(message, days, backlog=None): return []
    async def edit(request, candidates, instruction, current_days, backlog=None, **kwargs):
        with app_db.Session() as other:
            row = other.get(app_db.Trip, trip['id'])
            data = json.loads(row.data)
            data['days'][0]['stops'][0]['duration'] = 45
            row.data = json.dumps(data, ensure_ascii=False)
            row.version += 1
            other.commit()
        return {'days': current_days, 'reply': '建议', 'changed': False}
    monkeypatch.setattr(planning, 'adjustment_keywords', keywords)
    monkeypatch.setattr(planning, 'suggest_edits', edit)
    result = c.post(f"/api/trips/{trip['id']}/assistant", json={'message': '提个建议', 'version': trip['version']})
    assert result.status_code == 409
    current = c.get(f"/api/trips/{trip['id']}").json()
    assert current['days'][0]['stops'][0]['duration'] == 45
    assert current['conversation'] == []
