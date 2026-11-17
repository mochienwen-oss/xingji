"""B7：匿名日配额计数、限额读取、路径映射与登录豁免。"""
from backend.services import planning, quota
from backend.services.harness import orchestrator
from tests.conftest import login

CHAT = {'messages': [{'role': 'user', 'content': '帮我规划杭州两日游'}]}


def test_hit_allows_until_limit_then_blocks(monkeypatch):
    monkeypatch.setenv('ANON_LLM_DAILY', '2')
    assert quota.hit('llm', '1.2.3.4') is True
    assert quota.hit('llm', '1.2.3.4') is True
    assert quota.hit('llm', '1.2.3.4') is False
    # 计数按 IP 隔离：另一个匿名来源仍有自己的额度
    assert quota.hit('llm', '5.6.7.8') is True


def test_counter_resets_on_next_utc_day(monkeypatch):
    monkeypatch.setenv('ANON_LLM_DAILY', '2')
    monkeypatch.setattr(quota, '_today', lambda: '2026-11-06')
    assert quota.hit('llm', 'ip') is True
    assert quota.hit('llm', 'ip') is True
    assert quota.hit('llm', 'ip') is False
    monkeypatch.setattr(quota, '_today', lambda: '2026-11-07')
    assert quota.hit('llm', 'ip') is True


def test_zero_limit_disables_quota(monkeypatch):
    monkeypatch.setenv('ANON_AMAP_DAILY', '0')
    assert quota.limit('amap') == 0
    assert all(quota.hit('amap', 'ip') is True for _ in range(35))
    assert quota._buckets == {}


def test_limit_reads_env_and_falls_back_on_bad_values(monkeypatch):
    monkeypatch.delenv('ANON_LLM_DAILY', raising=False)
    monkeypatch.delenv('ANON_AMAP_DAILY', raising=False)
    assert quota.limit('llm') == 30
    assert quota.limit('amap') == 300
    monkeypatch.setenv('ANON_LLM_DAILY', '7')
    assert quota.limit('llm') == 7
    for raw in ['abc', '-1', '3.5', ' ', 'None']:
        monkeypatch.setenv('ANON_LLM_DAILY', raw)
        assert quota.limit('llm') == 30


def test_reset_clears_counters(monkeypatch):
    monkeypatch.setenv('ANON_LLM_DAILY', '1')
    assert quota.hit('llm', 'ip') is True
    assert quota.hit('llm', 'ip') is False
    quota.reset()
    assert quota._buckets == {}
    assert quota.hit('llm', 'ip') is True


def test_max_buckets_prunes_old_date_buckets(monkeypatch):
    monkeypatch.setattr(quota, '_MAX_BUCKETS', 2)
    monkeypatch.setattr(quota, '_today', lambda: '2026-11-06')
    quota._buckets[('llm', 'old', '2026-11-01')] = 1
    quota._buckets[('llm', 'recent', '2026-11-06')] = 1
    assert quota.hit('llm', 'new') is True
    assert ('llm', 'old', '2026-11-01') not in quota._buckets
    assert ('llm', 'recent', '2026-11-06') in quota._buckets
    assert ('llm', 'new', '2026-11-06') in quota._buckets


def test_max_buckets_evicts_active_buckets(monkeypatch):
    """全是当天桶时也要有硬上限：按插入顺序淘汰，而不是无限增长。"""
    quota.reset()
    monkeypatch.setattr(quota, '_MAX_BUCKETS', 2)
    monkeypatch.setattr(quota, '_today', lambda: '2026-11-06')
    assert quota.hit('llm', 'first') is True
    assert quota.hit('llm', 'second') is True
    assert quota.hit('llm', 'third') is True
    assert len(quota._buckets) == 2
    assert ('llm', 'first', '2026-11-06') not in quota._buckets
    assert ('llm', 'third', '2026-11-06') in quota._buckets


def test_scope_for_path_maps_only_expensive_anonymous_endpoints():
    for path in ['/api/planning/preview', '/api/planning/chat', '/api/planning/chat/stream',
                 '/api/planning/session/stream', '/api/planning/preview/assistant/stream']:
        assert quota.scope_for_path(path) == 'llm'
    for path in ['/api/places', '/api/places/details', '/api/discover/nearby',
                 '/api/discover/city-center', '/api/inspiration']:
        assert quota.scope_for_path(path) == 'amap'
    for path in ['/api/health', '/api/account/password/forgot', '/api/inspiration/themes',
                 '/api/trips/12/nearby', '/api/planning/chat/extra', '/api/places/extra']:
        assert quota.scope_for_path(path) is None


def test_logged_in_requests_are_not_counted(client, monkeypatch):
    c, _ = client
    calls = []

    async def fake_chat(messages, current, on_reply=None):
        calls.append(messages)
        return {'reply': '好的', 'updates': {}}

    monkeypatch.setattr(planning, 'planning_chat', fake_chat)
    monkeypatch.setenv('ANON_LLM_DAILY', '1')
    assert login(c).status_code == 200
    assert [c.post('/api/planning/chat', json=CHAT).status_code for _ in range(2)] == [200, 200]
    assert len(calls) == 2
    assert quota._buckets == {}


def test_session_stream_consumes_anonymous_llm_quota(client, monkeypatch):
    """P1-1：探索页主生成端点必须计入匿名每日 LLM 配额，用完返回配额 429。"""
    c, _ = client

    async def fake_run_turn(body, user, emit):
        await emit({'kind': 'done', 'reply': '好的', 'failed': False})

    monkeypatch.setattr(orchestrator, 'run_turn', fake_run_turn)
    monkeypatch.setenv('ANON_LLM_DAILY', '1')
    turn = {'mode': 'explore', 'message': '帮我规划杭州两日游', 'messages': [], 'places': []}
    assert c.post('/api/planning/session/stream', json=turn).status_code == 200
    blocked = c.post('/api/planning/session/stream', json=turn)
    assert blocked.status_code == 429
    assert blocked.json()['detail'] == '今天的免费体验次数已用完，请登录后继续。'
    assert blocked.headers['Retry-After'] == '3600'
    assert sum(quota._buckets.values()) == 1
