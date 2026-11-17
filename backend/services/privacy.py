"""公开行程脱敏：只用于「公开到灵感广场」的读与复制，不影响只读分享链接。

行踪轨迹属于敏感个人信息。广场是匿名可读的公开面，因此：
- 不暴露具体出发日期（公开卡只显示天数）；
- 住宿类地点的精确地址替换为城市级占位，名称保留以便理解行程；
- AI 对话整体清空（对话里常有同行人姓名、预算、身体限制等）。
只读分享链接（仅链接可见）仍返回完整行程给持链接的同行者。
"""
from __future__ import annotations

from copy import deepcopy

# 高德 POI 没有统一的住宿类型字段，这里按名称做保守识别；误判的代价只是地址变粗。
LODGING_HINTS = (
    '酒店', '宾馆', '民宿', '旅馆', '客栈', '青旅', '青年旅舍',
    '招待所', '度假村', '公寓', '住宿',
)

REDACTED_ADDRESS = '（具体地址不公开）'


def is_lodging_place(place: dict | None) -> bool:
    if not isinstance(place, dict):
        return False
    name = str(place.get('name') or '')
    return any(hint in name for hint in LODGING_HINTS)


def _redact_places(stops: list, city: str) -> None:
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        place = stop.get('place')
        if not is_lodging_place(place):
            continue
        place_city = str(place.get('city') or city or '').strip()
        place['address'] = f'{place_city}{REDACTED_ADDRESS}' if place_city else REDACTED_ADDRESS


def redact_public_trip(data: dict) -> dict:
    """返回脱敏后的深拷贝，调用方原来的 data 不变。"""
    redacted = deepcopy(data) if isinstance(data, dict) else {}
    request = redacted.get('request')
    city = ''
    if isinstance(request, dict):
        request['start_date'] = None
        city = str(request.get('city') or '')
    days = redacted.get('days')
    if isinstance(days, list):
        for day in days:
            if isinstance(day, dict) and isinstance(day.get('stops'), list):
                _redact_places(day['stops'], city)
    backlog = redacted.get('backlog')
    if isinstance(backlog, list):
        _redact_places(backlog, city)
    redacted['conversation'] = []
    return redacted
