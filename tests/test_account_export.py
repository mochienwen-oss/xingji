"""A12：账号数据导出。"""
import json

from sqlalchemy import select

import backend.db as app_db
from backend.db import Expense, Trip, TripBudget, User
from tests.conftest import login


def _user_id(username: str) -> int:
    with app_db.Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        return user.id


def _add_trip(owner: str, city: str = '杭州', deleted: bool = False) -> int:
    with app_db.Session() as db:
        trip = Trip(
            user_id=_user_id(owner),
            city=city,
            title=f'{city}周末',
            data=json.dumps({'request': {'city': city, 'days': 2}, 'days': [{'stops': []}]}),
            deleted_at='2026-01-02T00:00:00Z' if deleted else None,
        )
        db.add(trip)
        db.flush()
        db.add(TripBudget(trip_id=trip.id, amount_cents=100000))
        db.add(Expense(trip_id=trip.id, amount_cents=2500, category='餐饮',
                       expense_date='2026-01-01', place_id='B0FF', note='面'))
        db.commit()
        return trip.id


def test_export_account_contains_owned_trips_and_no_secrets(client):
    c, _places = client
    assert login(c).status_code == 200
    trip_id = _add_trip('alice')

    response = c.get('/api/account/export')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert 'attachment' in response.headers['content-disposition']

    body = response.json()
    assert body['account']['username'] == 'alice'
    assert body['account']['email_verified'] is False
    assert 'password_hash' not in body['account']
    assert 'session_nonce' not in body['account']
    assert 'password' not in json.dumps(body).lower()

    assert len(body['trips']) == 1
    trip = body['trips'][0]
    assert trip['id'] == trip_id
    assert trip['role'] == 'owner'
    assert trip['city'] == '杭州'
    assert trip['data']['request']['days'] == 2
    assert trip['budget_cents'] == 100000
    assert trip['expenses'][0]['amount_cents'] == 2500
    assert trip['expenses'][0]['note'] == '面'


def test_export_includes_deleted_trips_for_recovery_audit(client):
    c, _places = client
    assert login(c).status_code == 200
    _add_trip('alice', city='苏州', deleted=True)

    body = c.get('/api/account/export').json()
    assert body['trips'][0]['deleted_at'] == '2026-01-02T00:00:00Z'


def test_export_requires_login_and_does_not_leak_other_users(client):
    c, _places = client
    assert c.get('/api/account/export').status_code == 401

    _add_trip('bob', city='成都')
    assert login(c).status_code == 200
    body = c.get('/api/account/export').json()
    assert body['trips'] == []
