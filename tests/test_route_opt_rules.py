"""需求：README.md:89 路线优化会比较地图的预计交通耗时，并避免新增固定事项冲突。

同时钉住 README.md:87 的时间语义：
- 提前到达固定事项计入等待，预计迟到时提示（候选路线新增迟到则拒绝）；
- 每日结束时间早于或等于开始时间时按次日计算；
- 固定事项由用户手动选择是否在次日（fixed_next_day）。
"""
import copy

import pytest

from backend.services import amap, route_opt
from backend.services.errors import ServiceError


def stop(pid, lon, lat, duration=60, **extra):
    data = {'place': {'id': pid, 'name': pid, 'location': f'{lon:.2f},{lat:.2f}'},
            'duration': duration}
    data.update(extra)
    return data


def install_route(monkeypatch, durations, calls=None):
    async def route(a, b, mode, city):
        if calls is not None:
            calls.append((a['id'], b['id'], mode, city))
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode,
                'duration': durations.get((a['id'], b['id'])), 'distance': None,
                'polyline': [], 'source_time': 't'}
    monkeypatch.setattr(amap, 'route_between', route)


@pytest.mark.anyio
async def test_suggests_faster_route_and_keeps_day_untouched(monkeypatch):
    stops = [
        stop('a', 120.00, 30.00, 90),
        stop('b', 120.30, 30.00, 60),
        stop('c', 120.05, 30.00, 45),
        stop('d', 120.25, 30.00, 30),
    ]
    day = {'stops': stops, 'routes': [], 'start_time': '09:00', 'end_time': '18:00'}
    snapshot = copy.deepcopy(day)
    # 原始 a→b→c→d 预计 140 分钟；最近邻 a→c→d→b 预计 50 分钟。
    durations = {
        ('a', 'b'): 3600, ('b', 'c'): 3000, ('c', 'd'): 1800,
        ('a', 'c'): 600, ('d', 'b'): 600,
    }
    calls = []
    install_route(monkeypatch, durations, calls)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    assert result['improved'] is True
    assert [item['place']['id'] for item in result['day']['stops']] == ['a', 'c', 'd', 'b']
    assert [route['origin'] for route in result['day']['routes']] == ['a', 'c', 'd']
    assert [route['destination'] for route in result['day']['routes']] == ['c', 'd', 'b']
    assert result['message'] == '预计交通时间从 140 分钟减少到 50 分钟，请确认后保存。'
    # 优化只是建议，原 day 不得被修改。
    assert day == snapshot
    # 只会建议；查询用调用方传入的交通方式和城市。
    assert {call[:2] for call in calls} == {('a', 'b'), ('b', 'c'), ('c', 'd'), ('a', 'c'), ('d', 'b')}
    assert all(call[2:] == ('walking', '杭州') for call in calls)


@pytest.mark.anyio
async def test_candidate_not_shortening_keeps_current_order(monkeypatch):
    stops = [stop('a', 120.00, 30.00), stop('b', 120.30, 30.00), stop('c', 120.05, 30.00)]
    day = {'stops': stops, 'routes': []}
    durations = {
        ('a', 'b'): 600, ('b', 'c'): 600,
        ('a', 'c'): 600, ('c', 'b'): 600,
    }
    install_route(monkeypatch, durations)

    result = await route_opt.suggest_route(day, 'driving', '杭州')

    assert result['improved'] is False
    assert result['day'] == day
    assert result['message'] == '候选路线预计用时没有缩短，保留当前顺序。'


@pytest.mark.anyio
async def test_current_order_already_has_no_candidate(monkeypatch):
    stops = [stop('a', 120.00, 30.00), stop('b', 120.10, 30.00), stop('c', 120.20, 30.00)]
    day = {'stops': stops, 'routes': []}
    calls = []
    install_route(monkeypatch, {}, calls)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    assert result['improved'] is False
    assert result['day'] == day
    assert result['message'] == '未找到可比较的其他路线，保留当前顺序。'
    # 顺序没变时不该浪费地图配额。
    assert calls == []


@pytest.mark.anyio
async def test_requires_at_least_three_stops(monkeypatch):
    day = {'stops': [stop('a', 120.00, 30.00), stop('b', 120.10, 30.00)], 'routes': []}
    calls = []
    install_route(monkeypatch, {}, calls)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    assert result['improved'] is False
    assert result['message'] == '至少需要三个地点才能尝试优化。'
    assert calls == []


@pytest.mark.anyio
async def test_fixed_stop_requires_start_time(monkeypatch):
    day = {'stops': [
        stop('a', 120.00, 30.00),
        stop('f', 120.01, 30.00, fixed_time='10:00'),
        stop('b', 120.02, 30.00),
    ], 'routes': []}
    calls = []
    install_route(monkeypatch, {}, calls)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    assert result['improved'] is False
    assert result['message'] == '请先设置当天开始时间，再比较包含固定事项的路线。'
    assert calls == []


