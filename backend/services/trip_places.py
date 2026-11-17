from copy import deepcopy
from . import amap
from .errors import ServiceError


def stops(data: dict):
    for day in data.get('days', []):
        yield from day.get('stops', [])
    yield from data.get('backlog', [])


def for_storage(data: dict, original: dict | None = None) -> dict:
    """Keep legacy snapshots unchanged; new selections contain only their ID."""
    saved = deepcopy(data)
    legacy = {s['place']['id']: s['place'] for s in stops(original or {})
              if set(s.get('place', {})) - {'id'}}
    for stop in stops(saved):
        pid = stop['place']['id']
        stop['place'] = deepcopy(legacy.get(pid, {'id': pid}))
    saved.pop('place_notice', None)
    return saved


async def refresh(data: dict) -> dict:
    result = deepcopy(data)
    items = list(stops(result))
    ids = list(dict.fromkeys(s['place']['id'] for s in items))
    try:
        places = await amap.find_places(ids)
    except ServiceError:
        places = {}
    missing = False
    for stop in items:
        pid = stop['place']['id']
        place = places.get(pid)
        if place is None:
            missing = True
            place = {'id': pid, 'name': '地点信息暂不可用', 'address': '', 'location': '',
                     'opentime': '', 'cost': '', 'source_time': '', 'photos': [], 'unavailable': True,
                     'verification': {'status': 'unavailable', 'source': 'amap', 'checked_at': '',
                                      'opening_hours': False}}
        stop['place'] = place
    if missing:
        result['place_notice'] = '部分地点暂时无法从高德获取，请稍后重新打开行程。地点顺序和用户填写的内容仍已保留。'
    return result
