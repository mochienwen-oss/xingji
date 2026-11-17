#!/usr/bin/env python3
"""读取 /api/metrics 并按两次采样差分评估上线告警，供 cron / 外部探针调用。

设计约束：
- 只用标准库，部署机不需要额外安装依赖；
- 不打印 ADMIN_TOKEN、webhook URL 或指标正文，避免密钥进日志；
- 无告警时不发送 webhook；退出码 0=正常、1=有告警、2=配置或传输失败；
- 比率按两次采样增量计算，进程重启/首次运行只做基线，不拿累计值误报。

用法：
    python scripts/check_alerts.py
    python scripts/check_alerts.py --json
    python scripts/check_alerts.py --webhook-url "$ALERT_WEBHOOK_URL" --webhook-type dingtalk
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_METRICS_URL = 'http://127.0.0.1:8000/api/metrics'
DEFAULT_STATE_FILE = PROJECT_ROOT / '.tmp-alert-state.json'
STATE_VERSION = 1

DEFAULT_THRESHOLDS: dict[str, float] = {
    'min_requests': 20,
    'min_5xx_count': 3,
    'max_5xx_rate': 0.01,
    'min_429_count': 20,
    'max_429_rate': 0.10,
    'min_disk_free_gb': 2.0,
    'max_email_failed': 0,
}


class MetricsError(RuntimeError):
    """指标读取失败；消息只保留可安全打印的原因。"""


class WebhookError(RuntimeError):
    """webhook 发送失败；不携带 URL 或响应正文。"""


def fetch_metrics(metrics_url: str, admin_token: str, timeout: float = 10.0) -> dict[str, Any]:
    """带 X-Admin-Token 读取指标 JSON；错误信息不包含 URL。"""
    request = urllib.request.Request(
        metrics_url,
        headers={'X-Admin-Token': admin_token, 'Accept': 'application/json'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise MetricsError(f'metrics endpoint returned HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MetricsError(f'metrics endpoint unavailable: {type(exc).__name__}') from None
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MetricsError('metrics endpoint returned invalid JSON') from None
    if not isinstance(payload, dict):
        raise MetricsError('metrics endpoint returned a non-object payload')
    return payload


def _status_counts(snapshot: Mapping[str, Any]) -> dict[int, int]:
    raw = (snapshot.get('requests') or {}).get('by_status') or {}
    counts: dict[int, int] = {}
    if not isinstance(raw, Mapping):
        return counts
    for key, value in raw.items():
        try:
            code = int(key)
            amount = int(value)
        except (TypeError, ValueError):
            continue
        counts[code] = amount
    return counts


def _request_total(snapshot: Mapping[str, Any], counts: Mapping[int, int]) -> int:
    raw = (snapshot.get('requests') or {}).get('total')
    try:
        total = int(raw)
    except (TypeError, ValueError):
        total = sum(counts.values())
    return max(0, total)


def _outcome_counts(snapshot: Mapping[str, Any]) -> dict[str, int]:
    raw = (snapshot.get('email') or {}).get('by_outcome') or {}
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def make_state(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """只保存计算差分所需的计数器，不含用户数据。"""
    counts = _status_counts(snapshot)
    outcomes = _outcome_counts(snapshot)
    latency = snapshot.get('latency_ms')
    try:
        peak = float((latency or {}).get('max') or 0) if isinstance(latency, Mapping) else 0.0
    except (TypeError, ValueError):
        peak = 0.0
    return {
        'version': STATE_VERSION,
        'checked_at': time.time(),
        'requests_total': _request_total(snapshot, counts),
        'by_status': {str(code): amount for code, amount in counts.items()},
        'email_failed': int(outcomes.get('failed') or 0),
        'email_unconfigured': int(outcomes.get('unconfigured') or 0),
        'latency_max': peak,
    }


def load_state(path: str | Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get('version') != STATE_VERSION:
        return None
    return data


def save_state(path: str | Path, snapshot: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.tmp')
    temp.write_text(json.dumps(make_state(snapshot), ensure_ascii=False), encoding='utf-8')
    os.replace(temp, target)


def delta_snapshot(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any] | None:
    """用两次采样做差；首次运行、进程重启或计数器回退时返回 None。"""
    if not previous:
        return None
    now = make_state(current)
    try:
        previous_total = int(previous['requests_total'])
        previous_status = {int(key): int(value) for key, value in (previous.get('by_status') or {}).items()}
        previous_failed = int(previous.get('email_failed') or 0)
        previous_unconfigured = int(previous.get('email_unconfigured') or 0)
    except (KeyError, TypeError, ValueError):
        return None
    current_total = int(now['requests_total'])
    if current_total < previous_total:
        return None
    status_delta: dict[str, int] = {}
    for code, amount in now['by_status'].items():
        difference = int(amount) - previous_status.get(int(code), 0)
        if difference < 0:
            return None
        if difference:
            status_delta[str(code)] = difference
    failed = int(now['email_failed']) - previous_failed
    unconfigured = int(now['email_unconfigured']) - previous_unconfigured
    if failed < 0 or unconfigured < 0:
        return None
    return {
        'requests': {'total': current_total - previous_total, 'by_status': status_delta},
        'email': {'total': failed + unconfigured,
                  'by_outcome': {'failed': failed, 'unconfigured': unconfigured}},
        'db': current.get('db'),
        'disk': current.get('disk'),
        'latency_ms': {'max': now['latency_max']},
    }


def baseline_snapshot(current: Mapping[str, Any]) -> dict[str, Any]:
    """首次/重启后的基线：只做 DB 与磁盘检查，比率留到下一轮差分。"""
    return {
        'requests': {'total': 0, 'by_status': {}},
        'email': {'total': 0, 'by_outcome': {}},
        'db': current.get('db'),
        'disk': current.get('disk'),
        'latency_ms': {'max': 0},
    }


def evaluate(snapshot: Mapping[str, Any], thresholds: Mapping[str, float] | None = None) -> list[dict[str, str]]:
    """把指标快照变成告警列表；纯函数，便于测试。"""
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)
    alerts: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        alerts.append({'level': level, 'code': code, 'message': message})

    db = snapshot.get('db')
    if isinstance(db, Mapping) and db.get('ok') is False:
        add('critical', 'database_unavailable', '数据库探测失败，登录/行程/生成都会受影响。')

    disk = snapshot.get('disk')
    if isinstance(disk, Mapping):
        if disk.get('ok') is False:
            add('warning', 'disk_probe_failed', '磁盘探测失败，无法确认剩余空间。')
        else:
            try:
                free_bytes = int(disk.get('free_bytes'))
            except (TypeError, ValueError):
                free_bytes = None
            if free_bytes is not None:
                free_gb = free_bytes / (1024 ** 3)
                if free_gb < float(limits['min_disk_free_gb']):
                    add('critical', 'disk_low', f'磁盘剩余 {free_gb:.1f} GB，低于阈值 {limits["min_disk_free_gb"]:.1f} GB。')

    counts = _status_counts(snapshot)
    total = _request_total(snapshot, counts)
    if total >= int(limits['min_requests']):
        server_errors = sum(value for code, value in counts.items() if 500 <= code <= 599)
        rate_limited = counts.get(429, 0)
        error_rate = server_errors / total
        throttle_rate = rate_limited / total
        if server_errors >= int(limits['min_5xx_count']) and error_rate > float(limits['max_5xx_rate']):
            add('critical', 'error_rate_high',
                f'5xx {server_errors}/{total}（{error_rate:.1%}），高于阈值 {limits["max_5xx_rate"]:.1%}。')
        if rate_limited >= int(limits['min_429_count']) and throttle_rate > float(limits['max_429_rate']):
            add('warning', 'throttle_rate_high',
                f'429 {rate_limited}/{total}（{throttle_rate:.1%}），高于阈值 {limits["max_429_rate"]:.1%}。')

    outcomes = _outcome_counts(snapshot)
    failed = int(outcomes.get('failed') or 0)
    unconfigured = int(outcomes.get('unconfigured') or 0)
    if failed > int(limits['max_email_failed']):
        add('warning', 'email_failed', f'事务邮件发送失败 {failed} 次，注册/找回可能收不到信。')
    if unconfigured > 0:
        add('warning', 'email_unconfigured', f'SMTP 未配置，已有 {unconfigured} 次邮件请求被跳过。')

    return alerts


def format_text(alerts: Sequence[Mapping[str, str]], instance: str = '') -> str:
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    title = f'行迹告警（{len(alerts)} 条）'
    if instance:
        title += f' · {instance}'
    lines = [f'{title} {stamp}']
    for alert in alerts:
        lines.append(f"- [{alert['level']}] {alert['code']}: {alert['message']}")
    return '\n'.join(lines)


def webhook_payload(kind: str, text: str, alerts: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """兼容常见群机器人；generic 保留结构化 alerts 便于自建接收端。"""
    kind = (kind or 'generic').strip().lower()
    if kind == 'dingtalk':
        return {'msgtype': 'text', 'text': {'content': text}}
    if kind == 'feishu':
        return {'msg_type': 'text', 'content': {'text': text}}
    if kind == 'slack':
        return {'text': text}
    if kind == 'generic':
        return {'text': text, 'alerts': list(alerts)}
    raise ValueError(f'unsupported webhook type: {kind}')


def send_webhook(webhook_url: str, payload: Mapping[str, Any], timeout: float = 10.0) -> int:
    """POST JSON 到 webhook；返回 HTTP 状态码，不读取响应正文。"""
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        raise WebhookError(f'webhook returned HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WebhookError(f'webhook request failed: {type(exc).__name__}') from None


def _load_env_file(path: str) -> None:
    if not path or not Path(path).exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(path, override=False)


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, float]:
    return {
        'min_requests': max(1, int(args.min_requests)),
        'min_5xx_count': max(1, int(args.min_5xx_count)),
        'max_5xx_rate': max(0.0, float(args.max_5xx_rate)),
        'min_429_count': max(1, int(args.min_429_count)),
        'max_429_rate': max(0.0, float(args.max_429_rate)),
        'min_disk_free_gb': max(0.0, float(args.min_disk_free_gb)),
        'max_email_failed': max(0, int(args.max_email_failed)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='读取 /api/metrics 并按采样增量评估上线告警')
    parser.add_argument('--env-file', default=str(PROJECT_ROOT / '.env'), help='读取环境变量（默认项目根 .env）')
    parser.add_argument('--metrics-url', default=None, help='默认取 METRICS_URL 或本机 8000')
    parser.add_argument('--admin-token', default=None, help='默认取 ADMIN_TOKEN；不会打印')
    parser.add_argument('--webhook-url', default=None, help='默认取 ALERT_WEBHOOK_URL；留空只打印')
    parser.add_argument('--webhook-type', default=None,
                        choices=('generic', 'dingtalk', 'feishu', 'slack'),
                        help='默认取 ALERT_WEBHOOK_TYPE，缺省 generic')
    parser.add_argument('--instance', default=None, help='默认取 ALERT_INSTANCE，可写部署名')
    parser.add_argument('--state-file', default=None,
                        help='默认取 ALERT_STATE_FILE 或项目根 .tmp-alert-state.json')
    parser.add_argument('--timeout', type=float, default=10.0, help='HTTP 超时秒数')
    parser.add_argument('--min-requests', type=int, default=DEFAULT_THRESHOLDS['min_requests'],
                        help='窗口请求数少于此值时跳过比率判断')
    parser.add_argument('--min-5xx-count', type=int, default=DEFAULT_THRESHOLDS['min_5xx_count'])
    parser.add_argument('--max-5xx-rate', type=float, default=DEFAULT_THRESHOLDS['max_5xx_rate'])
    parser.add_argument('--min-429-count', type=int, default=DEFAULT_THRESHOLDS['min_429_count'])
    parser.add_argument('--max-429-rate', type=float, default=DEFAULT_THRESHOLDS['max_429_rate'])
    parser.add_argument('--min-disk-free-gb', type=float, default=DEFAULT_THRESHOLDS['min_disk_free_gb'])
    parser.add_argument('--max-email-failed', type=int, default=DEFAULT_THRESHOLDS['max_email_failed'])
    parser.add_argument('--json', action='store_true', help='以 JSON 输出告警，便于日志采集')
    parser.add_argument('--dry-run', action='store_true', help='只评估，不发送 webhook')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_env_file(args.env_file)

    metrics_url = args.metrics_url or os.environ.get('METRICS_URL') or DEFAULT_METRICS_URL
    admin_token = (args.admin_token or os.environ.get('ADMIN_TOKEN') or '').strip()
    webhook_url = (args.webhook_url or os.environ.get('ALERT_WEBHOOK_URL') or '').strip()
    webhook_type = (args.webhook_type or os.environ.get('ALERT_WEBHOOK_TYPE') or 'generic').strip().lower()
    instance = (args.instance or os.environ.get('ALERT_INSTANCE') or '').strip()
    state_file = Path(args.state_file or os.environ.get('ALERT_STATE_FILE') or DEFAULT_STATE_FILE)

    if not admin_token:
        print('缺少 ADMIN_TOKEN：请设置环境变量或用 --admin-token 传入。', file=sys.stderr)
        return 2
    if webhook_type not in ('generic', 'dingtalk', 'feishu', 'slack'):
        print(f'不支持的 webhook 类型：{webhook_type}', file=sys.stderr)
        return 2

    thresholds = _thresholds_from_args(args)
    state_write_failed = False
    try:
        snapshot = fetch_metrics(metrics_url, admin_token, timeout=args.timeout)
    except MetricsError as exc:
        alerts = [{'level': 'critical', 'code': 'metrics_unreachable', 'message': str(exc)}]
        baseline = False
    else:
        window = delta_snapshot(load_state(state_file), snapshot)
        baseline = window is None
        if window is None:
            window = baseline_snapshot(snapshot)
            print('首次采样或进程重启：先建立基线，下轮开始判断 5xx/429/邮件增量。', file=sys.stderr)
        alerts = evaluate(window, thresholds)
        try:
            save_state(state_file, snapshot)
        except OSError as exc:
            state_write_failed = True
            print(f'告警状态写入失败：{type(exc).__name__}', file=sys.stderr)

    if args.json:
        print(json.dumps({'alerts': alerts, 'baseline': baseline}, ensure_ascii=False))
    else:
        print(format_text(alerts, instance=instance))

    if not alerts:
        # 状态写不进去时，下一轮仍会重建基线，比率告警会静默失效；让 cron 看到非零退出码。
        return 2 if state_write_failed else 0

    if not webhook_url:
        print('未配置 ALERT_WEBHOOK_URL：告警只打印，未推送。', file=sys.stderr)
        return 1
    if args.dry_run:
        print('dry-run：未发送 webhook。', file=sys.stderr)
        return 1

    try:
        status = send_webhook(
            webhook_url,
            webhook_payload(webhook_type, format_text(alerts, instance=instance), alerts),
            timeout=args.timeout,
        )
    except (WebhookError, ValueError) as exc:
        print(f'webhook 发送失败：{exc}', file=sys.stderr)
        return 2
    print(f'webhook 已发送（HTTP {status}）。', file=sys.stderr)
    return 2 if state_write_failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
