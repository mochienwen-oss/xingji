"""回归测试：地图超时/传输错误时，路线优化必须给可读提示并保持原行程。

需求依据（README.md）：
- 第 89 行：路线优化会比较地图的预计交通耗时，并避免新增固定事项冲突。
  拿不到真实耗时时不能假装能比较，也不能给出一条基于估算的"更优路线"。
- 第 108 行：缺失时显示未知，路线查询失败不会用直线代替。

既有行为契约：路段耗时缺失时抛 ServiceError『部分路段无法获取交通时间，无法比较路线，
原行程未改变。』（见 tests/test_routes.py:37），端点在 main.py 的 ServiceError 处理器下返回
503 + 该文案。

本次 0.3.0 并发重构给 route_opt 加了 asyncio.timeout(amap.AMAP_TASK_TIMEOUT_SECONDS)，
却没有像 amap.update_routes（tests/test_amap_resilience.py:69）那样捕获 TimeoutError，
于是超时从 asyncio.gather 漏到全局异常处理器，用户看到 500『服务暂时不可用』。
"""
import asyncio
import copy

import httpx
import pytest

from backend.services import amap, route_opt
from backend.services.errors import ServiceError
from tests.conftest import login


def make_day():
    """a→c→b 三个地点：最近邻候选会排成 a→b→c，确保真的进入路线查询分支。"""
    def stop(pid, lon):
        return {'place': {'id': pid, 'name': pid, 'location': f'{lon},30.0'}, 'duration': 60}

    return {'stops': [stop('a', 120.0), stop('c', 120.3), stop('b', 120.1)],
            'routes': [], 'start_time': '09:00', 'end_time': '18:00'}


@pytest.mark.anyio
async def test_route_timeout_falls_back_to_readable_service_error(monkeypatch):
    """单段查询超时不是 500：按"路段不可用"处理，行程不变。"""
    async def hang(a, b, mode, city):
        await asyncio.sleep(5)

    monkeypatch.setattr(amap, 'route_between', hang)
    monkeypatch.setattr(amap, 'AMAP_TASK_TIMEOUT_SECONDS', 0.01)
    with pytest.raises(ServiceError, match='无法比较路线'):
        await route_opt.suggest_route(make_day(), 'walking', '桂林')


@pytest.mark.anyio
async def test_route_transport_error_falls_back_to_readable_service_error(monkeypatch):
    """连接失败等传输错误同样只让路段不可用，不把底层异常漏给用户。"""
    async def boom(a, b, mode, city):
        raise httpx.ConnectError('connection failed')

    monkeypatch.setattr(amap, 'route_between', boom)
    with pytest.raises(ServiceError, match='无法比较路线'):
        await route_opt.suggest_route(make_day(), 'walking', '桂林')


def test_optimize_endpoint_degrades_instead_of_500(client, monkeypatch):
    """完整流程：保存一天行程 → 优化 → 高德超时。必须 503 + 可读提示，行程原样保留。"""
    c, places = client
    assert login(c).status_code == 200
    created = c.post('/api/trips', json={'city': '桂林', 'days': 1}).json()
    days = copy.deepcopy(created['days'])
    # 顺序 1,3,2：最近邻候选是 1,2,3，优化请求才会真正去查路段。
    days[0]['stops'] = [{'place': place, 'duration': 60, 'reason': ''}
                        for place in (places[0], places[2], places[1])]
    days[0]['start_time'] = '09:00'
    days[0]['end_time'] = '18:00'
    saved = c.put(f"/api/trips/{created['id']}/days",
                  json={'days': days, 'version': created['version']})
    assert saved.status_code == 200, saved.text
    version = saved.json()['version']

    async def hang(a, b, mode, city):
        await asyncio.sleep(5)

    monkeypatch.setattr(amap, 'route_between', hang)
    monkeypatch.setattr(amap, 'AMAP_TASK_TIMEOUT_SECONDS', 0.01)
    response = c.post(f"/api/trips/{created['id']}/days/0/optimize")
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == '部分路段无法获取交通时间，无法比较路线，原行程未改变。'

    # 优化只是建议：失败时服务端行程与版本都不能变。
    seen = c.get(f"/api/trips/{created['id']}").json()
    assert seen['version'] == version
    assert [stop['place']['id'] for stop in seen['days'][0]['stops']] == ['1', '3', '2']
