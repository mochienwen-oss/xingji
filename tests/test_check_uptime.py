import json
import ssl
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import check_uptime


class _HealthHandler(BaseHTTPRequestHandler):
    status = 200
    body = b'{"status":"ok","db":"ok"}'

    def do_GET(self):  # noqa: N802 - http.server 接口
        self.send_response(self.status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):  # noqa: A002 - http.server 接口
        return


class _HookHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server 接口
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length)
        _HookHandler.received.append(json.loads(raw.decode('utf-8')))
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, format, *args):  # noqa: A002 - http.server 接口
        return


@contextmanager
def _serve(handler_cls):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _probe(**overrides):
    probe = {
        'ok': True,
        'status': 200,
        'latency_ms': 120.0,
        'error': None,
        'health': 'ok',
        'health_error': None,
    }
    probe.update(overrides)
    return probe


def _cert(**overrides):
    cert = {'checked': True, 'valid': True, 'days_left': 90.0}
    cert.update(overrides)
    return cert


def _codes(alerts):
    return {alert['code'] for alert in alerts}


def test_healthy_probe_and_cert_have_no_alerts():
    assert check_uptime.evaluate(_probe(), _cert()) == []
    assert check_uptime.evaluate(_probe(), None) == []


def test_unreachable_site_is_critical():
    unreachable = check_uptime.evaluate(
        _probe(ok=False, status=None, error='network error: URLError'),
        None,
    )
    assert _codes(unreachable) == {'uptime_unreachable'}
    assert unreachable[0]['level'] == 'critical'

    bad_status = check_uptime.evaluate(_probe(ok=False, status=503, health='degraded'), None)
    assert _codes(bad_status) == {'uptime_unreachable'}
    assert 'HTTP 503' in bad_status[0]['message']


def test_degraded_health_and_high_latency():
    alerts = check_uptime.evaluate(
        _probe(health='degraded', latency_ms=9000),
        None,
        max_latency_ms=5000,
    )
    assert {'health_degraded', 'latency_high'} <= _codes(alerts)
    levels = {alert['code']: alert['level'] for alert in alerts}
    assert levels['health_degraded'] == 'critical'
    assert levels['latency_high'] == 'warning'


def test_latency_threshold_zero_disables_alert():
    assert check_uptime.evaluate(_probe(latency_ms=9000), None, max_latency_ms=0) == []


def test_unparseable_health_warns_unless_disabled():
    probe = _probe(health=None, health_error='invalid_json')
    alerts = check_uptime.evaluate(probe, None)
    assert _codes(alerts) == {'health_unparsed'}
    assert alerts[0]['level'] == 'warning'
    assert check_uptime.evaluate(probe, None, expect_health=False) == []


def test_certificate_invalid_and_expiry_thresholds():
    invalid = check_uptime.evaluate(_probe(), _cert(valid=False, days_left=None, error='SSLError'))
    assert _codes(invalid) == {'tls_invalid'}
    assert invalid[0]['level'] == 'critical'

    warning = check_uptime.evaluate(_probe(), _cert(days_left=10), min_cert_days=14, critical_cert_days=7)
    assert _codes(warning) == {'tls_expiring'}
    assert warning[0]['level'] == 'warning'

    critical = check_uptime.evaluate(_probe(), _cert(days_left=3), min_cert_days=14, critical_cert_days=7)
    assert _codes(critical) == {'tls_expiring_critical'}
    assert critical[0]['level'] == 'critical'


def test_certificate_skipped_for_http():
    assert check_uptime.check_certificate('http://127.0.0.1:1/api/health') == {
        'checked': False,
        'valid': None,
        'reason': 'not_https',
    }


def test_certificate_days_left_uses_not_after():
    assert check_uptime.certificate_days_left(
        'Jan  1 00:00:00 2030 GMT',
        now=ssl.cert_time_to_seconds('Jan  1 00:00:00 2029 GMT'),
    ) == pytest.approx(365.0)


def test_probe_http_reads_health_json():
    with _serve(_HealthHandler) as server:
        probe = check_uptime.probe_http(f'http://127.0.0.1:{server.server_port}/api/health', timeout=2)
    assert probe['ok'] is True
    assert probe['status'] == 200
    assert probe['health'] == 'ok'
    assert probe['error'] is None
    assert probe['latency_ms'] >= 0


