"""UGC 举报：公开广场与分享页的举报入口，以及只给运营用的处理端点。

举报记录独立于行程生命周期：行程删除/清理后仍保留审计线索。
运营下架（hide）会取消公开、撤销所有分享链接并删除未使用邀请，但不删原始行程，
作者仍可在自己的行程里看到内容，误报也能通过 dismiss 留痕。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ..db import ShareLink, Trip, TripInvite, TripReport, User
from ..schemas import ReportCreate, ReportResolve
from ..services import amap
from .dependencies import current_user_optional, db_session, require_admin
from ..services.tokens import hash_token

router = APIRouter()
log = logging.getLogger(__name__)

REPORT_REASONS = ('虚假信息', '违法违规', '侵犯隐私', '垃圾广告', '其他')
REPORT_MESSAGE = '已收到举报，我们会在 24 小时内核查。'
ADMIN_PAGE_LIMIT = 100

def _clean_title(trip: Trip) -> str | None:
    title = (trip.title or '').strip()
    return title or None

def _pending_report(db: DBSession, trip_id: int, reporter_id: int) -> TripReport | None:
    return db.scalar(select(TripReport).where(
        TripReport.trip_id == trip_id,
        TripReport.reporter_user_id == reporter_id,
        TripReport.status == 'pending',
    ))

def _create_report(trip: Trip, body: ReportCreate, reporter: User | None,
                   source: str, db: DBSession) -> dict:
    reason = (body.reason or '').strip()
    if reason not in REPORT_REASONS:
        raise HTTPException(422, '请选择有效的举报原因。')
    detail = (body.detail or '').strip()
    if reporter is not None:
        existing = _pending_report(db, trip.id, reporter.id)
        if existing:
            return {'ok': True, 'duplicate': True, 'id': existing.id, 'message': REPORT_MESSAGE}
    report = TripReport(
        trip_id=trip.id,
        trip_title=_clean_title(trip),
        trip_city=trip.city,
        reporter_user_id=reporter.id if reporter else None,
        reason=reason,
        detail=detail,
        source=source,
        status='pending',
        created_at=amap.now(),
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        # 两个请求同时通过上面的去重检查时，由部分唯一索引兜底：后提交的一方回查后按重复处理。
        db.rollback()
        if reporter is not None:
            existing = _pending_report(db, trip.id, reporter.id)
            if existing:
                return {'ok': True, 'duplicate': True, 'id': existing.id, 'message': REPORT_MESSAGE}
        raise HTTPException(409, '举报提交冲突，请稍后重试。')
    db.refresh(report)
    # 只记录定位所需字段：detail 可能含联系方式，不写进日志。
    log.warning('UGC 举报 source=%s trip_id=%s report_id=%s reporter=%s reason=%s',
                source, trip.id, report.id, reporter.id if reporter else 'anonymous', reason)
    return {'ok': True, 'duplicate': False, 'id': report.id, 'message': REPORT_MESSAGE}

@router.post('/api/trips/{trip_id}/report')
def report_trip(trip_id: int, body: ReportCreate,
                user: User | None = Depends(current_user_optional),
                db: DBSession = Depends(db_session)):
    """举报公开广场里的行程；未公开的行程不暴露是否存在。"""
    trip = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.deleted_at.is_(None)))
    if not trip or not trip.is_public:
        raise HTTPException(404, '行程不存在或未公开。')
    return _create_report(trip, body, user, 'plaza', db)

@router.post('/api/shares/{token}/report')
def report_share(body: ReportCreate, token: str = Path(min_length=1, max_length=100),
                 user: User | None = Depends(current_user_optional),
                 db: DBSession = Depends(db_session)):
    """举报通过分享链接打开的行程：私密分享也能举报，不要求已公开到广场。"""
    row = db.scalar(select(Trip).join(ShareLink, ShareLink.trip_id == Trip.id).where(
        ShareLink.token_hash == hash_token(token),
        ShareLink.revoked_at.is_(None),
        Trip.deleted_at.is_(None),
    ))
    if not row:
        raise HTTPException(404, '分享不存在或已撤销。')
    return _create_report(row, body, user, 'share', db)

def _serialize(report: TripReport, usernames: dict[int, str] | None = None) -> dict:
    return {
        'id': report.id,
        'trip_id': report.trip_id,
        'trip_title': report.trip_title,
        'trip_city': report.trip_city,
        'reporter_user_id': report.reporter_user_id,
        'reporter': (usernames or {}).get(report.reporter_user_id) if report.reporter_user_id else None,
        'reason': report.reason,
        'detail': report.detail,
        'source': report.source,
        'status': report.status,
        'created_at': report.created_at,
        'resolved_at': report.resolved_at,
        'resolution': report.resolution,
    }

@router.get('/api/admin/reports')
def list_reports(status: str = Query(default='pending'), limit: int = Query(default=50, ge=1, le=ADMIN_PAGE_LIMIT),
                 offset: int = Query(default=0, ge=0), _: None = Depends(require_admin),
                 db: DBSession = Depends(db_session)):
    """运营列表：默认只看待处理；status=all 可查全部。"""
    if status not in ('pending', 'hidden', 'dismissed', 'all'):
        raise HTTPException(422, 'status 只能是 pending/hidden/dismissed/all。')
    condition = True if status == 'all' else TripReport.status == status
    total = db.scalar(select(func.count()).select_from(TripReport).where(condition)) or 0
    rows = db.scalars(select(TripReport).where(condition)
                      .order_by(TripReport.id.desc()).limit(limit).offset(offset)).all()
    # 运营需要看举报人用户名；不额外暴露邮箱或密码字段。
    reporter_ids = {row.reporter_user_id for row in rows if row.reporter_user_id}
    usernames = dict(db.execute(select(User.id, User.username)
                                .where(User.id.in_(reporter_ids))).all()) if reporter_ids else {}
    return {'reports': [_serialize(row, usernames) for row in rows],
            'total': total, 'limit': limit, 'offset': offset}

@router.post('/api/admin/reports/{report_id}/resolve')
def resolve_report(report_id: int, body: ReportResolve, _: None = Depends(require_admin),
                   db: DBSession = Depends(db_session)):
    """hide：下架公开内容并撤销分享/邀请；dismiss：判定不处理，仅留痕。"""
    report = db.get(TripReport, report_id)
    if not report:
        raise HTTPException(404, '举报不存在。')
    if report.status != 'pending':
        raise HTTPException(409, '这条举报已经处理过了。')
    trip_id = report.trip_id
    now = amap.now()
    if body.action == 'hide':
        status, resolution = 'hidden', (body.note or '').strip() or '内容已下架'
    else:
        status, resolution = 'dismissed', (body.note or '').strip() or '核查后不处理'
    # 用条件 UPDATE 抢处理权：两个运营同时点处理时只有一个能改到行，另一个拿 409，
    # 避免后提交者用不同结论覆盖先提交者的下架/驳回。
    claimed = db.execute(update(TripReport).where(
        TripReport.id == report_id,
        TripReport.status == 'pending',
    ).values(status=status, resolution=resolution, resolved_at=now))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '这条举报已经处理过了。')
    if body.action == 'hide':
        trip = db.get(Trip, trip_id)
        if trip and not trip.deleted_at:
            trip.is_public = 0
            db.execute(update(ShareLink)
                       .where(ShareLink.trip_id == trip.id, ShareLink.revoked_at.is_(None))
                       .values(revoked_at=now))
            db.execute(delete(TripInvite).where(TripInvite.trip_id == trip.id))
    db.commit()
    log.warning('UGC 举报处理 report_id=%s action=%s trip_id=%s status=%s',
                report_id, body.action, trip_id, status)
    return {'ok': True, 'id': report_id, 'status': status,
            'resolved_at': now, 'resolution': resolution}
