"""D3 P1 修复回归：邮箱链接失效、SMTP 事务边界、APP_BASE_URL、nearby 限流、
分享页高德缓存/配额、广场匿名可读。

每个用例只钉住审计里确认的契约，不重复 tests/test_account_email.py 已覆盖的细节。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as ORMSession

import backend.db as app_db
from backend.api import shares
from backend.db import AccountToken, User
from backend.services import account_tokens, amap, mailer, quota
from backend.services.errors import ServiceError
from tests.conftest import login

PASSWORD = 'password9'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_share_snapshots():
    """分享页快照是进程内缓存，会跨用例存活，进出都清一次。"""
    shares.reset_cache()
    yield
    shares.reset_cache()


def _capture(monkeypatch):
    sent = []

    def fake_send(to, subject, text, html=None):
        sent.append({'to': to, 'subject': subject, 'text': text, 'html': html})
        return True

    monkeypatch.setattr(mailer, 'send', fake_send)
    return sent


def _link_token(entry):
    """从邮件正文取明文 token；#change-email= 与 #verify= 两种链接都认。"""
    text = entry['text']
    for marker in ('#change-email=', '#verify='):
        index = text.find(marker)
        if index >= 0:
            return text[index + len(marker):].splitlines()[0].strip().strip('。，,')
    raise AssertionError(f'邮件里没有验证链接：{text!r}')


def _register(c, monkeypatch, username='carol', email='carol@example.com'):
    sent = _capture(monkeypatch)
    resp = c.post('/api/register', json={
        'username': username, 'password': PASSWORD, 'email': email, 'accept_terms': True,
    })
    assert resp.status_code == 200, resp.text
    return sent


def _fields(username='carol'):
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        return {'email': user.email, 'pending_email': user.pending_email}


def _used_at(username='carol', kind=account_tokens.KIND_VERIFY_EMAIL):
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        rows = db.scalars(select(AccountToken).where(
            AccountToken.user_id == user.id, AccountToken.kind == kind,
        )).all()
        return [row.used_at for row in rows]


def _trip(c, days=1, city='桂林'):
    trip = c.post('/api/trips', json={'city': city, 'days': days})
    assert trip.status_code == 201, trip.text
    return trip.json()


def _share(c, trip_id):
    resp = c.post(f'/api/trips/{trip_id}/share')
    assert resp.status_code == 200, resp.text
    return resp.json()['token']


# --- P1-2 改邮箱后旧验证链接必须失效 ---------------------------------------

def test_change_email_invalidates_old_verify_link(client, monkeypatch):
    """换绑发起时就作废注册期的 VERIFY 链接，否则它能把邮箱改回旧地址。"""
    c, _ = client
    sent = _register(c, monkeypatch)
    old_verify = _link_token(sent[0])
    sent.clear()

    resp = c.post('/api/account/email', json={'email': 'new@example.com', 'password': PASSWORD})
    assert resp.status_code == 200, resp.text
    assert _fields()['pending_email'] == 'new@example.com'
    # token 行本身被标记为已用（不只是靠 pending 兜底）
    assert all(used is not None for used in _used_at())

    stale = c.post('/api/account/verify-email', json={'token': old_verify})
    assert stale.status_code == 400, '换绑期间旧验证链接必须失效'
    assert _fields()['email'] == 'carol@example.com'

    # 新链接照常可用，换绑流程本身不受影响
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    assert _fields() == {'email': 'new@example.com', 'pending_email': None}


def test_old_verify_link_cannot_revert_after_change_completes(client, monkeypatch):
    """换绑完成后，旧 VERIFY 链接（写着旧邮箱）再点一次不能把邮箱改回去。"""
    c, _ = client
    sent = _register(c, monkeypatch)
    old_verify = _link_token(sent[0])
    sent.clear()

    assert c.post('/api/account/email',
                  json={'email': 'new@example.com', 'password': PASSWORD}).status_code == 200
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200

    replay = c.post('/api/account/verify-email', json={'token': old_verify})
    assert replay.status_code == 400
    assert _fields()['email'] == 'new@example.com'


def test_verify_requires_token_email_to_match_current_email(client, monkeypatch):
    """即使 token 还有效，写着的邮箱与当前邮箱不一致也不能生效（防历史库数据回流）。"""
    c, _ = client
    sent = _register(c, monkeypatch)
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[0])}).status_code == 200
    assert c.post('/api/account/email',
                  json={'email': 'new@example.com', 'password': PASSWORD}).status_code == 200
    assert c.post('/api/account/verify-email',
                  json={'token': _link_token(sent[1])}).status_code == 200

    # 手工造一封「写给旧邮箱」的 VERIFY：pending 为空、但 email 不匹配
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == 'carol'))
        token = account_tokens.create(
            db, user.id, account_tokens.KIND_VERIFY_EMAIL, 'carol@example.com', 3600,
        )
        db.commit()
    assert c.post('/api/account/verify-email', json={'token': token}).status_code == 400
    assert _fields()['email'] == 'new@example.com'


