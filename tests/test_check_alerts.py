import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import check_alerts


def _snapshot(**overrides):
    snapshot = {
        'requests': {'total': 100, 'by_status': {'200': 99, '500': 1}},
        'db': {'ok': True},
        'disk': {'ok': True, 'free_bytes': 10 * 1024 ** 3},
        'email': {'total': 5, 'by_outcome': {'sent': 5}},
    }
    snapshot.update(overrides)
    return snapshot


def _codes(alerts):
    return {alert['code'] for alert in alerts}


def test_healthy_snapshot_has_no_alerts():
    assert check_alerts.evaluate(_snapshot()) == []


def test_database_disk_and_email_alerts():
    snapshot = _snapshot(
        db={'ok': False, 'error': 'OperationalError'},
        disk={'ok': True, 'free_bytes': 100 * 1024 ** 2},
        email={'total': 5, 'by_outcome': {'failed': 2, 'unconfigured': 3}},
    )
    codes = _codes(check_alerts.evaluate(snapshot))
    assert {'database_unavailable', 'disk_low', 'email_failed', 'email_unconfigured'} <= codes


def test_error_rates_need_enough_samples_and_absolute_counts():
    low_sample = _snapshot(requests={'total': 10, 'by_status': {'200': 5, '500': 5}})
    assert 'error_rate_high' not in _codes(check_alerts.evaluate(low_sample))

    few_errors = _snapshot(requests={'total': 100, 'by_status': {'200': 98, '500': 2}})
    assert 'error_rate_high' not in _codes(check_alerts.evaluate(few_errors))

    high_rates = _snapshot(requests={'total': 100, 'by_status': {'200': 74, '500': 5, '429': 21}})
    codes = _codes(check_alerts.evaluate(high_rates))
    assert {'error_rate_high', 'throttle_rate_high'} <= codes


def test_missing_metrics_fields_do_not_crash():
    assert check_alerts.evaluate({}) == []


def test_delta_snapshot_uses_counter_differences():
    previous = check_alerts.make_state(_snapshot(
        requests={'total': 100, 'by_status': {'200': 99, '500': 1}},
        email={'by_outcome': {'failed': 1, 'unconfigured': 1}},
    ))
    current = _snapshot(
        requests={'total': 150, 'by_status': {'200': 146, '500': 3, '429': 1}},
        email={'by_outcome': {'failed': 2, 'unconfigured': 3}},
    )
    window = check_alerts.delta_snapshot(previous, current)
    assert window['requests']['total'] == 50
    assert window['requests']['by_status'] == {'200': 47, '500': 2, '429': 1}
    assert window['email']['by_outcome'] == {'failed': 1, 'unconfigured': 2}
    assert window['db'] == {'ok': True}


def test_delta_snapshot_rejects_counter_reset():
    previous = check_alerts.make_state(_snapshot(requests={'total': 100, 'by_status': {'200': 100}}))
    assert check_alerts.delta_snapshot(previous, _snapshot(requests={'total': 40, 'by_status': {'200': 40}})) is None


def test_baseline_snapshot_only_checks_db_and_disk():
    baseline = check_alerts.baseline_snapshot(_snapshot())
    assert baseline['requests']['total'] == 0
    assert baseline['email']['by_outcome'] == {}
    assert baseline['db'] == {'ok': True}


def test_state_round_trip(tmp_path):
    path = tmp_path / 'state.json'
    check_alerts.save_state(path, _snapshot())
    state = check_alerts.load_state(path)
    assert state['requests_total'] == 100
    assert state['by_status']['500'] == 1
    assert check_alerts.load_state(tmp_path / 'missing.json') is None


def test_webhook_payload_shapes():
    text = '行迹告警'
    alerts = [{'level': 'warning', 'code': 'x', 'message': 'y'}]
    assert check_alerts.webhook_payload('dingtalk', text, alerts) == {
        'msgtype': 'text', 'text': {'content': text}}
    assert check_alerts.webhook_payload('feishu', text, alerts) == {
        'msg_type': 'text', 'content': {'text': text}}
    assert check_alerts.webhook_payload('slack', text, alerts) == {'text': text}
    generic = check_alerts.webhook_payload('generic', text, alerts)
    assert generic['text'] == text and generic['alerts'] == alerts
    with pytest.raises(ValueError):
        check_alerts.webhook_payload('unknown', text, alerts)


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


def test_fetch_metrics_sends_admin_token_and_parses_json():
    class Handler(BaseHTTPRequestHandler):
        seen_token = None

        def do_GET(self):
            Handler.seen_token = self.headers.get('X-Admin-Token')
            body = json.dumps({'requests': {'total': 3}}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with _serve(Handler) as server:
        snapshot = check_alerts.fetch_metrics(
            f'http://127.0.0.1:{server.server_address[1]}/api/metrics', 'admin-secret')
    assert snapshot == {'requests': {'total': 3}}
    assert Handler.seen_token == 'admin-secret'


def test_send_webhook_posts_json():
    class Handler(BaseHTTPRequestHandler):
        body = None

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            Handler.body = self.rfile.read(length)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with _serve(Handler) as server:
        status = check_alerts.send_webhook(
            f'http://127.0.0.1:{server.server_address[1]}/hook',
            {'text': '告警', 'alerts': []})
    assert status == 204
    assert json.loads(Handler.body.decode('utf-8')) == {'text': '告警', 'alerts': []}


def test_format_text_contains_codes_and_instance():
    text = check_alerts.format_text(
        [{'level': 'critical', 'code': 'database_unavailable', 'message': '数据库不可用'}],
        instance='trip-prod')
    assert 'trip-prod' in text
    assert 'database_unavailable' in text
    assert '数据库不可用' in text

def test_main_returns_error_when_state_cannot_be_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_alerts, 'fetch_metrics', lambda *args, **kwargs: _snapshot())

    def fail_save(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(check_alerts, 'save_state', fail_save)
    code = check_alerts.main([
        '--env-file', str(tmp_path / 'missing.env'),
        '--admin-token', 'test-token',
        '--state-file', str(tmp_path / 'state.json'),
        '--json',
    ])
    assert code == 2
    assert '告警状态写入失败' in capsys.readouterr().err


def test_main_baselines_then_sends_webhook_on_delta(tmp_path, capsys):
    calls = {'count': 0}

    class Metrics(BaseHTTPRequestHandler):
        def do_GET(self):
            calls['count'] += 1
            if calls['count'] == 1:
                payload = _snapshot()
            else:
                payload = _snapshot(
                    requests={'total': 150, 'by_status': {'200': 144, '500': 6}},
                    email={'by_outcome': {'failed': 1}},
                )
            body = json.dumps(payload).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    class Hook(BaseHTTPRequestHandler):
        messages = []

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            Hook.messages.append(json.loads(self.rfile.read(length).decode('utf-8')))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with _serve(Metrics) as metrics_server, _serve(Hook) as hook_server:
        args = [
            '--env-file', str(tmp_path / 'missing.env'),
            '--metrics-url', f'http://127.0.0.1:{metrics_server.server_address[1]}/api/metrics',
            '--webhook-url', f'http://127.0.0.1:{hook_server.server_address[1]}/hook',
            '--admin-token', 'test-token',
            '--state-file', str(tmp_path / 'state.json'),
            '--json',
        ]
        assert check_alerts.main(args) == 0
        assert check_alerts.main(args) == 1

    assert len(Hook.messages) == 1
    assert Hook.messages[0]['alerts']
    assert calls['count'] == 2
    assert '首次采样' in capsys.readouterr().err
