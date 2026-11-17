"""P0：软删除过期清理要级联派生授权表，且行程主键永不复用。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

import backend.db as app_db
from backend.db import Trip, TripCollaborator, TripInvite
from tests.conftest import login


def _count(model, trip_id):
    with app_db.Session() as db:
        return db.scalar(select(func.count()).select_from(model).where(model.trip_id == trip_id))


def test_purge_cascades_collaborators_invites_and_keeps_ids_unique(client):
    c, _ = client
    login(c)
    trip = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    token = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    login(c, 'bob', 'password2')
    assert c.post('/api/collaborators/accept', json={'token': token}).status_code == 200
    assert _count(TripCollaborator, trip['id']) == 1
    assert _count(TripInvite, trip['id']) == 0, '一次性邀请接受后即作废'
    # 再发一张未接受的邀请，验证过期清理会级联删除
    login(c)
    spare = c.post(f"/api/trips/{trip['id']}/collaborators/invite").json()['token']
    assert _count(TripInvite, trip['id']) == 1
    # 软删后手动把删除时间拨到保留期之外
    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    with app_db.Session() as db:
        db.get(Trip, trip['id']).deleted_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.commit()
    # 过期行程由维护任务清理，不再挂在列表请求上
    from backend.services import maintenance
    with app_db.Session() as db:
        maintenance.purge_expired(db)
    with app_db.Session() as db:
        assert db.get(Trip, trip['id']) is None
    assert _count(TripCollaborator, trip['id']) == 0
    assert _count(TripInvite, trip['id']) == 0
    # 旧邀请令牌（已消费的与被清理的）都随行程一起失效
    login(c, 'bob', 'password2')
    reused = c.post('/api/collaborators/accept', json={'token': token})
    assert reused.status_code == 404, reused.text
    purged = c.post('/api/collaborators/accept', json={'token': spare})
    assert purged.status_code == 404, purged.text
    # AUTOINCREMENT 让被清理的最高主键不会被新行程复用
    login(c)
    fresh = c.post('/api/trips', json={'city': '杭州', 'days': 1}).json()
    assert fresh['id'] > trip['id']
