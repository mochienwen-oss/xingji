import hashlib
import json
import logging
import time
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DBSession
from ..db import ShareLink, Trip, User
from ..schemas import ShareAccess
from .dependencies import current_user, db_session, get_trip
from ..services import amap, analytics, share_page, trip_places
from ..services.tokens import hash_token, new_token

router = APIRouter()
log = logging.getLogger(__name__)

SHARE_SNAPSHOT_TTL_SECONDS = 300  # 分享页快照缓存 5 分钟：同一行程反复刷新不重复打高德
SHARE_SNAPSHOT_MAX_ENTRIES = 512
SHARE_NOTICE = '高德地图暂时不可用，已显示上次成功加载的行程快照。'


def _trip_data(row: Trip) -> dict:
    """解析 Trip.data；损坏的数据只影响这一条分享，不能抛 500 或返回半个对象。"""
    try:
        data = json.loads(row.data or '{}')
    except (TypeError, ValueError):
        log.warning('行程数据无法解析（trip_id=%s）', row.id, exc_info=True)
        raise HTTPException(503, '行程数据暂时无法读取，请稍后再试。')
    if not isinstance(data, dict):
        log.warning('行程数据不是对象（trip_id=%s）', row.id)
        raise HTTPException(503, '行程数据暂时无法读取，请稍后再试。')
    return data

# (trip_id, data 的 sha256) -> (写入时的 monotonic 时间, 已刷新地点详情的 data 深拷贝)
_snapshots: dict[tuple[int, str], tuple[float, dict]] = {}


def reset_cache() -> None:
    """清空分享快照缓存（测试用：进程内缓存会跨用例存活）。"""
    _snapshots.clear()


def _cache_key(row: Trip) -> tuple[int, str]:
    return (row.id, hashlib.sha256((row.data or '').encode('utf-8')).hexdigest())


def _prune(now: float) -> None:
    for key in [k for k, (at, _) in _snapshots.items() if now - at >= SHARE_SNAPSHOT_TTL_SECONDS]:
        _snapshots.pop(key, None)
    if len(_snapshots) >= SHARE_SNAPSHOT_MAX_ENTRIES:
        # 缓存只是加速手段：条目过多时整体清空重建，避免按行程无限堆积。
        _snapshots.clear()


async def _snapshot(row: Trip) -> dict:
    """取行程快照：5 分钟内同一份 data 直接复用，高德失败时回落到旧快照而不是 500。

    高德是分享页唯一的成本来源；缓存按「行程 id + data 哈希」隔离，行程一改就自然失效。
    """
    key = _cache_key(row)
    now = time.monotonic()
    cached = _snapshots.get(key)
    if cached and now - cached[0] < SHARE_SNAPSHOT_TTL_SECONDS:
        # 只读命中路径也要维护缓存：否则流量全打在命中上时过期条目永不回收。
        _prune(now)
        return deepcopy(cached[1])
    try:
        data = await trip_places.refresh(_trip_data(row))
    except Exception:
        # 超时、上游 4xx/5xx、数据异常都不能让分享页失败：优先给旧快照。
        log.warning('分享页刷新地点失败（trip_id=%s）', row.id, exc_info=True)
        data = None
    if data is not None and not data.get('place_notice'):
        _prune(now)
        _snapshots[key] = (now, deepcopy(data))
        return data
    if cached:
        # 这次只拿到部分地点：旧快照更完整，带上提示文案继续展示。
        fallback = deepcopy(cached[1])
        fallback['place_notice'] = (data or {}).get('place_notice') or SHARE_NOTICE
        return fallback
    if data is None:
        data = _trip_data(row)
        data['place_notice'] = SHARE_NOTICE
    return data


@router.get('/api/trips/{trip_id}/share-status')
def share_status(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """当前可见性（仅 owner）：私密 / 仅链接 / 公开。

    只返回是否存在有效链接，不返回链接原文——服务端只存哈希，无法还原。
    """
    row = get_trip(trip_id, user, db)
    active = db.scalar(select(ShareLink.id).where(
        ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None)).limit(1))
    return {
        'visibility': 'public' if row.is_public else ('link' if active else 'private'),
        'is_public': bool(row.is_public),
        'link_active': bool(active),
    }


@router.post('/api/trips/{trip_id}/share')
def create_share(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip(trip_id, user, db)
    # 一个行程只保留一个活跃分享：重新生成即撤销旧链接，避免链接无限扩散。
    db.execute(update(ShareLink).where(ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None))
               .values(revoked_at=amap.now()))
    token = new_token(32)
    db.add(ShareLink(trip_id=row.id, token_hash=hash_token(token)))
    db.commit()
    analytics.record('share')
    return {'token': token}

