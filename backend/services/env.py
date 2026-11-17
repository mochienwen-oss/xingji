"""环境变量解析：非法配置只告警并回落到默认值，不让进程在 import 阶段直接崩。

部署时一个拼错/漏填的数字变量不应导致整个 API 起不来；真正的必填项（数据库 URL、
密钥）仍由各自模块显式校验并给出可操作错误。
"""
from __future__ import annotations

import logging
import math
import os

log = logging.getLogger(__name__)


def _raw(name: str) -> str:
    return (os.getenv(name) or '').strip()


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        log.warning('%s=%r 不是整数，使用默认值 %s', name, raw, default)
        return default
    if minimum is not None and value < minimum:
        log.warning('%s=%r 小于最小值 %s，按 %s 处理', name, raw, minimum, minimum)
        return minimum
    return value


def env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        log.warning('%s=%r 不是数字，使用默认值 %s', name, raw, default)
        return default
    if not math.isfinite(value):
        log.warning('%s=%r 不是有限数字，使用默认值 %s', name, raw, default)
        return default
    if minimum is not None and value < minimum:
        log.warning('%s=%r 小于最小值 %s，按 %s 处理', name, raw, minimum, minimum)
        return minimum
    return value
