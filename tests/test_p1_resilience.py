"""B10：P1 韧性收尾。

- restore 遇到历史脏 deleted_at 只能 404，不能 500；
- GET /api/trips 与 GET /api/plaza 遇到单条坏 JSON 只跳过该行并 warning；
- 已删行程的保存路径保持 404（get_trip_member 已过滤 deleted_at，这里锁行为）；
- 灵感主题缓存按插入顺序限容 256。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

import backend.db as app_db
from backend.api import inspiration
from tests.conftest import login


def _create_trip(c, city='杭州', days=2):
    resp = c.post('/api/trips', json={'city': city, 'days': days})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _alice_id() -> int:
    with app_db.Session() as db:
        return db.scalar(select(app_db.User.id).where(app_db.User.username == 'alice'))


def _set_deleted_at(trip_id: int, value: str) -> None:
    with app_db.Session() as db:
        row = db.get(app_db.Trip, trip_id)
        row.deleted_at = value
        db.commit()


def _add_corrupt_trip(user_id: int, *, is_public: int) -> int:
    with app_db.Session() as db:
        row = app_db.Trip(user_id=user_id, city='苏州', title='坏行', data='{', is_public=is_public)
        db.add(row)
        db.commit()
        return row.id


def test_restore_accepts_naive_deleted_at(client):
    """历史行可能存的是不带时区的 isoformat：补 UTC 后应正常恢复。"""
    c, _ = client
    login(c)
    trip = _create_trip(c)
    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    _set_deleted_at(trip['id'], datetime.now(timezone.utc).replace(tzinfo=None).isoformat())

    resp = c.post(f"/api/trips/{trip['id']}/restore")

    assert resp.status_code == 200, resp.text
    assert resp.json()['ok'] is True


def test_restore_corrupt_deleted_at_is_404(client, caplog):
    """deleted_at 是乱码时按不可恢复处理：404 + warning，绝不 500。"""
    c, _ = client
    login(c)
    trip = _create_trip(c)
    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200
    _set_deleted_at(trip['id'], 'not-a-timestamp')

    with caplog.at_level(logging.WARNING, logger='backend.api.trips'):
        resp = c.post(f"/api/trips/{trip['id']}/restore")

    assert resp.status_code == 404
    assert resp.json()['detail'] == '没有找到可恢复的行程。'
    assert any(str(trip['id']) in record.getMessage() for record in caplog.records)



def test_trip_list_skips_corrupt_rows(client, caplog):
    c, _ = client
    login(c)
    good = _create_trip(c)
    bad_id = _add_corrupt_trip(_alice_id(), is_public=0)

    with caplog.at_level(logging.WARNING, logger='backend.api.trips'):
        resp = c.get('/api/trips')

    assert resp.status_code == 200
    body = resp.json()
    assert [item['id'] for item in body] == [good['id']]
    assert body[0]['request']['city'] == '杭州'
    warnings = [record.getMessage() for record in caplog.records
                if record.levelno == logging.WARNING]
    # 告警带 trip id，但不把整份 data 打出来。
    assert any(str(bad_id) in message for message in warnings)
    assert all('{' not in message for message in warnings)


def test_plaza_skips_corrupt_rows(client, caplog):
    c, _ = client
    login(c)
    trip = _create_trip(c)
    assert c.put(f"/api/trips/{trip['id']}/visibility",
                 json={'is_public': True}).status_code == 200
    bad_id = _add_corrupt_trip(_alice_id(), is_public=1)

    with caplog.at_level(logging.WARNING, logger='backend.api.trips'):
        resp = c.get('/api/plaza')

    assert resp.status_code == 200
    body = resp.json()
    ids = [item['id'] for item in body['trips']]
    assert trip['id'] in ids
    assert bad_id not in ids
    assert all(set(item) == {'id', 'title', 'city', 'days', 'owner', 'start_date'}
               for item in body['trips'])
    assert any(str(bad_id) in record.getMessage() for record in caplog.records)


def test_save_days_on_deleted_trip_is_404(client):
    """删除后写保存必须 404；顺带确认失败路径没有碰 version/CAS。"""
    c, _ = client
    login(c)
    trip = _create_trip(c)
    assert c.delete(f"/api/trips/{trip['id']}").status_code == 200

    resp = c.put(f"/api/trips/{trip['id']}/days",
                 json={'days': trip['days'], 'version': trip['version']})

    assert resp.status_code == 404
    assert resp.json()['detail'] == '行程不存在'
    with app_db.Session() as db:
        row = db.get(app_db.Trip, trip['id'])
        assert row.version == trip['version']


def test_theme_catalog_is_constant_and_city_independent(client):
    themes = inspiration._theme_catalog()
    assert len(themes) == 8
    assert next(theme for theme in themes if theme['id'] == 'nature')['label'] == '自然疗愈'
    assert all('breath' not in theme['label'] for theme in themes)

    # 返回副本：调用方改动不会污染模块级常量。
    themes[0]['label'] = '被改掉'
    assert inspiration._theme_catalog()[0]['label'] == '城市漫步'

    c, _ = client
    hangzhou = c.get('/api/inspiration/themes', params={'city': '杭州'})
    chengdu = c.get('/api/inspiration/themes', params={'city': '成都'})
    assert hangzhou.status_code == 200
    assert hangzhou.json()['themes'] == chengdu.json()['themes']
    assert len(hangzhou.json()['themes']) == 8
