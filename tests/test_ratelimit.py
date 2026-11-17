"""P0：匿名端点令牌桶限流（进程内，按客户端 IP）。"""
import re

from backend.services import ratelimit
from backend.services.harness import orchestrator
from tests.conftest import login

PLACES = {'city': '杭州', 'q': '景点'}


def _tiny_rules(monkeypatch, budget=2):
    """把规则换成只剩 /api/places、容量 2、几乎不补充，便于快速打出 429。"""
    monkeypatch.setattr(ratelimit, 'RULES', [ratelimit.Rule(re.compile(r'^/api/places$'), budget, 0.001)])


def test_bucket_map_evicts_oldest_when_all_active(monkeypatch):
    """被限流的分支同样要参与清理：字典在达到上限后必须强制淘汰，不能无界增长。"""
    ratelimit.reset()
    _tiny_rules(monkeypatch, budget=1)
    monkeypatch.setattr(ratelimit, '_MAX_BUCKETS', 2)
    for key in ('a', 'b', 'c'):
        ratelimit.check('/api/places', key)
    assert len(ratelimit._buckets) == 2
    ratelimit.reset()


def test_places_returns_429_with_retry_after(client, monkeypatch):
    c, _ = client
    ratelimit.reset()
    _tiny_rules(monkeypatch)
    assert [c.get('/api/places', params=PLACES).status_code for _ in range(2)] == [200, 200]
    blocked = c.get('/api/places', params=PLACES)
    assert blocked.status_code == 429
    body = blocked.json()
    assert set(body) == {'detail'}
    assert body['detail'].startswith('操作太频繁，请')
    assert int(blocked.headers['Retry-After']) >= 1
    # reset 之后立即恢复
    ratelimit.reset()
    assert c.get('/api/places', params=PLACES).status_code == 200


def test_unmatched_paths_are_not_limited(client, monkeypatch):
    c, _ = client
    _tiny_rules(monkeypatch, budget=1)
    login(c)
    assert [c.get('/api/me').status_code for _ in range(5)] == [200] * 5


def test_disabled_by_env(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('RATE_LIMIT_DISABLED', '1')
    _tiny_rules(monkeypatch, budget=1)
    assert [c.get('/api/places', params=PLACES).status_code for _ in range(3)] == [200] * 3


def test_session_stream_returns_429_when_burst_exceeded(client, monkeypatch):
    """P1-1：探索页主生成端点必须受限流保护，超速返回 429 + Retry-After。"""
    c, _ = client
    ratelimit.reset()

    async def fake_run_turn(body, user, emit):
        await emit({'kind': 'done', 'reply': '好的', 'failed': False})

    monkeypatch.setattr(orchestrator, 'run_turn', fake_run_turn)
    monkeypatch.setattr(ratelimit, 'RULES', [
        ratelimit.Rule(re.compile(r'^/api/planning/session/stream$'), 2, 0.001),
    ])
    turn = {'mode': 'explore', 'message': '帮我规划杭州两日游', 'messages': [], 'places': []}
    assert [c.post('/api/planning/session/stream', json=turn).status_code for _ in range(2)] == [200, 200]
    blocked = c.post('/api/planning/session/stream', json=turn)
    assert blocked.status_code == 429
    assert blocked.json()['detail'].startswith('操作太频繁，请')
    assert int(blocked.headers['Retry-After']) >= 1


def test_rules_cover_expensive_endpoints():
    assert ratelimit.match('/api/planning/chat')
    assert ratelimit.match('/api/planning/chat/stream')
    assert ratelimit.match('/api/planning/session/stream')
    assert ratelimit.match('/api/planning/preview')
    assert ratelimit.match('/api/planning/preview/assistant/stream')
    assert ratelimit.match('/api/trips/from-preview')
    assert ratelimit.match('/api/shares/view')
    assert ratelimit.match('/api/shares/fork')
    assert ratelimit.match('/api/plaza/12/fork')
    assert ratelimit.match('/api/login')
    assert ratelimit.match('/api/register')
    assert ratelimit.match('/api/trips/12/assistant')
    assert ratelimit.match('/api/trips/12/assistant/stream')
    assert ratelimit.match('/api/trips/12/guide/outline')
    assert ratelimit.match('/api/trips/12/days/2/optimize')
    assert ratelimit.match('/api/trips/12/budget/estimate')
    assert ratelimit.match('/api/inspiration')
    assert ratelimit.match('/api/trips')
    assert ratelimit.match('/api/trips/12')
    assert ratelimit.match('/api/trips/12/days/0/routes')
    # P1-5：真实路由是 /api/trips/{trip_id}/days/{day_index}/nearby，旧规则少一层永远不命中
    assert ratelimit.match('/api/trips/12/days/0/nearby')
    assert ratelimit.match('/api/trips/12/nearby') is None
    assert ratelimit.match('/api/places')
    assert ratelimit.match('/api/discover/nearby')
    # 协作轮询使用轻量版本端点，不能被限流规则误伤
    assert ratelimit.match('/api/trips/12/version') is None
    assert ratelimit.match('/api/trips/shared') is not None
    # 分享/邀请/可见性/恢复/成员/支出/分享令牌/导出都有独立规则，避免匿名刷全量读或外部缓存。
    assert ratelimit.match('/api/trips/12/join-code') is not None
    assert ratelimit.match('/api/trips/12/visibility') is not None
    assert ratelimit.match('/api/trips/12/restore') is not None
    assert ratelimit.match('/api/trips/12/share') is not None
    assert ratelimit.match('/api/trips/12/collaborators') is not None
    assert ratelimit.match('/api/trips/12/expenses') is not None
    assert ratelimit.match('/api/shares/abc123') is not None
    assert ratelimit.match('/api/account/export') is not None
    assert ratelimit.match('/api/me') is None


def test_rules_cover_account_and_trip_write_endpoints():
    assert ratelimit.match('/api/collaborators/accept') is not None
    assert ratelimit.match('/api/trips/12/days') is not None
    assert ratelimit.match('/api/trips/12/guide') is not None
    assert ratelimit.match('/api/trips/12/budget') is not None
    assert ratelimit.match('/api/plaza') is not None
    # 版本轮询仍然轻量豁免
    assert ratelimit.match('/api/trips/12/version') is None
