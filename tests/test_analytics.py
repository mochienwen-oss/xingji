"""A3 首方埋点：日计数只聚合事件，不采集个人数据。"""
from datetime import datetime, timezone

from backend.services import analytics


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def test_record_aggregates_daily_counts(client):
    assert analytics.record('login') is True
    assert analytics.record('login') is True
    summary = analytics.summary(days=1)
    assert summary['days'] == 1
    assert summary['by_day'][_today()]['login'] == 2


def test_unknown_event_is_ignored(client):
    assert analytics.record('password') is False
    assert analytics.summary(days=1)['by_day'] == {}


def test_login_endpoint_records_event(client):
    c, _ = client
    resp = c.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert resp.status_code == 200
    assert analytics.summary(days=1)['by_day'][_today()]['login'] >= 1


def test_metrics_exposes_analytics(client, monkeypatch):
    c, _ = client
    analytics.record('share')
    monkeypatch.setenv('ADMIN_TOKEN', 'ops-secret')
    body = c.get('/api/metrics', headers={'X-Admin-Token': 'ops-secret'}).json()
    assert body['analytics']['days'] == 14
    assert body['analytics']['by_day'][_today()]['share'] == 1
