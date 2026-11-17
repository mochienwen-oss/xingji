"""进程内轻量指标：给上线首周的外部探针和告警提供一个稳定的读口。

这里不替代 Sentry：异常堆栈仍由 logger.exception 落到本机日志，外部错误聚合服务
负责聚合。本模块只回答“现在是否可用、错误率多高、哪个接口在慢”，并刻意保持无依赖：
不引入 prometheus_client、psutil 或后台线程。单 worker 的进程内计数在重启后清零，
这是可接受的；需要跨进程历史时应接外部时序库。
"""
from __future__ import annotations

import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone

_lock = threading.Lock()
_started_at = time.time()
_requests_total = 0
_requests_by_status: Counter[str] = Counter()
_requests_by_path: Counter[str] = Counter()
_errors_total = 0
_errors_by_kind: Counter[str] = Counter()
_latency_ms_total = 0.0
_latency_count = 0
_latency_max_ms = 0.0
_emails_by_outcome: Counter[str] = Counter()

# 路径里的数字 id、分享/邀请 token 都是高基数字段：不归一化会把指标表撑爆。
_NUMERIC_SEGMENT = re.compile(r'^\d+$')
_MAX_PATH_KEYS = 200


def redact_path(path: str) -> str:
    """只脱敏路径里的访问凭据，保留数字 id 便于排障。

    /s/<token> 是分享落地页，token 本身就是读取权限；原样写进访问日志会让
    任何能看日志的人拿到可访问链接。/api/shares/<token>、/api/invites/<token>
    同理。数字 id 不敏感，保留它访问日志才可读。
    """
    path = path or '/'
    parts = path.split('/')
    if len(parts) >= 4 and parts[1] == 'api' and parts[2] in ('shares', 'invites'):
        parts[3] = '{token}'
    elif len(parts) >= 3 and parts[1] == 's':
        parts[2] = '{token}'
    return '/'.join(parts) or '/'


def normalize_path(path: str) -> str:
    """把动态路径压成有限集合，避免用户可控字符串成为指标标签。"""
    parts = redact_path(path).split('/')
    for index, part in enumerate(parts):
        if _NUMERIC_SEGMENT.fullmatch(part):
            parts[index] = '{id}'
    return '/'.join(parts) or '/'


def observe_request(method: str, path: str, status: int, seconds: float) -> None:
    """一次 HTTP 请求结束后调用；由 ASGI 中间件在最外层记录，能覆盖 429 与 5xx。"""
    global _requests_total, _latency_ms_total, _latency_count, _latency_max_ms
    key = normalize_path(path)
    elapsed_ms = max(0.0, float(seconds) * 1000.0)
    with _lock:
        _requests_total += 1
        _requests_by_status[str(status)] += 1
        if key not in _requests_by_path and len(_requests_by_path) >= _MAX_PATH_KEYS:
            key = '{other}'
        _requests_by_path[key] += 1
        _latency_ms_total += elapsed_ms
        _latency_count += 1
        if elapsed_ms > _latency_max_ms:
            _latency_max_ms = elapsed_ms


def observe_email(outcome: str) -> None:
    """记录一次事务邮件结果：sent / failed / unconfigured。

    邮件是注册、找回密码的第一公里；没有 SMTP 或发信失败时，产品会静默
    降级成「注册成功但收不到信」。计数器让 /api/metrics 能直接暴露这一点。
    """
    with _lock:
        _emails_by_outcome[(outcome or 'unknown')[:20]] += 1


def record_error(kind: str) -> None:
    """记录错误类别（database_busy / pool_timeout / unhandled / upstream）。"""
    global _errors_total
    with _lock:
        _errors_total += 1
        _errors_by_kind[(kind or 'unknown')[:40]] += 1


def snapshot() -> dict:
    """只读快照；不查数据库、不读磁盘，端点再补健康探测。"""
    with _lock:
        total = _requests_total
        latency_count = _latency_count
        return {
            'started_at': datetime.fromtimestamp(_started_at, tz=timezone.utc).isoformat(),
            'uptime_seconds': int(max(0, time.time() - _started_at)),
            'requests': {
                'total': total,
                'by_status': dict(_requests_by_status),
                'by_path': dict(_requests_by_path),
            },
            'errors': {'total': _errors_total, 'by_kind': dict(_errors_by_kind)},
            'email': {'total': sum(_emails_by_outcome.values()), 'by_outcome': dict(_emails_by_outcome)},
            'latency_ms': {
                'count': latency_count,
                'avg': round(_latency_ms_total / latency_count, 2) if latency_count else 0,
                'max': round(_latency_max_ms, 2),
            },
        }


def reset() -> None:
    """测试用：清空进程内计数，不重置 started_at（启动时间仍代表进程）。"""
    global _requests_total, _errors_total, _latency_ms_total, _latency_count, _latency_max_ms
    with _lock:
        _requests_total = 0
        _requests_by_status.clear()
        _requests_by_path.clear()
        _errors_total = 0
        _errors_by_kind.clear()
        _latency_ms_total = 0.0
        _latency_count = 0
        _latency_max_ms = 0.0
        _emails_by_outcome.clear()
