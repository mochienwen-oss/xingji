"""分享码邀请：格式/幂等/轮换/停用、加入行程与限流。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import backend.db as app_db
import backend.main as main  # 确保 app 与路由已装配
from backend.db import Trip, TripCollaborator
from backend.services import join_codes
from tests.conftest import login

assert main.app is not None

ALPHABET = set(join_codes.ALPHABET)


def _create_trip(c, city='杭州'):
    resp = c.post('/api/trips', json={'city': city, 'days': 2, 'travelers': 2, 'transport': 'transit'})
    assert resp.status_code == 201, resp.text
    return resp.json()['id']


def _issue_code(c, trip_id):
    resp = c.post(f'/api/trips/{trip_id}/join-code', json={'rotate': False})
    assert resp.status_code == 200, resp.text
    return resp.json()['code']


def _user_id(username):
    from backend.db import User
    with app_db.Session() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _collaborators(trip_id):
    with app_db.Session() as db:
        return db.scalars(select(TripCollaborator).where(TripCollaborator.trip_id == trip_id)).all()


def test_join_code_format_is_eight_uppercase_alnum(client):
    c, _ = client
    login(c)
    code = _issue_code(c, _create_trip(c))
    assert isinstance(code, str) and len(code) == 8
    assert set(code) <= ALPHABET
    # 易混字符不出现在码里，口头转述不容易听错。
    assert not (set(code) & set('IO01'))


def test_two_trips_get_different_codes_and_rotate_replaces(client):
    c, _ = client
    login(c)
    first, second = _create_trip(c, '杭州'), _create_trip(c, '上海')
    code = _issue_code(c, first)
    assert _issue_code(c, second) != code
    resp = c.post(f'/api/trips/{first}/join-code', json={'rotate': True})
    assert resp.status_code == 200, resp.text
    rotated = resp.json()['code']
    assert len(rotated) == 8 and set(rotated) <= ALPHABET
    assert rotated != code
    # 不轮换再取：幂等返回同一个码。
    assert _issue_code(c, first) == rotated


def test_join_code_owner_only(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _issue_code(c, trip_id)
    login(c, 'bob', 'password2')
    for method, path in (('get', f'/api/trips/{trip_id}/join-code'),
                         ('post', f'/api/trips/{trip_id}/join-code'),
                         ('delete', f'/api/trips/{trip_id}/join-code')):
        resp = getattr(c, method)(path)
        assert resp.status_code == 404, (method, resp.text)
    # bob 也不能通过加入码去探测别的行程有没有码。
    assert c.post('/api/trips/join', json={'code': code}).status_code == 200


def test_join_with_code_creates_collaborator_once(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _issue_code(c, trip_id)
    login(c, 'bob', 'password2')
    resp = c.post('/api/trips/join', json={'code': f'  {code.lower()}  '})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['trip_id'] == trip_id and body['already_member'] is False
    rows = _collaborators(trip_id)
    assert [row.user_id for row in rows] == [_user_id('bob')]
    assert rows[0].role == 'edit'
    # 加入后能打开行程详情（协作权限生效）。
    assert c.get(f'/api/trips/{trip_id}').status_code == 200
    again = c.post('/api/trips/join', json={'code': code})
    assert again.status_code == 200
    assert again.json()['already_member'] is True
    assert len(_collaborators(trip_id)) == 1


def test_owner_using_own_code_is_already_member(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _issue_code(c, trip_id)
    resp = c.post('/api/trips/join', json={'code': code})
    assert resp.status_code == 200
    assert resp.json()['already_member'] is True
    assert _collaborators(trip_id) == []


def test_join_unknown_code_and_malformed_code_return_same_404(client):
    c, _ = client
    login(c)
    for code in ('ABCDEFGH', 'abc'):
        resp = c.post('/api/trips/join', json={'code': code})
        assert resp.status_code == 404
        assert resp.json()['detail'] == join_codes.INVALID_MESSAGE


def test_deleted_code_fails_join_and_get_returns_null(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _issue_code(c, trip_id)
    assert c.delete(f'/api/trips/{trip_id}/join-code').status_code == 204
    assert c.get(f'/api/trips/{trip_id}/join-code').json() == {'code': None}
    login(c, 'bob', 'password2')
    resp = c.post('/api/trips/join', json={'code': code})
    assert resp.status_code == 404
    assert resp.json()['detail'] == join_codes.INVALID_MESSAGE


def test_deleted_trip_cannot_be_joined(client):
    c, _ = client
    login(c)
    trip_id = _create_trip(c)
    code = _issue_code(c, trip_id)
    assert c.delete(f'/api/trips/{trip_id}').status_code == 200
    login(c, 'bob', 'password2')
    resp = c.post('/api/trips/join', json={'code': code})
    assert resp.status_code == 404
    assert resp.json()['detail'] == join_codes.INVALID_MESSAGE


def test_join_route_is_not_swallowed_by_path_param_routes(client):
    from backend.api import trips as trips_api
    # FastAPI 新版把 include_router 存成 _IncludedRouter 惰性匹配，直接看 trips router 自己的注册顺序。
    routes = [(getattr(route, 'path', ''), getattr(route, 'methods', set()) or set())
              for route in trips_api.router.routes]
    join_index = next(index for index, (path, methods) in enumerate(routes)
                      if path == '/api/trips/join' and 'POST' in methods)
    earlier = [(path, sorted(methods)) for path, methods in routes[:join_index]
               if path.startswith('/api/trips/{') and 'POST' in methods]
    assert earlier == [], f'这些 POST 路由注册在 /api/trips/join 之前，会把 join 当路径参数：{earlier}'
    # 功能上也证明它没被 {trip_id} 吞掉：无效码走 join 自己的 404 文案，而不是路径参数 422。
    c, _ = client
    login(c)
    resp = c.post('/api/trips/join', json={'code': 'ABCDEFGH'})
    assert resp.status_code == 404
    assert resp.json()['detail'] == join_codes.INVALID_MESSAGE


def test_join_is_rate_limited(client):
    c, _ = client
    login(c)
    for _ in range(5):
        assert c.post('/api/trips/join', json={'code': 'ABCDEFGH'}).status_code == 404
    resp = c.post('/api/trips/join', json={'code': 'ABCDEFGH'})
    assert resp.status_code == 429
    assert '操作太频繁' in resp.json()['detail']


def test_unique_index_blocks_duplicate_join_code(client):
    c, _ = client
    login(c)
    first, second = _create_trip(c, '杭州'), _create_trip(c, '上海')
    code = _issue_code(c, first)
    with app_db.Session() as db:
        db.get(Trip, second).join_code = code
        with pytest.raises(IntegrityError):
            db.commit()


def test_assign_retries_when_generated_code_collides(client, monkeypatch):
    c, _ = client
    login(c)
    first, second = _create_trip(c, '杭州'), _create_trip(c, '上海')
    taken = _issue_code(c, first)
    generated = iter([taken, 'ZZZZZZZZ'])
    monkeypatch.setattr(join_codes, 'generate', lambda: next(generated))
    with app_db.Session() as db:
        row = db.get(Trip, second)
        assert join_codes.assign(db, row) == 'ZZZZZZZZ'
        assert db.execute(select(Trip.join_code).where(Trip.id == second)).scalar_one() == 'ZZZZZZZZ'


def test_assign_gives_up_after_repeated_collisions(client, monkeypatch):
    c, _ = client
    login(c)
    first, second = _create_trip(c, '杭州'), _create_trip(c, '上海')
    taken = _issue_code(c, first)
    monkeypatch.setattr(join_codes, 'generate', lambda: taken)
    with app_db.Session() as db:
        assert join_codes.assign(db, db.get(Trip, second)) is None
    with app_db.Session() as db:
        assert db.execute(select(Trip.join_code).where(Trip.id == second)).scalar_one() is None