@router.delete('/api/trips/{trip_id}/share')
def revoke_shares(trip_id: int, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    row = get_trip(trip_id, user, db)
    # 与单条撤销保持一致：只标记 revoked_at、保留记录，便于排查旧链接；物理删除会丢掉审计线索。
    db.execute(update(ShareLink).where(ShareLink.trip_id == row.id, ShareLink.revoked_at.is_(None))
               .values(revoked_at=amap.now()))
    db.commit()
    return {'ok': True}

@router.get('/s/{token}', include_in_schema=False)
def share_landing(token: str = Path(min_length=1, max_length=100), db: DBSession = Depends(db_session)):
    """分享链接的可抓取落地页：给微信/X 抓标题与封面，再跳回互动版。

    只读 Trip.data 里的公开摘要，不刷新高德、不读预算与对话；token 失效时返回 404 页面。
    """
    row = db.scalar(select(Trip).join(ShareLink, ShareLink.trip_id == Trip.id).where(
        ShareLink.token_hash == hash_token(token), ShareLink.revoked_at.is_(None), Trip.deleted_at.is_(None)))
    if not row:
        return HTMLResponse(share_page.render_not_found(), status_code=404,
                            headers={'Cache-Control': 'no-store'})
    return HTMLResponse(share_page.render_share_page(row, token),
                        headers={'Cache-Control': 'no-store'})

@router.post('/api/shares/view')
async def view_share(body: ShareAccess, response: Response, db: DBSession = Depends(db_session)):
    row = db.scalar(select(Trip).join(ShareLink, ShareLink.trip_id == Trip.id).where(
        ShareLink.token_hash == hash_token(body.token), ShareLink.revoked_at.is_(None), Trip.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '分享不存在或已撤销。')
    data = await _snapshot(row)
    request = data.get('request') if isinstance(data.get('request'), dict) else {}
    response.headers['Cache-Control'] = 'no-store'
    days = []
    for day in data.get('days') or []:
        if not isinstance(day, dict):
            continue
        stops = []
        for stop in day.get('stops') or []:
            if not isinstance(stop, dict):
                continue
            place = stop.get('place') if isinstance(stop.get('place'), dict) else {}
            stops.append({'place': {key: place.get(key, '') for key in
                ('id', 'name', 'address', 'location', 'opentime', 'cost', 'source_time', 'photos', 'unavailable')},
                'duration': stop.get('duration', 0), 'activity': stop.get('activity', ''), 'reason': '',
                'fixed_time': stop.get('fixed_time'), 'fixed_next_day': stop.get('fixed_next_day', False)})
        routes = [{key: route.get(key) for key in
                   ('origin', 'destination', 'mode', 'duration', 'distance', 'polyline', 'source_time')}
                  for route in (day.get('routes') or []) if isinstance(route, dict)]
        for route in routes:
            route['polyline'] = route['polyline'] or []
        days.append({'stops': stops, 'routes': routes, 'start_time': day.get('start_time'), 'end_time': day.get('end_time')})
    # 只带用户名用于「谁做的」署名；不暴露邮箱等账号信息。
    owner = db.scalar(select(User.username).where(User.id == row.user_id))
    return {'id': row.id, 'is_public': bool(row.is_public), 'title': row.title, 'city': row.city,
            'request': {key: request.get(key) for key in ('city', 'days', 'start_date', 'transport')},
            'days': days, 'place_notice': data.get('place_notice', ''), 'owner': owner}

@router.post('/api/shares/fork', status_code=201)
def fork_share(body: ShareAccess, user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """凭分享链接把行程复制成自己的：私密分享也能「拿走一份」，不依赖公开广场。"""
    row = db.scalar(select(Trip).join(ShareLink, ShareLink.trip_id == Trip.id).where(
        ShareLink.token_hash == hash_token(body.token), ShareLink.revoked_at.is_(None), Trip.deleted_at.is_(None)))
    if not row:
        raise HTTPException(404, '分享链接无效或已失效。')
    data = _trip_data(row)
    data['conversation'] = []  # 原作者的 AI 对话可能含预算/同行人等隐私，副本从零开始
    copy = Trip(user_id=user.id, city=row.city, title=row.title,
                data=json.dumps(trip_places.for_storage(data), ensure_ascii=False))
    db.add(copy)
    db.commit()
    db.refresh(copy)
    analytics.record('fork')
    # 元数据放在 **data 之后：旧数据若残留 id/version 字段，也不能覆盖副本的真实主键与版本。
    return {**data, 'id': copy.id, 'title': copy.title, 'version': copy.version or 0,
            'is_owner': True, 'is_public': False}

@router.delete('/api/shares/{token}')
def revoke_share(token: str = Path(min_length=1, max_length=100),
                 user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """owner 撤销一条分享链接：标记 revoked_at 即失效，重复调用保持幂等。"""
    link = db.scalar(select(ShareLink).join(Trip, ShareLink.trip_id == Trip.id).where(
        ShareLink.token_hash == hash_token(token), Trip.user_id == user.id, Trip.deleted_at.is_(None)))
    if not link:
        raise HTTPException(404, '分享链接不存在或无权撤销。')
    if not link.revoked_at:
        link.revoked_at = amap.now()
        db.commit()
    return {'ok': True}