def test_probe_http_keeps_http_error_status():
    _HealthHandler.status = 503
    _HealthHandler.body = b'{"status":"degraded","db":"error"}'
    try:
        with _serve(_HealthHandler) as server:
            probe = check_uptime.probe_http(f'http://127.0.0.1:{server.server_port}/api/health', timeout=2)
    finally:
        _HealthHandler.status = 200
        _HealthHandler.body = b'{"status":"ok","db":"ok"}'
    assert probe['ok'] is False
    assert probe['status'] == 503
    assert probe['health'] == 'degraded'
    assert probe['error'] == 'HTTP 503'


def test_probe_http_handles_non_json_body():
    _HealthHandler.status = 200
    _HealthHandler.body = b'<html>ok</html>'
    try:
        with _serve(_HealthHandler) as server:
            probe = check_uptime.probe_http(f'http://127.0.0.1:{server.server_port}/', timeout=2)
    finally:
        _HealthHandler.status = 200
        _HealthHandler.body = b'{"status":"ok","db":"ok"}'
    assert probe['ok'] is True
    assert probe['health'] is None
    assert probe['health_error'] == 'invalid_json'


def test_main_requires_url(monkeypatch, tmp_path):
    monkeypatch.delenv('UPTIME_URL', raising=False)
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--dry-run',
    ])
    assert code == 2


def test_main_rejects_invalid_scheme(monkeypatch, tmp_path):
    monkeypatch.delenv('UPTIME_URL', raising=False)
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--url', 'ftp://example.test/health',
        '--no-cert',
        '--dry-run',
    ])
    assert code == 2


@pytest.mark.parametrize('url', ['https://', 'https://trip.example.test:bad/api/health'])
def test_main_rejects_malformed_url(monkeypatch, tmp_path, url):
    monkeypatch.delenv('UPTIME_URL', raising=False)
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--url', url,
        '--no-cert',
        '--dry-run',
    ])
    assert code == 2


def test_main_healthy_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(check_uptime, 'probe_http', lambda url, timeout: _probe())
    monkeypatch.setattr(check_uptime, 'check_certificate',
                        lambda url, timeout: {'checked': False, 'valid': None, 'reason': 'not_https'})
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--url', 'https://trip.example.test/api/health',
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert '行迹告警（0 条）' in captured.out


def test_main_sends_webhook_for_alert(monkeypatch, tmp_path):
    _HookHandler.received.clear()
    monkeypatch.setattr(check_uptime, 'probe_http',
                        lambda url, timeout: _probe(ok=False, status=503, health='degraded'))
    monkeypatch.setattr(check_uptime, 'check_certificate',
                        lambda url, timeout: {'checked': False, 'valid': None, 'reason': 'not_https'})
    with _serve(_HookHandler) as server:
        code = check_uptime.main([
            '--env-file', str(tmp_path / 'missing.env'),
            '--url', 'https://trip.example.test/api/health',
            '--webhook-url', f'http://127.0.0.1:{server.server_port}/hook',
            '--webhook-type', 'generic',
        ])
    assert code == 1
    assert len(_HookHandler.received) == 1
    payload = _HookHandler.received[0]
    assert payload['alerts'][0]['code'] == 'uptime_unreachable'
    assert '站点探活失败' in payload['text']


def test_main_returns_two_when_webhook_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(check_uptime, 'probe_http',
                        lambda url, timeout: _probe(ok=False, status=503))
    monkeypatch.setattr(check_uptime, 'check_certificate',
                        lambda url, timeout: {'checked': False, 'valid': None, 'reason': 'not_https'})
    monkeypatch.setattr(check_uptime, 'send_webhook',
                        lambda *args, **kwargs: (_ for _ in ()).throw(check_uptime.WebhookError('boom')))
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--url', 'https://trip.example.test/api/health',
        '--webhook-url', 'https://hook.example.test/x',
    ])
    assert code == 2


def test_main_json_output_contains_probe_and_cert(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(check_uptime, 'probe_http', lambda url, timeout: _probe())
    monkeypatch.setattr(check_uptime, 'check_certificate',
                        lambda url, timeout: _cert(days_left=10))
    code = check_uptime.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--url', 'https://trip.example.test/api/health',
        '--json',
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 1
    assert payload['alerts'][0]['code'] == 'tls_expiring'
    assert payload['probe']['status'] == 200
    assert payload['cert']['days_left'] == 10
    assert 'body' not in payload['probe']
