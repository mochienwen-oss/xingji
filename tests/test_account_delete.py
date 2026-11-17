"""B6：立即注销（硬删当前用户的数据）。

按 spec 2.3 的顺序清空 alice 名下行程的派生表、他作为协作者的成员行、他的行程、
account_tokens 与 users 行；bob 的行程、bob fork 的副本以及副本里的数据必须原样保留。
删除是单事务：最后一步失败时前面的 DELETE 也要回滚，cookie 不能清。
"""
from datetime import datetime, timezone

from sqlalchemy import func, select

import backend.db as app_db
from backend.api import account as account_api
from backend.db import (
    AccountToken,
    Expense,
    ShareLink,
    Trip,
    TripBudget,
    TripCollaborator,
    TripInvite,
    TripReport,
    User,
    UserMemory,
)
from backend.services import mailer
from tests.conftest import login

CONFIRM = '注销'
CONFIRM_WRONG = '请输入「注销」确认'
PASSWORD_WRONG = '密码错误'
DELETE_FAILED = '注销失败，请稍后重试'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _delete(c, password='password1', confirm=CONFIRM):
    # httpx 的 delete() 不接受 json，DELETE + body 用 request() 发。
    return c.request('DELETE', '/api/account', json={'password': password, 'confirm': confirm})


def _seed():
    """alice 两条自有行程（全套派生数据）、alice 是 bob 行程的协作者、bob 自有行程与 fork 副本。"""
    stamp = _now()
    with app_db.Session() as db:
        alice = db.scalar(select(User).where(User.username == 'alice'))
        bob = db.scalar(select(User).where(User.username == 'bob'))
        alice_trip = Trip(user_id=alice.id, city='杭州', data='{"days": []}', title='alice 的行程')
        alice_second = Trip(user_id=alice.id, city='成都', data='{"days": []}', title='alice 的第二个行程')
        bob_trip = Trip(user_id=bob.id, city='苏州', data='{"days": []}', title='bob 的行程')
        fork = Trip(user_id=bob.id, city='杭州', data='{"days": []}', title='alice 行程副本')
        db.add_all([alice_trip, alice_second, bob_trip, fork])
        db.flush()
        db.add_all([
            TripBudget(trip_id=alice_trip.id, amount_cents=100000),
            Expense(trip_id=alice_trip.id, amount_cents=1200, category='餐饮',
                   expense_date='2026-11-01', note='午饭'),
            ShareLink(trip_id=alice_trip.id, token_hash='a' * 64),
            TripInvite(trip_id=alice_trip.id, token_hash='b' * 64,
                       created_at=stamp, expires_at=stamp),
            TripCollaborator(trip_id=alice_trip.id, user_id=bob.id, created_at=stamp),
            TripBudget(trip_id=alice_second.id, amount_cents=20000),
            Expense(trip_id=alice_second.id, amount_cents=800, category='交通',
                   expense_date='2026-11-02', note='打车'),
            # alice 反过来是 bob 行程的协作者：这行也要删，但 bob 的行程本身不能删
            TripCollaborator(trip_id=bob_trip.id, user_id=alice.id, created_at=stamp),
            # bob 自己的数据：删 alice 账号不能碰
            TripBudget(trip_id=bob_trip.id, amount_cents=5000),
            Expense(trip_id=bob_trip.id, amount_cents=300, category='交通',
                    expense_date='2026-11-03', note='地铁'),
            ShareLink(trip_id=bob_trip.id, token_hash='c' * 64),
            TripInvite(trip_id=bob_trip.id, token_hash='d' * 64,
                       created_at=stamp, expires_at=stamp),
            AccountToken(user_id=alice.id, kind='reset_password', token_hash='e' * 64,
                         email='alice@example.com', created_at=stamp, expires_at=stamp),
            AccountToken(user_id=bob.id, kind='reset_password', token_hash='f' * 64,
                         email='bob@example.com', created_at=stamp, expires_at=stamp),
            # 长期记忆：alice 的生效行 + 已被取代的历史行都要随注销删除，bob 的必须保留
            UserMemory(user_id=alice.id, category='preference', key='hotel', value='安静'),
            UserMemory(user_id=alice.id, category='preference', key='hotel', value='近地铁',
                       superseded_at=datetime(2026, 1, 1)),
            UserMemory(user_id=bob.id, category='preference', key='hotel', value='含早餐'),
        ])
        db.commit()
        return {
            'alice_id': alice.id,
            'bob_id': bob.id,
            'alice_trips': [alice_trip.id, alice_second.id],
            'bob_trip': bob_trip.id,
            'fork': fork.id,
        }


