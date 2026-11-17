#!/usr/bin/env python3
"""外部可用性与 TLS 证书检查，供另一台机器的 cron / 拨测脚本调用。

与 check_alerts.py 的分工：
- check_alerts.py 在本机读 /api/metrics，看 5xx/429/磁盘/邮件；
- 本脚本从外部访问公开 URL，看站点是否可达、健康检查是否 ok、TLS 证书是否将过期。

设计约束：
- 只用标准库，不依赖 openssl 命令行；
- 不在输出/j日志里打印 URL 中的凭据或响应正文；
- 退出码 0=正常、1=有告警、2=配置/传输失败；
- 每次运行独立判断，不做状态去重；去重交给外部拨测服务或 cron 的告警渠道。
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_LATENCY_MS = 5000.0
DEFAULT_MIN_CERT_DAYS = 14.0
DEFAULT_CRITICAL_CERT_DAYS = 7.0

try:  # python scripts/check_uptime.py 时用同级模块；pytest 导入时用包路径
    from scripts.check_alerts import (
        WebhookError,
        _load_env_file,
        format_text,
        send_webhook,
        webhook_payload,
    )
except ImportError:  # pragma: no cover - 只在脚本直接运行时走到
    from check_alerts import (  # type: ignore
        WebhookError,
        _load_env_file,
        format_text,
        send_webhook,
        webhook_payload,
    )


def _parse_health(raw: bytes) -> tuple[str | None, str | None]:
    """从响应体提取 status；只接受小型 JSON，不做正文输出。"""
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, 'invalid_json'
    if not isinstance(payload, Mapping):
        return None, 'non_object'
    status = payload.get('status')
    if isinstance(status, str):
        return status, None
    return None, 'missing_status'


def probe_http(url: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """GET 公开 URL；错误只保留状态码/异常类型，不含 URL 或响应正文。"""
    request = urllib.request.Request(
        url,
        headers={'Accept': 'application/json', 'User-Agent': 'trip-uptime/1.0'},
        method='GET',
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        latency = round((time.monotonic() - started) * 1000, 1)
        raw = b''
        try:
            raw = exc.read(4096)
        except (OSError, ValueError, http.client.HTTPException):
            pass
        health, health_error = _parse_health(raw) if raw else (None, None)
        return {
            'ok': False,
            'status': int(exc.code),
            'latency_ms': latency,
            'error': f'HTTP {exc.code}',
            'health': health,
            'health_error': health_error,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        latency = round((time.monotonic() - started) * 1000, 1)
        return {
            'ok': False,
            'status': None,
            'latency_ms': latency,
            'error': f'network error: {type(exc).__name__}',
            'health': None,
            'health_error': None,
        }
    latency = round((time.monotonic() - started) * 1000, 1)
    health, health_error = _parse_health(raw)
    return {
        'ok': 200 <= status < 300,
        'status': status,
        'latency_ms': latency,
        'error': None if 200 <= status < 300 else f'HTTP {status}',
        'health': health,
        'health_error': health_error,
    }


def certificate_days_left(not_after: str, *, now: float | None = None) -> float:
    """按证书 notAfter 计算剩余天数；便于测试，不发起网络请求。"""
    expires = ssl.cert_time_to_seconds(not_after)
    current = time.time() if now is None else float(now)
    return round((expires - current) / 86400, 1)


def check_certificate(url: str, timeout: float = DEFAULT_TIMEOUT, *, now: float | None = None) -> dict[str, Any]:
    """检查 HTTPS 证书有效性与剩余天数；HTTP URL 返回 checked=False。"""
    parts = urlsplit(url)
    if parts.scheme != 'https':
        return {'checked': False, 'valid': None, 'reason': 'not_https'}
    host = parts.hostname
    if not host:
        return {'checked': False, 'valid': None, 'reason': 'no_host'}
    port = parts.port or 443
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except (ssl.SSLError, ssl.CertificateError, OSError, ValueError) as exc:
        return {'checked': True, 'valid': False, 'days_left': None, 'error': type(exc).__name__}
    if not isinstance(cert, Mapping):
        return {'checked': True, 'valid': False, 'days_left': None, 'error': 'no_certificate'}
    not_after = cert.get('notAfter')
    if not isinstance(not_after, str):
        return {'checked': True, 'valid': False, 'days_left': None, 'error': 'no_not_after'}
    try:
        expires = ssl.cert_time_to_seconds(not_after)
        days_left = certificate_days_left(not_after, now=now)
    except (TypeError, ValueError):
        return {'checked': True, 'valid': False, 'days_left': None, 'error': 'bad_not_after'}
    return {
        'checked': True,
        'valid': True,
        'days_left': days_left,
        'not_after': datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
    }


def evaluate(
    probe: Mapping[str, Any],
    cert: Mapping[str, Any] | None = None,
    *,
    max_latency_ms: float = DEFAULT_MAX_LATENCY_MS,
    min_cert_days: float = DEFAULT_MIN_CERT_DAYS,
    critical_cert_days: float = DEFAULT_CRITICAL_CERT_DAYS,
    expect_health: bool = True,
) -> list[dict[str, str]]:
    """把探活与证书结果变成告警；纯函数，便于测试。"""
    alerts: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        alerts.append({'level': level, 'code': code, 'message': message})

    if not probe.get('ok'):
        status = probe.get('status')
        reason = f'HTTP {status}' if status is not None else str(probe.get('error') or 'unknown')
        add('critical', 'uptime_unreachable', f'站点探活失败（{reason}）。')
    else:
        health = probe.get('health')
        if isinstance(health, str) and health.lower() != 'ok':
            add('critical', 'health_degraded', f'健康检查返回 {health}。')
        elif expect_health and probe.get('health_error'):
            add('warning', 'health_unparsed',
                f'健康检查响应无法识别（{probe.get("health_error")}），确认 UPTIME_URL 指向 /api/health。')
        try:
            latency = float(probe.get('latency_ms') or 0)
        except (TypeError, ValueError):
            latency = 0.0
        if max_latency_ms > 0 and latency > max_latency_ms:
            add('warning', 'latency_high', f'响应 {latency:.0f} ms，高于阈值 {max_latency_ms:.0f} ms。')

    if not cert or not cert.get('checked'):
        return alerts
    if cert.get('valid') is False:
        add('critical', 'tls_invalid', f'TLS 证书校验失败（{cert.get("error") or "unknown"}）。')
        return alerts
    days_left = cert.get('days_left')
    try:
        remaining = float(days_left)
    except (TypeError, ValueError):
        return alerts
    if critical_cert_days > 0 and remaining <= critical_cert_days:
        add('critical', 'tls_expiring_critical', f'TLS 证书仅剩 {remaining:.1f} 天。')
    elif min_cert_days > 0 and remaining <= min_cert_days:
        add('warning', 'tls_expiring', f'TLS 证书剩余 {remaining:.1f} 天，低于阈值 {min_cert_days:.0f} 天。')
    return alerts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='外部可用性与 TLS 证书到期检查')
    parser.add_argument('--env-file', default=str(PROJECT_ROOT / '.env'), help='读取环境变量（默认项目根 .env）')
    parser.add_argument('--url', default=None, help='默认取 UPTIME_URL；建议填 https://域名/api/health')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT, help='HTTP/TLS 超时秒数')
    parser.add_argument('--max-latency-ms', type=float, default=DEFAULT_MAX_LATENCY_MS,
                        help='延迟告警阈值（毫秒；0 表示关闭）')
    parser.add_argument('--min-cert-days', type=float, default=DEFAULT_MIN_CERT_DAYS,
                        help='证书剩余天数警告阈值（0 表示关闭）')
    parser.add_argument('--critical-cert-days', type=float, default=DEFAULT_CRITICAL_CERT_DAYS,
                        help='证书剩余天数严重阈值（0 表示关闭）')
    parser.add_argument('--no-cert', action='store_true', help='跳过 TLS 证书检查')
    parser.add_argument('--no-health', action='store_true', help='不要求响应是健康检查 JSON（用于任意页面拨测）')
    parser.add_argument('--webhook-url', default=None, help='默认取 ALERT_WEBHOOK_URL；留空只打印')
    parser.add_argument('--webhook-type', default=None,
                        choices=('generic', 'dingtalk', 'feishu', 'slack'),
                        help='默认取 ALERT_WEBHOOK_TYPE，缺省 generic')
    parser.add_argument('--instance', default=None, help='默认取 ALERT_INSTANCE，可写部署名')
    parser.add_argument('--json', action='store_true', help='以 JSON 输出，便于日志采集')
    parser.add_argument('--dry-run', action='store_true', help='只评估，不发送 webhook')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_env_file(args.env_file)

    url = (args.url or os.environ.get('UPTIME_URL') or '').strip()
    webhook_url = (args.webhook_url or os.environ.get('ALERT_WEBHOOK_URL') or '').strip()
    webhook_type = (args.webhook_type or os.environ.get('ALERT_WEBHOOK_TYPE') or 'generic').strip().lower()
    instance = (args.instance or os.environ.get('ALERT_INSTANCE') or '').strip()

    if not url:
        print('缺少探活 URL：设置 UPTIME_URL 或用 --url 传入。', file=sys.stderr)
        return 2
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        print('探活 URL 必须是带主机名的 http(s)。', file=sys.stderr)
        return 2
    try:
        parts.port
    except ValueError:
        print('探活 URL 的端口不合法。', file=sys.stderr)
        return 2
    if webhook_type not in ('generic', 'dingtalk', 'feishu', 'slack'):
        print(f'不支持的 webhook 类型：{webhook_type}', file=sys.stderr)
        return 2

    probe = probe_http(url, timeout=args.timeout)
    cert = None if args.no_cert else check_certificate(url, timeout=args.timeout)
    alerts = evaluate(
        probe,
        cert,
        max_latency_ms=args.max_latency_ms,
        min_cert_days=args.min_cert_days,
        critical_cert_days=args.critical_cert_days,
        expect_health=not args.no_health,
    )

    if args.json:
        print(json.dumps({'alerts': alerts, 'probe': probe, 'cert': cert}, ensure_ascii=False))
    else:
        print(format_text(alerts, instance=instance))
        print(f"probe: status={probe.get('status')} latency={probe.get('latency_ms')}ms health={probe.get('health')}", file=sys.stderr)
        if cert and cert.get('checked'):
            print(f"cert: valid={cert.get('valid')} days_left={cert.get('days_left')}", file=sys.stderr)

    if not alerts:
        return 0
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
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