# --- P1-3 SMTP 必须在写事务提交之后 ---------------------------------------

def test_email_flows_commit_before_sending(client, monkeypatch):
    """改邮箱/重发都必须先 commit pending+token，再进可能阻塞 10s 的 SMTP。"""
    c, _ = client
    marks = []
    original_commit = ORMSession.commit

    def recording_commit(self):
        marks.append('commit')
        return original_commit(self)

    monkeypatch.setattr(ORMSession, 'commit', recording_commit)
    sent = []

    def fake_send(to, subject, text, html=None):
        marks.append('send')
        sent.append({'to': to, 'subject': subject, 'text': text})
        return True

    monkeypatch.setattr(mailer, 'send', fake_send)
    assert c.post('/api/register', json={
        'username': 'carol', 'password': PASSWORD,
        'email': 'carol@example.com', 'accept_terms': True,
    }).status_code == 200

    marks.clear()
    sent.clear()
    assert c.post('/api/account/email',
                  json={'email': 'new@example.com', 'password': PASSWORD}).status_code == 200
    assert marks == ['commit', 'send'], '改邮箱时 SMTP 不能落在未提交的写事务里'

    marks.clear()
    assert c.post('/api/account/email/resend').status_code == 200
    assert marks == ['commit', 'send'], '重发同样先提交再发信'
    assert len(sent) == 2


# --- P1-4 APP_BASE_URL 默认值与生产校验 -----------------------------------

