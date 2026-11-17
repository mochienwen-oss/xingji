from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import backend.api.auth as auth_api
from backend.main import app
from backend.services import ratelimit


@pytest.fixture(autouse=True)
def _clear_login_failures():
    """失败计数是进程内状态：每个用例前后清空，避免跨用例/跨文件污染。"""
    auth_api._reset_login_failures()
    yield
    auth_api._reset_login_failures()


def test_login_failure_map_evicts_when_all_entries_active(monkeypatch):
    """全是活跃组合时按最近失败时间淘汰约 10%，保证内存有硬上限。"""
    monkeypatch.setattr(auth_api, '_MAX_LOGIN_FAILURES', 2)
    now = datetime.now(timezone.utc)
    auth_api._LOGIN_FAILURES[('a', 'ip1')] = (1, now - timedelta(seconds=2), None)
    auth_api._LOGIN_FAILURES[('b', 'ip2')] = (1, now - timedelta(seconds=1), None)
    auth_api._prune_login_failures(now)
    assert len(auth_api._LOGIN_FAILURES) == 1
    assert ('a', 'ip1') not in auth_api._LOGIN_FAILURES


def _client_at(ip: str) -> TestClient:
    """同一个 app、不同来源 IP 的客户端；starlette TestClient 原生支持自定义 client 地址。"""
    return TestClient(app, client=(ip, 50000))


def _expire_lock(username: str = 'alice', ip: str = 'testclient') -> None:
    """把 (用户名, IP) 的锁定截止时间改到过去，模拟等待解锁。"""
    key = (username, ip)
    count, last_seen, _locked_until = auth_api._LOGIN_FAILURES[key]
    auth_api._LOGIN_FAILURES[key] = (count, last_seen, datetime.now(timezone.utc) - timedelta(seconds=1))


def test_locks_login_from_same_ip_after_repeated_failures(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(auth_api, 'LOGIN_MAX_FAILURES', 3)
    monkeypatch.setattr(auth_api, 'LOGIN_LOCK_SECONDS', 120)
    monkeypatch.setattr(ratelimit, 'enabled', lambda: False)
    wrong = {'username': 'alice', 'password': 'wrong-password'}

    assert c.post('/api/login', json=wrong).status_code == 401
    assert c.post('/api/login', json=wrong).status_code == 401
    locked = c.post('/api/login', json=wrong)
    assert locked.status_code == 429
    assert locked.headers['retry-after'] == '120'
    assert '锁定' in locked.json()['detail']

    # 锁定期间即使密码正确也拒绝（同一来源 IP），并且不再累加失败次数。
    during = c.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert during.status_code == 429
    assert 0 < int(during.headers['retry-after']) <= 120

    assert auth_api._LOGIN_FAILURES[('alice', 'testclient')][0] == 3
    # 锁定不再写账号行（账号表已不存锁定状态）。

    # 到期后可以正常登录，成功后该 (账号, IP) 计数清零。
    _expire_lock()
    ok = c.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert ok.status_code == 200
    assert ('alice', 'testclient') not in auth_api._LOGIN_FAILURES


def test_success_resets_earlier_failures(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(auth_api, 'LOGIN_MAX_FAILURES', 5)
    monkeypatch.setattr(ratelimit, 'enabled', lambda: False)

    assert c.post('/api/login', json={'username': 'alice', 'password': 'nope'}).status_code == 401
    assert c.post('/api/login', json={'username': 'alice', 'password': 'nope'}).status_code == 401
    assert auth_api._LOGIN_FAILURES[('alice', 'testclient')][0] == 2

    assert c.post('/api/login', json={'username': 'alice', 'password': 'password1'}).status_code == 200
    assert ('alice', 'testclient') not in auth_api._LOGIN_FAILURES


def test_unknown_username_never_gets_locked_or_leaks(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(auth_api, 'LOGIN_MAX_FAILURES', 2)
    monkeypatch.setattr(ratelimit, 'enabled', lambda: False)

    for _ in range(4):
        resp = c.post('/api/login', json={'username': 'ghost', 'password': 'whatever'})
        assert resp.status_code == 401
        assert resp.json()['detail'] == '用户名或密码错误'
    assert ('ghost', 'testclient') not in auth_api._LOGIN_FAILURES


def test_lockout_pins_attacker_ip_not_the_account(client, monkeypatch):
    """DoS 消除：攻击者只能锁住自己来源 IP，受害者从别的 IP 正常登录。"""
    monkeypatch.setattr(auth_api, 'LOGIN_MAX_FAILURES', 3)
    monkeypatch.setattr(auth_api, 'LOGIN_LOCK_SECONDS', 120)
    monkeypatch.setattr(ratelimit, 'enabled', lambda: False)
    attacker = _client_at('203.0.113.7')
    victim = _client_at('198.51.100.8')
    wrong = {'username': 'alice', 'password': 'wrong-password'}

    # 攻击者从 IP-A 连输错密码：只有 (alice, IP-A) 被锁。
    assert attacker.post('/api/login', json=wrong).status_code == 401
    assert attacker.post('/api/login', json=wrong).status_code == 401
    locked = attacker.post('/api/login', json=wrong)
    assert locked.status_code == 429
    assert locked.headers['retry-after'] == '120'

    # 受害者从 IP-B：输错只是普通 401（计数独立从 0 开始），正确密码能正常登录。
    assert victim.post('/api/login', json=wrong).status_code == 401
    ok = victim.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert ok.status_code == 200
    assert ok.json()['username'] == 'alice'

    # 账号行自始至终没有被写锁定状态；IP-B 的计数已被成功登录清掉。
    assert ('alice', '198.51.100.8') not in auth_api._LOGIN_FAILURES

    # IP-A 仍处于锁定：即使拿到正确密码也进不来（429 与 Retry-After 行为不变）。
    still = attacker.post('/api/login', json={'username': 'alice', 'password': 'password1'})
    assert still.status_code == 429
    assert 0 < int(still.headers['retry-after']) <= 120


def test_same_ip_bruteforce_keeps_getting_locked(client, monkeypatch):
    """同 IP 同账号持续爆破：锁定期间持续 429，到期后再失败立即重新锁定整个窗口。"""
    monkeypatch.setattr(auth_api, 'LOGIN_MAX_FAILURES', 3)
    monkeypatch.setattr(auth_api, 'LOGIN_LOCK_SECONDS', 120)
    monkeypatch.setattr(ratelimit, 'enabled', lambda: False)
    attacker = _client_at('203.0.113.7')
    wrong = {'username': 'alice', 'password': 'wrong-password'}

    assert attacker.post('/api/login', json=wrong).status_code == 401
    assert attacker.post('/api/login', json=wrong).status_code == 401
    assert attacker.post('/api/login', json=wrong).status_code == 429

    # 继续爆破：每次都 429，不会放行。
    for _ in range(3):
        again = attacker.post('/api/login', json=wrong)
        assert again.status_code == 429
        assert 0 < int(again.headers['retry-after']) <= 120

    # 解锁后立刻再试一次错密码：计数仍在，马上重新锁定（原有续锁语义）。
    _expire_lock('alice', '203.0.113.7')
    relock = attacker.post('/api/login', json=wrong)
    assert relock.status_code == 429
    assert relock.headers['retry-after'] == '120'
