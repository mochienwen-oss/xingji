"""A11 UGC 举报：公开广场/私密分享入口、去重、运营下架与凭证保护。"""
import pytest
from sqlalchemy import select

import backend.db as app_db
from backend.db import ShareLink, Trip, TripInvite, TripReport
from backend.services import ratelimit
from tests.conftest import login


def _create_trip(c, city='杭州', days=2):
    resp = c.post('/api/trips', json={'city': city, 'days': days, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()['id']


@pytest.fixture
def public_trip(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    assert c.put(f'/api/trips/{trip_id}/visibility', json={'is_public': True}).status_code == 200
    return trip_id


def test_report_public_trip_anonymous(client, public_trip):
    c, _ = client
    c.cookies.clear()
    resp = c.post(f'/api/trips/{public_trip}/report',
                  json={'reason': '虚假信息', 'detail': '开放时间明显不对'})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['ok'] is True and body['duplicate'] is False
    assert '24 小时' in body['message']
    with app_db.Session() as db:
        row = db.scalar(select(TripReport).where(TripReport.id == body['id']))
        assert row.trip_id == public_trip
        assert row.trip_city == '杭州'
        assert row.reporter_user_id is None
        assert row.source == 'plaza'
        assert row.status == 'pending'


def test_report_unlisted_trip_hidden(client, public_trip):
    c, _ = client
    login(c)
    private_id = _create_trip(c, city='苏州')
    for target in (private_id, 99999):
        resp = c.post(f'/api/trips/{target}/report', json={'reason': '垃圾广告'})
        assert resp.status_code == 404
        assert '未公开' in resp.json()['detail']


def test_report_private_share_anonymous(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    token = c.post(f'/api/trips/{trip_id}/share').json()['token']
    c.cookies.clear()
    resp = c.post(f'/api/shares/{token}/report', json={'reason': '侵犯隐私', 'detail': '包含住址'})
    assert resp.status_code == 200, resp.text
    assert resp.json()['ok'] is True
    with app_db.Session() as db:
        row = db.scalar(select(TripReport).where(TripReport.id == resp.json()['id']))
        assert row.source == 'share' and row.trip_id == trip_id


def test_report_rejects_bad_reason_and_long_detail(client, public_trip):
    c, _ = client
    c.cookies.clear()
    bad = c.post(f'/api/trips/{public_trip}/report', json={'reason': '看不顺眼'})
    assert bad.status_code == 422
    too_long = c.post(f'/api/trips/{public_trip}/report',
                      json={'reason': '其他', 'detail': 'x' * 1001})
    assert too_long.status_code == 422


def test_report_duplicate_for_same_user(client, public_trip):
    c, _ = client
    login(c, 'bob', 'password2')
    first = c.post(f'/api/trips/{public_trip}/report', json={'reason': '违法违规'})
    assert first.status_code == 200
    second = c.post(f'/api/trips/{public_trip}/report', json={'reason': '其他'})
    assert second.status_code == 200
    assert second.json()['duplicate'] is True
    assert second.json()['id'] == first.json()['id']


def test_admin_requires_configured_token(client, public_trip, monkeypatch):
    c, _ = client
    c.cookies.clear()
    c.post(f'/api/trips/{public_trip}/report', json={'reason': '其他'})
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    assert c.get('/api/admin/reports').status_code == 404
    monkeypatch.setenv('ADMIN_TOKEN', 'secret-admin-token')
    assert c.get('/api/admin/reports').status_code == 403
    assert c.get('/api/admin/reports', headers={'X-Admin-Token': 'wrong'}).status_code == 403


def test_admin_hide_revokes_public_share_and_invite(client, public_trip, monkeypatch):
    c, _ = client
    login(c)
    token = c.post(f'/api/trips/{public_trip}/share').json()['token']
    invite = c.post(f'/api/trips/{public_trip}/collaborators/invite').json()['token']
    assert invite
    c.cookies.clear()
    report_id = c.post(f'/api/trips/{public_trip}/report', json={'reason': '违法违规'}).json()['id']

    monkeypatch.setenv('ADMIN_TOKEN', 'secret-admin-token')
    headers = {'X-Admin-Token': 'secret-admin-token'}
    listing = c.get('/api/admin/reports', headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()['total'] == 1
    assert listing.json()['reports'][0]['id'] == report_id
    # 匿名举报没有举报人，但字段必须存在，运营端不用猜。
    assert listing.json()['reports'][0]['reporter'] is None

    resolved = c.post(f'/api/admin/reports/{report_id}/resolve',
                      json={'action': 'hide', 'note': '确认违规'}, headers=headers)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['status'] == 'hidden'

    with app_db.Session() as db:
        trip = db.get(Trip, public_trip)
        assert trip.is_public == 0
        assert db.scalar(select(ShareLink).where(ShareLink.trip_id == public_trip)).revoked_at
        assert db.scalars(select(TripInvite).where(TripInvite.trip_id == public_trip)).all() == []
        report = db.get(TripReport, report_id)
        assert report.status == 'hidden' and report.resolved_at
        assert report.resolution == '确认违规'

    # 下架后公开入口消失，分享链接失效
    assert c.post('/api/shares/view', json={'token': token}).status_code == 404
    assert c.get('/api/plaza').json()['trips'] == []
    again = c.post(f'/api/admin/reports/{report_id}/resolve',
                   json={'action': 'dismiss'}, headers=headers)
    assert again.status_code == 409


def test_admin_dismiss_keeps_content(client, public_trip, monkeypatch):
    c, _ = client
    c.cookies.clear()
    report_id = c.post(f'/api/trips/{public_trip}/report', json={'reason': '其他'}).json()['id']
    monkeypatch.setenv('ADMIN_TOKEN', 'admin')
    headers = {'X-Admin-Token': 'admin'}
    resp = c.post(f'/api/admin/reports/{report_id}/resolve', json={'action': 'dismiss'}, headers=headers)
    assert resp.status_code == 200 and resp.json()['status'] == 'dismissed'
    with app_db.Session() as db:
        assert db.get(Trip, public_trip).is_public == 1
    assert any(item['id'] == public_trip for item in c.get('/api/plaza').json()['trips'])


def test_report_rules_are_tight():
    rule = ratelimit.match('/api/trips/12/report')
    assert rule is not None and rule.capacity == 3
    share_rule = ratelimit.match('/api/shares/abcDEF123/report')
    assert share_rule is not None and share_rule.capacity == 3
    assert ratelimit.match('/api/trips/12').capacity == 60

def test_admin_list_includes_reporter_username(client, public_trip, monkeypatch):
    c, _ = client
    login(c, 'bob', 'password2')
    assert c.post(f'/api/trips/{public_trip}/report', json={'reason': '其他'}).status_code == 200
    monkeypatch.setenv('ADMIN_TOKEN', 'secret-admin-token')
    listing = c.get('/api/admin/reports', headers={'X-Admin-Token': 'secret-admin-token'})
    assert listing.status_code == 200, listing.text
    assert listing.json()['reports'][0]['reporter'] == 'bob'