def test_production_without_base_url_fails_fast(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('APP_BASE_URL', raising=False)
    # .env 的本地 COOKIE_SECURE=false 不应掩盖这里的 APP_BASE_URL 校验。
    monkeypatch.delenv('COOKIE_SECURE', raising=False)
    with pytest.raises(RuntimeError, match='APP_BASE_URL'):
        mailer.validate_config()
    # 配好 HTTPS 之后不再报错；未显式写 COOKIE_SECURE 时由站点地址推导为 Secure。
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com')
    mailer.validate_config()


def test_importing_app_in_production_without_base_url_fails(monkeypatch):
    """导入 backend.main 就会触发校验：生产缺配置是启动失败，不是运行期才发现。"""
    # 显式给出会话密钥，否则启动会在更早的 SESSION_SECRET 守卫处失败，
    # 验证不到本用例关心的 APP_BASE_URL 校验（本机 .env 可能为空或未配置）。
    env = {**os.environ, 'APP_ENV': 'production', 'APP_BASE_URL': '', 'DATABASE_URL': 'sqlite://',
           'SESSION_SECRET': 's' * 40, 'PYTHONIOENCODING': 'utf-8'}
    # 子进程会打印中文错误信息；Windows 默认 GBK 解码会让 stderr 变成 None。
    # 本机 platform 导入 _wmi 的原生 WMI 初始化可能挂死；先塞占位模块，
    # 只影响平台版本探测，不影响这里要验证的 APP_BASE_URL 启动校验。
    import_code = (
        "import sys, types\n"
        "m = types.ModuleType('_wmi')\n"
        "m.exec_query = lambda q: (_ for _ in ()).throw(OSError('wmi disabled'))\n"
        "sys.modules.setdefault('_wmi', m)\n"
        "import backend.main\n"
    )
    proc = subprocess.run(
        [sys.executable, '-c', import_code],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=120,
    )
    assert proc.returncode != 0
    assert 'APP_BASE_URL' in proc.stderr


def test_dev_default_base_url_points_to_8000(monkeypatch):
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('APP_BASE_URL', raising=False)
    assert mailer.verification_link('abc') == 'http://127.0.0.1:8000/#verify=abc'
    assert mailer.reset_link('abc') == 'http://127.0.0.1:8000/#reset=abc'
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com/')
    assert mailer.verification_link('abc') == 'https://trip.example.com/#verify=abc'


# --- P1-5 nearby 限流规则必须命中真实路由 ---------------------------------

def test_nearby_endpoint_rate_limited_on_real_path(client, monkeypatch):
    c, places = client
    login(c)
    trip = _trip(c)

    async def nearby(city, location, category):
        return [places[1]]

    monkeypatch.setattr(amap, 'nearby_places', nearby)
    url = f"/api/trips/{trip['id']}/days/0/nearby"
    params = {'place_id': places[0]['id'], 'category': '餐厅'}
    codes = [c.get(url, params=params).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30, codes
    blocked = c.get(url, params=params)
    assert blocked.status_code == 429
    assert blocked.json()['detail'].startswith('操作太频繁，请')
    assert int(blocked.headers['Retry-After']) >= 1


# --- P1-6 分享页高德成本：TTL 快照 + 匿名配额 -----------------------------

def test_share_view_reuses_snapshot_within_ttl(client, monkeypatch):
    c, places = client
    login(c)
    trip = _trip(c)
    token = _share(c, trip['id'])
    calls = []

    async def counted(ids):
        calls.append(sorted(ids))
        return {p['id']: p for p in places}

    monkeypatch.setattr(amap, 'find_places', counted)
    first = c.post('/api/shares/view', json={'token': token})
    assert first.status_code == 200
    second = c.post('/api/shares/view', json={'token': token})
    assert second.status_code == 200
    assert len(calls) == 1, 'TTL 内的重复刷新不能再打高德'
    assert second.json()['days'] == first.json()['days']
    assert second.headers['cache-control'] == 'no-store'


def test_snapshot_cache_prunes_on_cache_hit_and_caps_entries(client, monkeypatch):
    """需求（0.3.0「分享快照缓存命中时也执行裁剪」）：命中路径要顺手回收过期条目，
    条目达到上限时整体重建，不能让缓存按行程无限增长。
    """
    c, _ = client
    login(c)
    trip_a = _trip(c, city='桂林')
    token_a = _share(c, trip_a['id'])
    assert c.post('/api/shares/view', json={'token': token_a}).status_code == 200
    fresh_key = next(iter(shares._snapshots))
    stale_key = (999, 'stale')
    now = time.monotonic()
    shares._snapshots[stale_key] = (now - shares.SHARE_SNAPSHOT_TTL_SECONDS - 1, {'days': []})

    # 命中路径：再次读同一份分享时，过期条目必须被清理，且本次命中不增加新条目
    assert c.post('/api/shares/view', json={'token': token_a}).status_code == 200
    assert stale_key not in shares._snapshots, '命中路径也要裁剪过期快照'
    assert fresh_key in shares._snapshots

    # 上限：容量设为 1 后再读另一份分享，缓存不能超过上限
    monkeypatch.setattr(shares, 'SHARE_SNAPSHOT_MAX_ENTRIES', 1)
    trip_b = _trip(c, city='成都')
    token_b = _share(c, trip_b['id'])
    assert c.post('/api/shares/view', json={'token': token_b}).status_code == 200
    assert len(shares._snapshots) == 1, '缓存条目超过上限时必须整体重建'


def test_share_view_degrades_to_snapshot_when_amap_fails(client, monkeypatch):
    c, _ = client
    login(c)
    trip = _trip(c)
    token = _share(c, trip['id'])
    first = c.post('/api/shares/view', json={'token': token})
    assert first.status_code == 200 and first.json()['days']

    # 让缓存过期，再把高德打成额度耗尽
    monkeypatch.setattr(shares, 'SHARE_SNAPSHOT_TTL_SECONDS', -1)

    async def exhausted(ids):
        raise ServiceError('高德额度已用完', 429)

    monkeypatch.setattr(amap, 'find_places', exhausted)
    second = c.post('/api/shares/view', json={'token': token})
    assert second.status_code == 200, '高德失败不能让分享页 500'
    assert second.json()['place_notice']
    assert second.json()['days'] == first.json()['days']


def test_share_view_counts_toward_anonymous_amap_quota(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv('ANON_AMAP_DAILY', '1')
    assert quota.scope_for_path('/api/shares/view') == 'amap'

    login(c)
    trip = _trip(c)
    token = _share(c, trip['id'])
    c.post('/api/logout')

    assert c.post('/api/shares/view', json={'token': token}).status_code == 200
    blocked = c.post('/api/shares/view', json={'token': token})
    assert blocked.status_code == 429
    assert '免费体验次数已用完' in blocked.json()['detail']


# --- P1-7 广场匿名可读 ----------------------------------------------------

def test_plaza_is_readable_without_login(client):
    c, _ = client
    login(c)
    trip = _trip(c, days=2)
    assert c.put(f"/api/trips/{trip['id']}/visibility",
                 json={'is_public': True}).json() == {'is_public': True}
    c.post('/api/logout')

    resp = c.get('/api/plaza')
    assert resp.status_code == 200, '游客也必须能读广场'
    rows = resp.json()['trips']
    mine = next(row for row in rows if row['id'] == trip['id'])
    assert set(mine) == {'id', 'title', 'city', 'days', 'owner', 'start_date'}
    assert mine['owner'] == 'alice' and mine['city'] == '桂林' and mine['days'] == 2

    # 过期/伪造 cookie 只当匿名，不返回 401
    c.cookies.set('trip_session', 'bogus-token')
    assert c.get('/api/plaza').status_code == 200
