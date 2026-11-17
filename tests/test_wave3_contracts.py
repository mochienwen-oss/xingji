"""Wave3 契约：权限矩阵、邀请过期/撤销、分享撤销、游客灵感、时间校验、兜底异常与 SSE 心跳。"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.db as app_db
import backend.main as main
from backend.db import TripCollaborator, TripInvite
from backend.services import agent
from tests.conftest import login


def _create_trip(c, days=2):
    resp = c.post('/api/trips', json={'city': '杭州', 'days': days, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _invite(c, trip_id):
    resp = c.post(f'/api/trips/{trip_id}/collaborators/invite')
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register(c, username):
    resp = c.post('/api/register', json={'username': username, 'password': 'password3', 'email': f'{username}@example.com', 'accept_terms': True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _expense(note='member'):
    return {'amount_cents': 1200, 'category': '餐饮', 'expense_date': '2026-11-05', 'note': note}


def test_permission_matrix_owner_member_and_stranger(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    token = _invite(c, trip['id'])['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200

    # 成员：真实 role / is_owner，能记账看账，但不能改总预算
    detail = c.get(f"/api/trips/{trip['id']}").json()
    assert detail['is_owner'] is False and detail['is_public'] is False
    assert c.put(f"/api/trips/{trip['id']}/budget", json={'amount_cents': 5000}).status_code == 404
    assert c.post(f"/api/trips/{trip['id']}/expenses", json=_expense()).status_code == 201
    budget = c.get(f"/api/trips/{trip['id']}/budget").json()
    assert budget['amount_cents'] is None and [e['note'] for e in budget['expenses']] == ['member']

    # 陌生人：登录但不是成员，全部 404
    _register(c, 'carol')
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    assert c.get(f"/api/trips/{trip['id']}/budget").status_code == 404
    assert c.put(f"/api/trips/{trip['id']}/budget", json={'amount_cents': 1000}).status_code == 404
    assert c.post(f"/api/trips/{trip['id']}/expenses", json=_expense('stranger')).status_code == 404
    assert c.delete(f"/api/trips/{trip['id']}/members/me").status_code == 404

    # owner：能改总预算，不能退出协作
    login(c)
    assert c.put(f"/api/trips/{trip['id']}/budget", json={'amount_cents': 20000}).status_code == 200
    assert c.delete(f"/api/trips/{trip['id']}/members/me").status_code == 422
    assert c.get(f"/api/trips/{trip['id']}").json()['is_owner'] is True
    assert c.get(f"/api/trips/{trip['id']}/budget").json()['amount_cents'] == 20000

    # 成员自退：退后按陌生人处理（404），重复退出也 404
    login(c, 'bob', 'password2')
    assert c.delete(f"/api/trips/{trip['id']}/members/me").status_code == 200
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    assert c.delete(f"/api/trips/{trip['id']}/members/me").status_code == 404
    assert all(item['id'] != trip['id'] for item in c.get('/api/trips/shared').json()['trips'])
    login(c)
    assert [m['username'] for m in c.get(f"/api/trips/{trip['id']}/collaborators").json()['members']] == ['alice']


def test_shared_list_returns_stored_role(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    token = _invite(c, trip['id'])['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    with app_db.Session() as db:
        link = db.scalar(select(TripCollaborator).where(TripCollaborator.trip_id == trip['id']))
        link.role = 'view'
        db.commit()
    shared = c.get('/api/trips/shared').json()['trips']
    assert [item['role'] for item in shared if item['id'] == trip['id']] == ['view']


def test_invite_expiry_is_410_and_legacy_rows_use_created_at(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    fresh = _invite(c, trip['id'])
    delta = datetime.fromisoformat(fresh['expires_at']) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < delta <= timedelta(days=7)
    expired = _invite(c, trip['id'])['token']
    legacy = _invite(c, trip['id'])['token']
    with app_db.Session() as db:
        rows = {row.token_hash: row for row in db.scalars(select(TripInvite).where(TripInvite.trip_id == trip['id'])).all()}
        rows[hashlib.sha256(expired.encode()).hexdigest()].expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        old = rows[hashlib.sha256(legacy.encode()).hexdigest()]
        old.expires_at = None
        old.created_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.commit()
    login(c, 'bob', 'password2')
    resp = c.post('/api/collaborators/accept', json={'token': expired})
    assert resp.status_code == 410
    assert resp.json()['detail'] == '邀请链接已过期，请让行程创建者重新生成邀请。'
    assert c.post('/api/collaborators/accept', json={'token': legacy}).status_code == 410
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404


def test_owner_revokes_invites_and_self_accept_keeps_token(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    _invite(c, trip['id'])
    second = _invite(c, trip['id'])['token']
    assert c.post('/api/collaborators/accept', json={'token': second}).status_code == 422
    revoked = c.delete(f"/api/trips/{trip['id']}/invites")
    assert revoked.status_code == 200 and revoked.json()['revoked'] == 2
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': second}).status_code == 404
    assert c.get(f"/api/trips/{trip['id']}").status_code == 404
    _register(c, 'carol')
    assert c.delete(f"/api/trips/{trip['id']}/invites").status_code == 404
    login(c)
    token = _invite(c, trip['id'])['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 404  # 一次性


def test_share_links_single_active_and_revocable(client):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    first = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    second = c.post(f"/api/trips/{trip['id']}/share").json()['token']
    assert c.post('/api/shares/view', json={'token': first}).status_code == 404  # 新链接即撤销旧链接
    assert c.post('/api/shares/view', json={'token': second}).status_code == 200
    assert c.post('/api/shares/fork', json={'token': second}).status_code == 201
    login(c, 'bob', 'password2')
    assert c.delete(f'/api/shares/{second}').status_code == 404
    login(c)
    assert c.delete(f'/api/shares/{second}').status_code == 200
    assert c.post('/api/shares/view', json={'token': second}).status_code == 404
    assert c.post('/api/shares/fork', json={'token': second}).status_code == 404
    assert c.delete(f'/api/shares/{second}').status_code == 200  # 幂等
    assert c.delete('/api/shares/unknown-token').status_code == 404


def test_inspiration_is_guest_accessible(client, monkeypatch):
    c, _ = client
    assert c.get('/api/inspiration/themes', params={'city': '杭州'}).status_code == 200

    async def fake_route(city, label, desc):
        return {'title': '老城漫步', 'intro': '穿过三条老巷',
                'stops': [{'name': f'景点{i}', 'why': 'w'} for i in (1, 2, 3)]}

    monkeypatch.setattr('backend.api.inspiration.planning.inspiration_route', fake_route)
    resp = c.post('/api/inspiration', json={'city': '杭州', 'theme_id': 'citywalk'})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()['stops']) == 3 and all(stop['place']['id'] for stop in resp.json()['stops'])
    assert c.get('/api/me').status_code == 401  # 其它受保护端点仍要登录


def test_day_time_validation_allows_next_day_but_rejects_malformed(client):
    """结束早于/等于开始 = 次日（README 第 87 行），不是校验错误；HH:MM 格式错误仍要拦。"""
    c, _ = client
    login(c)
    trip = _create_trip(c, days=1)
    stops = trip['days'][0]['stops']

    def save(**day):
        return c.put(f"/api/trips/{trip['id']}/days", json={'days': [{'stops': stops, **day}]})

    reversed_day = save(start_time='18:00', end_time='09:00')
    assert reversed_day.status_code == 200, reversed_day.text
    assert reversed_day.json()['days'][0]['start_time'] == '18:00'
    assert reversed_day.json()['days'][0]['end_time'] == '09:00'
    assert save(start_time='9:00').status_code == 422
    assert save(start_time='24:00').status_code == 422
    same = save(start_time='09:00', end_time='09:00')
    assert same.status_code == 200 and same.json()['days'][0]['end_time'] == '09:00'
    cleared = save(start_time=None, end_time=None)
    assert cleared.status_code == 200 and cleared.json()['days'][0]['start_time'] is None


def test_day_time_validation_after_legacy_backfill(client):
    c, _ = client
    login(c)
    trip = _create_trip(c, days=1)
    stops = trip['days'][0]['stops']
    first = c.put(f"/api/trips/{trip['id']}/days",
                  json={'days': [{'stops': stops, 'start_time': '09:00', 'end_time': '18:00'}]})
    assert first.status_code == 200
    merged = c.put(f"/api/trips/{trip['id']}/days", json={'days': [{'stops': stops, 'end_time': '08:00'}]})
    # 老客户端只改 end_time：09:00→08:00 按次日计算，回填的 start_time 不受影响。
    assert merged.status_code == 200, merged.text
    assert merged.json()['days'][0]['start_time'] == '09:00'
    assert merged.json()['days'][0]['end_time'] == '08:00'
    kept = c.put(f"/api/trips/{trip['id']}/days", json={'days': [{'stops': stops, 'end_time': '20:00'}]})
    assert kept.status_code == 200 and kept.json()['days'][0]['start_time'] == '09:00'


def test_unhandled_exception_returns_generic_500(caplog):
    assert main.app.exception_handlers[Exception] is main.unhandled_exception
    probe = FastAPI()
    probe.add_exception_handler(Exception, main.unhandled_exception)

    @probe.get('/boom')
    def boom():
        raise RuntimeError('secret-stack-trace')

    with caplog.at_level(logging.ERROR, logger='trip'):
        with TestClient(probe, raise_server_exceptions=False) as probe_client:
            resp = probe_client.get('/boom')
    assert resp.status_code == 500
    assert resp.json() == {'detail': '服务暂时不可用，请稍后重试'}
    assert 'secret-stack-trace' not in resp.text and 'RuntimeError' not in resp.text
    assert any(record.exc_info for record in caplog.records)


def test_http_exception_is_not_swallowed_by_global_handler(client):
    c, _ = client
    resp = c.get('/api/me')
    assert resp.status_code == 401 and resp.json()['detail'] == '请先登录'


def test_trip_stream_keeps_connection_alive_with_heartbeat(client, monkeypatch):
    c, _ = client
    login(c)
    trip = _create_trip(c, days=1)

    async def slow(state):
        await asyncio.sleep(0.2)
        yield {'events': [{'kind': 'done'}]}
        yield {'suggestion': {'reply': '已按你的要求调整', 'changed': False}}

    monkeypatch.setattr(agent, 'run_stream', slow)
    monkeypatch.setattr('backend.api.trips.SSE_HEARTBEAT_SECONDS', 0.05)
    resp = c.post(f"/api/trips/{trip['id']}/assistant/stream", json={'message': '帮我安排轻松一点'})
    assert resp.status_code == 200
    assert ': ping\n\n' in resp.text
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith('data: ')]
    assert [event['kind'] for event in events] == ['done', 'saved']
