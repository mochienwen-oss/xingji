import os
import secrets

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from .. import db as app_db
from ..auth import read_token
from ..db import Trip, TripCollaborator, User
from ..services.accounts import SESSION_COOKIE

def db_session():
    # 走模块属性读取：测试会把 backend.db.Session 换成内存库会话工厂。
    with app_db.Session() as db:
        yield db

def current_user(request: Request, db: DBSession = Depends(db_session)) -> User:
    parsed = read_token(request.cookies.get(SESSION_COOKIE, ''))
    if not parsed:
        raise HTTPException(401, '请先登录')
    uid, session_version, session_nonce = parsed
    user = db.get(User, uid)
    # 改密/重置/注销会 +1；nonce 还会挡住「删除最高 id 后新注册账号复用主键」的旧 cookie。
    # 两者对不上都按未登录处理，文案保持一致，不泄露“密码已改”。
    if not user or user.session_version != session_version or (user.session_nonce or '') != session_nonce:
        raise HTTPException(401, '请先登录')
    return user

def current_user_optional(request: Request, db: DBSession = Depends(db_session)) -> User | None:
    """可选鉴权：token 无效（过期、改密后 version 不符、主键复用）只当作匿名，不返回 401。"""
    parsed = read_token(request.cookies.get(SESSION_COOKIE, ''))
    if not parsed:
        return None
    uid, session_version, session_nonce = parsed
    user = db.get(User, uid)
    if not user or user.session_version != session_version or (user.session_nonce or '') != session_nonce:
        return None
    return user

def get_trip(trip_id: int, user: User, db: DBSession) -> Trip:
    trip = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.user_id == user.id, Trip.deleted_at.is_(None)))
    if not trip:
        raise HTTPException(404, '行程不存在')
    return trip

def get_trip_member(trip_id: int, user: User, db: DBSession) -> Trip:
    """owner 或已接受邀请的协作者均可读写行程（删除/分享/协作管理仍限 owner）。"""
    trip = db.scalar(select(Trip).where(Trip.id == trip_id, Trip.deleted_at.is_(None)))
    if not trip:
        raise HTTPException(404, '行程不存在')
    if trip.user_id != user.id:
        member = db.scalar(select(TripCollaborator).where(TripCollaborator.trip_id == trip_id, TripCollaborator.user_id == user.id))
        if not member:
            raise HTTPException(404, '行程不存在')
    return trip

def optional_user_snapshot(request: Request) -> dict | None:
    """SSE 入口用：短会话读一次用户，不在流期间持有数据库连接。

    返回普通 dict（id/username/memory_enabled），离开 with 后仍可安全使用；
    未登录或 token 失效都返回 None，匿名也能使用规划会话。
    """
    parsed = read_token(request.cookies.get(SESSION_COOKIE, ''))
    if not parsed:
        return None
    uid, session_version, session_nonce = parsed
    # 走模块属性读取：测试会把 backend.db.Session 换成内存库会话工厂。
    with app_db.Session() as db:
        user = db.get(User, uid)
        if (
            not user
            or user.session_version != session_version
            or (user.session_nonce or '') != session_nonce
        ):
            return None
        return {
            'id': user.id,
            'username': user.username,
            'memory_enabled': bool(getattr(user, 'memory_enabled', True)),
        }

def require_admin(admin_token: str = Header(default='', alias='X-Admin-Token')) -> None:
    """运营端点的统一鉴权：未配置 ADMIN_TOKEN 时按端点不存在处理，避免暴露管理面。"""
    expected = os.getenv('ADMIN_TOKEN', '').strip()
    if not expected:
        raise HTTPException(404, 'Not Found')
    if not secrets.compare_digest(admin_token.strip(), expected):
        raise HTTPException(403, '无权访问运营接口。')

