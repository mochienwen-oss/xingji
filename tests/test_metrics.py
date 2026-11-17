"""A2 运营指标：ADMIN_TOKEN 保护、路径归一化与健康探针字段。"""
from backend.services import metrics


def test_normalize_path_collapses_tokens_and_ids():
    assert metrics.normalize_path('/api/trips/12/days/3/nearby') == '/api/trips/{id}/days/{id}/nearby'
    assert metrics.normalize_path('/api/shares/abcDEF/report') == '/api/shares/{token}/report'
    assert metrics.normalize_path('/api/invites/xyz') == '/api/invites/{token}'
    assert metrics.normalize_path('/s/abcDEF') == '/s/{token}'
    assert metrics.normalize_path('') == '/'


def test_redact_path_hides_credentials_but_keeps_ids():
    assert metrics.redact_path('/s/abcDEF') == '/s/{token}'
    assert metrics.redact_path('/api/shares/abcDEF/report') == '/api/shares/{token}/report'
    assert metrics.redact_path('/api/invites/xyz') == '/api/invites/{token}'
    assert metrics.redact_path('/api/trips/12/days/3/nearby') == '/api/trips/12/days/3/nearby'
    assert metrics.redact_path('') == '/'


def test_observe_request_and_errors_are_aggregated():
    metrics.reset()
    metrics.observe_request('GET', '/api/trips/7', 200, 0.02)
    metrics.observe_request('GET', '/api/trips/8', 404, 0.01)
    metrics.record_error('database_busy')
    metrics.observe_email('sent')
    metrics.observe_email('failed')
    metrics.observe_email('failed')
    snapshot = metrics.snapshot()
    assert snapshot['requests']['total'] == 2
    assert snapshot['requests']['by_status'] == {'200': 1, '404': 1}
    assert snapshot['requests']['by_path']['/api/trips/{id}'] == 2
    assert snapshot['errors']['total'] == 1
    assert snapshot['errors']['by_kind']['database_busy'] == 1
    assert snapshot['email']['total'] == 3
    assert snapshot['email']['by_outcome'] == {'sent': 1, 'failed': 2}
    assert snapshot['latency_ms']['count'] == 2
    assert snapshot['latency_ms']['max'] == 20.0


def test_metrics_requires_admin_token(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    assert c.get('/api/metrics').status_code == 404

    monkeypatch.setenv('ADMIN_TOKEN', 'ops-secret')
    assert c.get('/api/metrics').status_code == 403
    assert c.get('/api/metrics', headers={'X-Admin-Token': 'wrong'}).status_code == 403


def test_metrics_reports_health_probes(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('ADMIN_TOKEN', 'ops-secret')
    assert c.get('/api/health').status_code == 200
    resp = c.get('/api/metrics', headers={'X-Admin-Token': 'ops-secret'})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['requests']['total'] >= 1
    assert '200' in body['requests']['by_status']
    assert body['db']['ok'] is True
    assert body['disk']['ok'] is True
    assert body['disk']['total_bytes'] > 0
    assert 'email' in body and 'by_outcome' in body['email']
    # 高德配额是首周最容易被重复消耗的成本项：命中/未命中要能从指标端点看到。
    assert body['amap']['place_hits'] >= 0
    assert body['amap']['place_misses'] >= 0
    assert body['amap']['place_entries'] >= 0
    # 指标端点自身响应在中间件 finally 中才计数，因此不应出现在本次快照内。
    assert body['requests']['by_path'].get('/api/metrics', 0) == 0
    assert 'uptime_seconds' in body and body['uptime_seconds'] >= 0