def _count(model, **filters) -> int:
    with app_db.Session() as db:
        query = select(func.count()).select_from(model)
        for key, value in filters.items():
            query = query.where(getattr(model, key) == value)
        return db.scalar(query)


def _assert_alice_rows_present(ids):
    assert _count(Trip, user_id=ids['alice_id']) == 2
    for trip_id in ids['alice_trips']:
        assert _count(TripBudget, trip_id=trip_id) == 1
        assert _count(Expense, trip_id=trip_id) == 1
    assert _count(ShareLink, trip_id=ids['alice_trips'][0]) == 1
    assert _count(TripInvite, trip_id=ids['alice_trips'][0]) == 1
    assert _count(TripCollaborator, trip_id=ids['alice_trips'][0]) == 1
    assert _count(TripCollaborator, user_id=ids['alice_id']) == 1
    assert _count(AccountToken, user_id=ids['alice_id']) == 1


def test_delete_account_requires_login(client):
    c, _ = client
    resp = _delete(c)
    assert resp.status_code == 401
    assert resp.json()['detail'] == '请先登录'


def test_delete_account_rejects_wrong_confirm(client):
    """confirm 必须精确等于“注销”：多一个空格也是 422，且什么都不删。"""
    c, _ = client
    ids = _seed()
    assert login(c).status_code == 200
    for confirm in ('注销 ', ' 注销', 'cancel', '注销账号'):
        resp = _delete(c, confirm=confirm)
        assert resp.status_code == 422, resp.text
        assert resp.json()['detail'] == CONFIRM_WRONG
    assert c.get('/api/me').status_code == 200
    with app_db.Session() as db:
        assert db.get(User, ids['alice_id']) is not None
    _assert_alice_rows_present(ids)


def test_delete_account_rejects_wrong_password(client):
    """密码错：401“密码错误”，数据与 cookie 都保持原样。"""
    c, _ = client
    ids = _seed()
    assert login(c).status_code == 200
    resp = _delete(c, password='not-my-password')
    assert resp.status_code == 401
    assert resp.json()['detail'] == PASSWORD_WRONG
    assert c.get('/api/me').status_code == 200
    with app_db.Session() as db:
        assert db.get(User, ids['alice_id']) is not None
    _assert_alice_rows_present(ids)


def test_delete_account_purges_only_own_rows_and_keeps_others(client, monkeypatch):
    c, _ = client
    ids = _seed()
    assert login(c).status_code == 200
    assert c.get('/api/me').status_code == 200

    resp = _delete(c)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {'ok': True}
    assert c.cookies.get('trip_session') is None, '成功提交后必须 delete_cookie'
    assert c.get('/api/me').status_code == 401

    with app_db.Session() as db:
        # alice 的账号、行程与全部派生数据都硬删
        assert db.get(User, ids['alice_id']) is None
        for trip_id in ids['alice_trips']:
            assert db.get(Trip, trip_id) is None
            assert db.get(TripBudget, trip_id) is None
        assert _count(Trip, user_id=ids['alice_id']) == 0
        for trip_id in ids['alice_trips']:
            assert _count(Expense, trip_id=trip_id) == 0
            assert _count(ShareLink, trip_id=trip_id) == 0
            assert _count(TripInvite, trip_id=trip_id) == 0
            assert _count(TripCollaborator, trip_id=trip_id) == 0
        # alice 作为协作者出现在别人行程里的成员行也要删
        assert _count(TripCollaborator, user_id=ids['alice_id']) == 0
        assert _count(AccountToken, user_id=ids['alice_id']) == 0
        # 长期记忆（含 superseded 历史行）一并删除，避免 SQLite 主键复用时泄露给新账号
        assert _count(UserMemory, user_id=ids['alice_id']) == 0
        assert _count(UserMemory, user_id=ids['bob_id']) == 1

        # bob 自己的行程、其派生数据与 fork 副本全部保留
        assert db.get(User, ids['bob_id']) is not None
        assert db.get(Trip, ids['bob_trip']) is not None
        assert db.get(Trip, ids['fork']) is not None
        assert db.get(TripBudget, ids['bob_trip']).amount_cents == 5000
        assert _count(Expense, trip_id=ids['bob_trip']) == 1
        assert _count(ShareLink, trip_id=ids['bob_trip']) == 1
        assert _count(TripInvite, trip_id=ids['bob_trip']) == 1
        assert _count(TripCollaborator, trip_id=ids['bob_trip']) == 0, '只删 alice 的成员行'
        assert _count(AccountToken, user_id=ids['bob_id']) == 1

    # 用户名释放：同一用户名可以重新注册
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: True)
    again = c.post('/api/register', json={
        'username': 'alice', 'password': 'password1',
        'email': 'alice@example.com', 'accept_terms': True,
    })
    assert again.status_code == 200, again.text
    assert again.json()['username'] == 'alice'
    assert c.get('/api/me').json()['username'] == 'alice'


