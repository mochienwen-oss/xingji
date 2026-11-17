"""B7：匿名 LLM/Amap 日配额在中间件生效，登录用户不受影响。

B10 追加：账户端点（验邮箱/改邮箱/改密/注销/条款）的令牌桶与路径精确匹配。
"""
import pytest

from backend.services import planning, quota, ratelimit
from tests.conftest import login

CHAT = {'messages': [{'role': 'user', 'content': '帮我规划杭州两日游'}]}
DETAIL = '今天的免费体验次数已用完，请登录后继续。'


def _install_fake_chat(monkeypatch):
    calls = []

    async def fake_chat(messages, current, on_reply=None):
        calls.append(messages)
        return {'reply': '可以，杭州两日游安排如下。', 'updates': {}}

    monkeypatch.setattr(planning, 'planning_chat', fake_chat)
    return calls


def test_anonymous_llm_quota_blocks_second_request(client, monkeypatch):
    c, _ = client
    calls = _install_fake_chat(monkeypatch)
    monkeypatch.setenv('ANON_LLM_DAILY', '1')
    first = c.post('/api/planning/chat', json=CHAT)
    assert first.status_code == 200
    assert first.json()['reply'] == '可以，杭州两日游安排如下。'
    blocked = c.post('/api/planning/chat', json=CHAT)
    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '3600'
    assert blocked.json() == {'detail': DETAIL}
    # 配额拦截发生在进入端点之前，模型不会被再次调用
    assert len(calls) == 1


def test_logged_in_user_bypasses_anonymous_quota(client, monkeypatch):
    c, _ = client
    calls = _install_fake_chat(monkeypatch)
    monkeypatch.setenv('ANON_LLM_DAILY', '1')
    assert login(c).status_code == 200
    assert [c.post('/api/planning/chat', json=CHAT).status_code for _ in range(3)] == [200] * 3
    assert len(calls) == 3
    assert quota._buckets == {}


def test_anonymous_amap_quota_blocks_second_request(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('ANON_AMAP_DAILY', '1')
    params = {'city': '杭州', 'q': '景点'}
    assert c.get('/api/places', params=params).status_code == 200
    blocked = c.get('/api/places', params=params)
    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '3600'
    assert blocked.json() == {'detail': DETAIL}
# --- B10：账户端点限流（精确锚定路径，容量按发信/改密成本收紧）---

ACCOUNT_RULES = {
    '/api/account/verify-email': (20, 1 / 10),
    '/api/account/email': (10, 1 / 30),
    '/api/account/email/resend': (5, 1 / 60),
    '/api/account/password/forgot': (5, 1 / 60),
    '/api/account/password/reset': (10, 1 / 30),
    '/api/account/password': (10, 1 / 30),
    '/api/account/terms': (10, 1 / 30),
    '/api/account': (10, 1 / 30),
}


def test_account_rules_are_exact_and_ordered():
    """每条账户规则都必须完整锚定，不能用前缀把相邻路径吃掉。"""
    for path, (capacity, rate) in ACCOUNT_RULES.items():
        rule = ratelimit.match(path)
        assert rule is not None, path
        assert rule.pattern.pattern == '^' + path + '$', path
        assert rule.capacity == capacity, path
        assert rule.rate == pytest.approx(rate), path
    # forgot/reset 有自己的规则，不能被 /api/account/password 抢先命中。
    assert ratelimit.match('/api/account/password/forgot').pattern.pattern == r'^/api/account/password/forgot$'
    assert ratelimit.match('/api/account/password/reset').pattern.pattern == r'^/api/account/password/reset$'
    # 未注册的账户子路径不应被兜底限流（避免误伤未来的只读接口）。
    assert ratelimit.match('/api/account/password/hint') is None
    assert ratelimit.match('/api/account/unknown') is None


def test_forgot_password_uses_its_own_five_token_bucket(client):
    """forgot 容量 5：第 6 次即 429；若误命中 password 规则(10)则不会触发。"""
    c, _ = client
    for _ in range(5):
        assert c.post('/api/account/password/forgot',
                      json={'identifier': 'ghost'}).status_code == 200

    blocked = c.post('/api/account/password/forgot', json={'identifier': 'ghost'})

    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '60'
    assert blocked.json() == {'detail': '操作太频繁，请 60 秒后重试'}
    # 独立桶：forgot 被限流不影响同一 IP 的改密接口。
    assert login(c).status_code == 200
    changed = c.post('/api/account/password',
                     json={'current_password': 'wrong-password', 'new_password': 'password9'})
    assert changed.status_code == 401


def test_verify_email_limited_to_twenty(client):
    c, _ = client
    payload = {'token': 'not-a-real-token'}
    assert [c.post('/api/account/verify-email', json=payload).status_code
            for _ in range(20)] == [400] * 20

    blocked = c.post('/api/account/verify-email', json=payload)

    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '10'


def test_change_password_limited_to_ten(client):
    c, _ = client
    login(c)
    payload = {'current_password': 'wrong-password', 'new_password': 'password9'}
    assert [c.post('/api/account/password', json=payload).status_code
            for _ in range(10)] == [401] * 10

    blocked = c.post('/api/account/password', json=payload)

    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '30'


def test_delete_account_shares_account_bucket(client):
    """DELETE /api/account 没有子路径，靠 ^/api/account$ 兜住注销。"""
    c, _ = client
    login(c)
    payload = {'password': 'wrong-password', 'confirm': '注销'}
    for _ in range(10):
        resp = c.request('DELETE', '/api/account', json=payload)
        assert resp.status_code == 401, resp.text

    blocked = c.request('DELETE', '/api/account', json=payload)

    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '30'


def test_terms_limited_to_ten(client):
    c, _ = client
    login(c)
    assert [c.post('/api/account/terms').status_code for _ in range(10)] == [200] * 10

    blocked = c.post('/api/account/terms')

    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '30'

