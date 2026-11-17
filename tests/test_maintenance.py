from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import backend.db as app_db
from backend.db import AccountToken, Trip, TripInvite, User
from backend.services import maintenance


def _iso(delta):
    return (datetime.now(timezone.utc) + delta).isoformat()


def _seed():
    with app_db.Session() as db:
        user = User(username='maint', password_hash='x')
        db.add(user)
        db.flush()
        trip = Trip(user_id=user.id, city='杭州', data='{}')
        db.add(trip)
        db.flush()
        db.add_all([
            TripInvite(trip_id=trip.id, token_hash='invite-expired', created_at=_iso(timedelta(days=-8)),
                       expires_at=_iso(timedelta(days=-1))),
            TripInvite(trip_id=trip.id, token_hash='invite-valid', created_at=_iso(timedelta(days=-1)),
                       expires_at=_iso(timedelta(days=1))),
            TripInvite(trip_id=trip.id, token_hash='invite-legacy', created_at=_iso(timedelta(days=-8)),
                       expires_at=None),
            AccountToken(user_id=user.id, kind='verify_email', token_hash='token-expired',
                         created_at=_iso(timedelta(days=-1)), expires_at=_iso(timedelta(minutes=-1)), used_at=None),
            AccountToken(user_id=user.id, kind='reset_password', token_hash='token-used',
                         created_at=_iso(timedelta(days=-1)), expires_at=_iso(timedelta(days=1)),
                         used_at=_iso(timedelta(minutes=-5))),
            AccountToken(user_id=user.id, kind='verify_email', token_hash='token-valid',
                         created_at=_iso(timedelta(days=-1)), expires_at=_iso(timedelta(days=1)), used_at=None),
        ])
        db.commit()


def test_purge_expired_deletes_only_expired_rows(client):
    _seed()

    with app_db.Session() as db:
        counts = maintenance.purge_expired(db)
    assert counts == {'invites': 1, 'tokens': 2, 'trips': 0}

    with app_db.Session() as db:
        invites = {row.token_hash for row in db.scalars(select(TripInvite))}
        tokens = {row.token_hash for row in db.scalars(select(AccountToken))}
    assert invites == {'invite-valid', 'invite-legacy'}
    assert tokens == {'token-valid'}


def test_purge_expired_is_idempotent(client):
    _seed()
    with app_db.Session() as db:
        maintenance.purge_expired(db)

    with app_db.Session() as db:
        assert maintenance.purge_expired(db) == {'invites': 0, 'tokens': 0, 'trips': 0}