@pytest.mark.anyio
async def test_missing_segment_time_refuses_to_compare(monkeypatch):
    stops = [stop('a', 120.00, 30.00), stop('b', 120.30, 30.00), stop('c', 120.05, 30.00)]
    day = {'stops': stops, 'routes': []}
    durations = {
        ('a', 'b'): 600, ('b', 'c'): 600,
        ('a', 'c'): None, ('c', 'b'): 600,
    }
    install_route(monkeypatch, durations)

    with pytest.raises(ServiceError) as info:
        await route_opt.suggest_route(day, 'walking', '杭州')

    assert info.value.status_code == 503
    assert str(info.value) == '部分路段无法获取交通时间，无法比较路线，原行程未改变。'


@pytest.mark.anyio
async def test_rejects_candidate_that_missed_day_end(monkeypatch):
    """候选总耗时更短，但末段更长会把行程拖过结束时间，必须拒绝（等待归一后仍超时）。"""
    stops = [
        stop('a', 120.00, 30.00, 15),
        stop('f', 120.02, 30.00, 60, fixed_time='10:00'),
        stop('b', 120.01, 30.00, 15),
        stop('c', 120.03, 30.00, 15),
    ]
    day = {'stops': stops, 'routes': [], 'start_time': '09:00', 'end_time': '11:33'}
    snapshot = copy.deepcopy(day)
    # 原顺序 a→f→b→c：42 分钟；候选 a→b→f→c：30 分钟，但 f 之后多出的路段把结束时间推过 11:33。
    durations = {
        ('a', 'f'): 2400, ('f', 'b'): 60, ('b', 'c'): 60,
        ('a', 'b'): 300, ('b', 'f'): 300, ('f', 'c'): 1200,
    }
    install_route(monkeypatch, durations)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    assert result['improved'] is False
    assert result['message'] == '候选路线会增加固定事项冲突或超出结束时间，保留当前顺序。'
    assert day == snapshot
    assert [item['place']['id'] for item in result['day']['stops']] == ['a', 'f', 'b', 'c']


@pytest.mark.anyio
async def test_end_before_start_counts_as_next_day(monkeypatch):
    """结束 00:17 ≤ 开始 22:00，按次日 00:17 计算：候选虽更短但仍越过截止时间。"""
    stops = [
        stop('a', 120.00, 30.00, 15),
        stop('f', 120.02, 30.00, 15, fixed_time='23:30'),
        stop('b', 120.01, 30.00, 15),
        stop('c', 120.03, 30.00, 15),
    ]
    day = {'stops': stops, 'routes': [], 'start_time': '22:00', 'end_time': '00:17'}
    durations = {
        ('a', 'f'): 2100, ('f', 'b'): 60, ('b', 'c'): 60,
        ('a', 'b'): 300, ('b', 'f'): 300, ('f', 'c'): 1200,
    }
    install_route(monkeypatch, durations)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    # 原方案 23:30 后 32 分钟结束（次日 00:17），候选 23:30 后 35 分钟（00:20），
    # 次日 00:17 的截止时间因此被越过；若忽略 +1440，截止时间会被误算成当天 00:17，
    # 比较 before_end <= deadline 不成立，错误的候选会被采纳。
    assert result['improved'] is False
    assert result['message'] == '候选路线会增加固定事项冲突或超出结束时间，保留当前顺序。'


@pytest.mark.anyio
async def test_fixed_next_day_flag_avoids_false_conflict(monkeypatch):
    stops = [
        stop('a', 120.00, 30.00, 15),
        stop('f', 120.02, 30.00, 60, fixed_time='10:00', fixed_next_day=True),
        stop('b', 120.01, 30.00, 15),
        stop('c', 120.03, 30.00, 15),
    ]
    day = {'stops': stops, 'routes': [], 'start_time': '09:00', 'end_time': '11:33'}
    durations = {
        ('a', 'f'): 2400, ('f', 'b'): 60, ('b', 'c'): 60,
        ('a', 'b'): 300, ('b', 'f'): 300, ('f', 'c'): 1200,
    }
    install_route(monkeypatch, durations)

    result = await route_opt.suggest_route(day, 'walking', '杭州')

    # 固定事项在次日，等待到次日 10:00；候选交通时间仍更短，不应被判成新增冲突。
    assert result['improved'] is True
    assert result['message'] == '预计交通时间从 42 分钟减少到 30 分钟，请确认后保存。'
    assert [item['place']['id'] for item in result['day']['stops']] == ['a', 'b', 'f', 'c']