def test_delete_account_detaches_report_reporter(client):
    """注销只解除举报人与账号的关联，举报审计内容保留。

    需求（CHANGELOG 0.3.0「注销账号解除 trip_reports 的举报人引用」）：举报记录按设计
    独立于行程/账号生命周期；注销后 reporter_user_id 置 NULL，不能因外键/引用把审计行
    一起删掉，也不能留下指向已注销账号的引用。trip_reports 有意不设外键，所以这里直接
    校验列值。
    """
    c, _ = client
    ids = _seed()
    with app_db.Session() as db:
        bob_trip = db.get(Trip, ids['bob_trip'])
        bob_trip.is_public = 1  # 举报入口只对公开行程开放
        db.add(TripReport(trip_id=ids['bob_trip'], trip_title='bob 的行程', trip_city='苏州',
                          reporter_user_id=ids['alice_id'], reason='垃圾广告', detail='广告',
                          source='plaza', status='pending', created_at=_now()))
        db.commit()

    assert login(c).status_code == 200
    assert _delete(c).status_code == 200

    with app_db.Session() as db:
        reports = db.scalars(select(TripReport).where(TripReport.trip_id == ids['bob_trip'])).all()
        assert len(reports) == 1, '举报记录必须保留（审计），而不是随账号级联删除'
        report = reports[0]
        assert report.reporter_user_id is None, '注销后不能留下指向已删账号的举报人引用'
        assert report.reason == '垃圾广告' and report.detail == '广告'
        assert report.trip_title == 'bob 的行程' and report.trip_city == '苏州'

    # 解除关联后，新账号仍可对同一行程提交待处理举报（不会撞旧人的部分唯一索引）。
    assert c.post('/api/register', json={
        'username': 'carol', 'password': 'password3', 'accept_terms': True,
    }).status_code == 200
    resp = c.post(f"/api/trips/{ids['bob_trip']}/report", json={'reason': '垃圾广告'})
    assert resp.status_code in (200, 201), resp.text
    with app_db.Session() as db:
        rows = db.scalars(select(TripReport).where(TripReport.trip_id == ids['bob_trip'])
                          .order_by(TripReport.id)).all()
        assert len(rows) == 2
        assert rows[0].reporter_user_id is None
        assert rows[1].reporter_user_id is not None

def test_delete_account_rolls_back_when_final_step_fails(client, monkeypatch):
    """最后删 users 行时抛错：整笔事务回滚，数据完整、cookie 不清、响应 500。"""
    c, _ = client
    ids = _seed()
    assert login(c).status_code == 200
    cookie = c.cookies.get('trip_session')
    real_delete = account_api.delete

    def flaky_delete(target, *args, **kwargs):
        if target is User:
            raise RuntimeError('disk full')
        return real_delete(target, *args, **kwargs)

    monkeypatch.setattr(account_api, 'delete', flaky_delete)
    resp = _delete(c)
    assert resp.status_code == 500
    assert resp.json()['detail'] == DELETE_FAILED

    assert c.cookies.get('trip_session') == cookie, '失败不能删 cookie'
    assert c.get('/api/me').status_code == 200
    with app_db.Session() as db:
        assert db.get(User, ids['alice_id']) is not None
        for trip_id in ids['alice_trips']:
            assert db.get(Trip, trip_id) is not None
            assert db.get(TripBudget, trip_id) is not None
    _assert_alice_rows_present(ids)
