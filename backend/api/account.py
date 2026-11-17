"""账户设置端点：条款同意、邮箱验证、修改邮箱与重发、忘记密码与重置、改密与注销。

verify-email 与 password/forgot、password/reset 公开（邮件链接可能在没有会话的浏览器里打开），
其余端点都要求登录。改密换发当前会话 cookie；注销硬删当前用户数据后清 cookie。
"""
import json
import logging
from datetime import datetime, timezone

import anyio
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ..auth import hash_password, verify_password
from ..db import (
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
from ..schemas import (
    ChangeEmail,
    ChangePassword,
    DeleteAccount,
    ForgotPassword,
    MemoryPreference,
    ResetPassword,
    VerifyEmail,
)
from ..services import account_tokens, accounts, mailer
from .dependencies import current_user, db_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/account')

EMAIL_TOKEN_TTL_SECONDS = 24 * 60 * 60
RESET_TOKEN_TTL_SECONDS = 30 * 60
RESET_COOLDOWN_SECONDS = 60
INVALID_LINK = '链接无效或已过期'
SEND_FAILED = '验证邮件发送失败，请稍后再试'
SEND_UNAVAILABLE = '当前环境未配置邮件服务，暂时无法发送验证邮件。'
PASSWORD_BLANK = '新密码不能全是空格'
EMAIL_TAKEN = '这个邮箱已绑定其他账号，请换一个或直接登录。'
SAME_EMAIL = '新邮箱与当前邮箱相同。'
PASSWORD_WRONG = '密码错误'
CURRENT_PASSWORD_WRONG = '当前密码错误'
DELETE_CONFIRM = '注销'
DELETE_CONFIRM_WRONG = '请输入「注销」确认'
DELETE_FAILED = '注销失败，请稍后重试'
NO_EMAIL = '没有可验证的邮箱。'
ALREADY_VERIFIED = '当前邮箱已验证，无需重复验证。'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get('/memory')
def get_memory_preference(user: User = Depends(current_user)):
    """规划记忆开关：关闭后 Harness 不读取也不写入长期记忆。"""
    return {'enabled': bool(getattr(user, 'memory_enabled', True))}


@router.patch('/memory')
def set_memory_preference(body: MemoryPreference, user: User = Depends(current_user),
                          db: DBSession = Depends(db_session)):
    user.memory_enabled = body.enabled
    db.commit()
    return {'enabled': bool(getattr(user, 'memory_enabled', body.enabled))}


@router.post('/terms')
def accept_terms(user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """记录条款同意；已同意时保留原时间戳，重复调用幂等。"""
    if not user.accepted_terms_at:
        user.accepted_terms_at = _now()
        db.commit()
    return {'accepted_terms_at': user.accepted_terms_at}


def _send_failure() -> str:
    """没配 SMTP 时说清楚原因，避免把环境问题报成“稍后再试”。"""
    return SEND_FAILED if mailer.configured() else SEND_UNAVAILABLE


async def _send_email_token(to: str, token: str, kind: str) -> bool:
    """按 kind 选模板，在线程池里发信；任何异常都按“没发出去”处理，不抛到端点。

    链接统一用 #verify=：前端验证页只认这一个入口，响应里的 kind 告诉它验证的是哪种邮箱。
    """
    link = mailer.verification_link(token)
    subject, text, html = (
        mailer.change_email(link)
        if kind == account_tokens.KIND_CHANGE_EMAIL
        else mailer.verification_email(link)
    )
    try:
        sent = await anyio.to_thread.run_sync(mailer.send, to, subject, text, html)
    except Exception:
        logger.warning('邮箱验证邮件发送异常（收件域名=%s）', to.rpartition('@')[2], exc_info=True)
        return False
    return bool(sent)


@router.post('/verify-email')
def verify_email(body: VerifyEmail, db: DBSession = Depends(db_session)):
    """公开端点：一次性 token 换已验证邮箱；kind 只接受 verify_email / change_email。"""
    plaintext = body.token.strip()
    kind = account_tokens.KIND_VERIFY_EMAIL
    row = account_tokens.consume(db, plaintext, kind)
    if row is None:
        kind = account_tokens.KIND_CHANGE_EMAIL
        row = account_tokens.consume(db, plaintext, kind)
    if row is None or not row.email:
        # 已用、过期、不存在、kind 不符都统一一句文案，避免泄露 token 状态
        db.rollback()
        raise HTTPException(400, INVALID_LINK)
    user = db.get(User, row.user_id)
    if not user:
        # 账号已注销
        db.rollback()
        raise HTTPException(400, INVALID_LINK)
    if kind == account_tokens.KIND_CHANGE_EMAIL:
        if (user.pending_email or '') != (row.email or ''):
            # 发信后又改了目标邮箱：旧链接不能覆盖当前 pending
            db.rollback()
            raise HTTPException(400, INVALID_LINK)
    elif user.pending_email or (user.email or '') != (row.email or ''):
        # P1-2：换绑待确认（pending 非空）或当前邮箱已经不是这封信写的那一个时，
        # 注册期的旧验证链接一律作废，否则改绑后还能用它把邮箱写回旧地址。
        db.rollback()
        raise HTTPException(400, INVALID_LINK)
    user.email = row.email
    user.email_verified_at = _now()
    if kind == account_tokens.KIND_CHANGE_EMAIL:
        user.pending_email = None
    try:
        db.commit()
    except IntegrityError as exc:
        # 等待验证期间目标邮箱被别的账号占用：消费记录随回滚撤销，用户可换目标后重发
        db.rollback()
        raise HTTPException(409, EMAIL_TAKEN) from exc
    return {'ok': True, 'email': user.email, 'kind': kind}


def _active_token_ids(db: DBSession, user_id: int, kinds: tuple[str, ...]) -> list[int]:
    """记下马上要被作废的 token id：发信失败时把它们恢复成未使用，上一封邮件里的链接照旧可用。"""
    return list(db.scalars(select(AccountToken.id).where(
        AccountToken.user_id == user_id,
        AccountToken.kind.in_(kinds),
        AccountToken.used_at.is_(None),
    )))


def _restore_tokens(db: DBSession, token_ids: list[int]) -> None:
    """短事务内把本次作废的旧 token 改回未使用（不 commit）。"""
    if not token_ids:
        return
    db.execute(update(AccountToken).where(AccountToken.id.in_(token_ids)).values(used_at=None))


@router.post('/email')
async def request_email_change(body: ChangeEmail, user: User = Depends(current_user),
                               db: DBSession = Depends(db_session)):
    """修改邮箱第一步：验当前密码、查占用、写 pending_email，并给新地址发确认信。"""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, PASSWORD_WRONG)
    try:
        email = accounts.normalize_email(body.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if email == (user.email or '').strip().lower():
        raise HTTPException(409, SAME_EMAIL)
    taken = db.scalar(select(User).where(
        User.id != user.id,
        or_(User.email == email, User.pending_email == email),
    ))
    if taken:
        raise HTTPException(409, EMAIL_TAKEN)
    stale = _active_token_ids(db, user.id, (account_tokens.KIND_VERIFY_EMAIL,))
    # P1-2：换绑期间旧验证链接必须一起作废，否则它能在 pending 之外把邮箱写回旧地址。
    account_tokens.invalidate(
        db, user.id, (account_tokens.KIND_CHANGE_EMAIL, account_tokens.KIND_VERIFY_EMAIL)
    )
    user.pending_email = email
    token = account_tokens.create(
        db, user.id, account_tokens.KIND_CHANGE_EMAIL, email, EMAIL_TOKEN_TTL_SECONDS
    )
    # P1-3：先提交 pending/token，再做可能阻塞到 SMTP 超时的发信；不让写事务跨网络。
    db.commit()
    if not await _send_email_token(email, token, account_tokens.KIND_CHANGE_EMAIL):
        # 发送失败不能留下验证不了的 pending：短事务删新 token、清 pending、恢复旧链接。
        account_tokens.delete_unused(db, user.id, account_tokens.KIND_CHANGE_EMAIL)
        user.pending_email = None
        _restore_tokens(db, stale)
        db.commit()
        raise HTTPException(503, _send_failure())
    return {'pending_email': email, 'email_sent': True}


@router.post('/email/resend')
async def resend_email(user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """重发验证信：目标 = pending_email or email；新 token 作废旧 change_email/verify_email。"""
    pending = (user.pending_email or '').strip()
    target = pending or (user.email or '').strip()
    if not target:
        raise HTTPException(400, NO_EMAIL)
    if user.email_verified_at and not pending:
        raise HTTPException(409, ALREADY_VERIFIED)
    kind = account_tokens.KIND_CHANGE_EMAIL if pending else account_tokens.KIND_VERIFY_EMAIL
    stale = _active_token_ids(
        db, user.id, (account_tokens.KIND_CHANGE_EMAIL, account_tokens.KIND_VERIFY_EMAIL)
    )
    account_tokens.invalidate(
        db, user.id, (account_tokens.KIND_CHANGE_EMAIL, account_tokens.KIND_VERIFY_EMAIL)
    )
    token = account_tokens.create(db, user.id, kind, target, EMAIL_TOKEN_TTL_SECONDS)
    # P1-3：先提交新 token 再发信；发信失败时用短事务回滚这一步，不持有写锁等 SMTP。
    db.commit()
    if not await _send_email_token(target, token, kind):
        account_tokens.delete_unused(db, user.id, kind)
        _restore_tokens(db, stale)
        db.commit()
        raise HTTPException(503, _send_failure())
    body = {'email_sent': True}
    if pending:
        body['pending_email'] = pending
    return body


def _user_by_identifier(db: DBSession, identifier: str) -> User | None:
    """identifier 含 @ 按邮箱查（格式非法按不存在处理），否则按用户名查。"""
    if '@' not in identifier:
        return db.scalar(select(User).where(User.username == identifier))
    try:
        email = accounts.normalize_email(identifier)
    except ValueError:
        return None
    return db.scalar(select(User).where(User.email == email))


async def _send_password_reset(to: str, token: str) -> bool:
    """重置邮件必须用 #reset= 链接（B4 的 _send_email_token 固定 #verify=，不能复用）。

    发信失败只记日志：调用方无论成败都返回同一句 200，避免用响应差异枚举账号。
    """
    subject, text, html = mailer.password_reset_email(mailer.reset_link(token))
    try:
        sent = await anyio.to_thread.run_sync(mailer.send, to, subject, text, html)
    except Exception:
        logger.warning('重置邮件发送异常（收件域名=%s）', to.rpartition('@')[2], exc_info=True)
        return False
    if not sent:
        logger.warning('重置邮件未发出（收件域名=%s）', to.rpartition('@')[2])
    return bool(sent)


@router.post('/password/forgot')
async def forgot_password(body: ForgotPassword, db: DBSession = Depends(db_session)):
    """公开端点：账号不存在、邮箱未验证、发信失败都返回同一个 200，不泄露账号状态。"""
    user = _user_by_identifier(db, body.identifier.strip())
    email = (user.email or '').strip() if user else ''
    if not user or not email or not user.email_verified_at:
        return {'ok': True}
    latest = account_tokens.latest_created_at(db, user.id, account_tokens.KIND_RESET_PASSWORD)
    if latest is not None and (datetime.now(timezone.utc) - latest).total_seconds() < RESET_COOLDOWN_SECONDS:
        # 冷却期内静默跳过：既不重复发信，也不作废上一封邮件里的链接
        return {'ok': True}
    token = account_tokens.create(
        db, user.id, account_tokens.KIND_RESET_PASSWORD, email, RESET_TOKEN_TTL_SECONDS
    )
    db.commit()
    await _send_password_reset(email, token)
    return {'ok': True}


@router.post('/password/reset')
def reset_password(body: ResetPassword, db: DBSession = Depends(db_session)):
    """公开端点：一次性 token 改密；不自动登录，session_version+1 让所有旧会话失效。"""
    if not body.new_password.strip():
        raise HTTPException(422, PASSWORD_BLANK)
    row = account_tokens.consume(db, body.token.strip(), account_tokens.KIND_RESET_PASSWORD)
    if row is None or db.get(User, row.user_id) is None:
        db.rollback()
        raise HTTPException(400, INVALID_LINK)
    # 单条 UPDATE 自增版本号：不做读改写，避免并发重置互相覆盖
    db.execute(
        update(User)
        .where(User.id == row.user_id)
        .values(
            password_hash=hash_password(body.new_password),
            session_version=User.session_version + 1,
        )
    )
    db.commit()
    return {'ok': True}


@router.post('/password')
def change_password(body: ChangePassword, response: Response,
                    user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """登录状态改密：验当前密码 → 单条 UPDATE 换 hash 并 +1 版本 → 给当前浏览器换发 cookie。

    新旧密码相同也按修改处理（版本照常 +1）：其他旧 cookie 立即失效，当前会话无缝继续。
    """
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, CURRENT_PASSWORD_WRONG)
    if not body.new_password.strip():
        raise HTTPException(422, PASSWORD_BLANK)
    # 与重置密码一致：版本号用 SQL 表达式自增，不做读改写，避免并发改密互相覆盖
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            password_hash=hash_password(body.new_password),
            session_version=User.session_version + 1,
        )
    )
    db.commit()
    db.refresh(user)
    accounts.set_session_cookie(response, user)
    return {'ok': True}


def _trip_data(raw: str):
    """行程 data 是历史 JSON 字符串：解析失败时导出原始文本，不因为一条坏数据让整包导出失败。"""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {'raw': raw}


@router.get('/export')
def export_account(user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """导出当前账号可见的数据：资料、自己创建的行程、被邀请协作的行程、预算支出与记忆。

    不包含密码哈希、会话 token、分享/邀请令牌（数据库只存哈希，也没有导出价值）。
    """
    owned = db.scalars(select(Trip).where(Trip.user_id == user.id).order_by(Trip.id)).all()
    memberships = db.execute(
        select(TripCollaborator, Trip)
        .join(Trip, Trip.id == TripCollaborator.trip_id)
        .where(TripCollaborator.user_id == user.id)
        .order_by(Trip.id)
    ).all()

    entries: list[tuple[Trip, str]] = [(trip, 'owner') for trip in owned]
    seen = {trip.id for trip in owned}
    for collaborator, trip in memberships:
        if trip.id in seen:
            continue
        entries.append((trip, collaborator.role or 'edit'))
        seen.add(trip.id)

    trip_ids = list(seen)
    budgets = {
        row.trip_id: row.amount_cents
        for row in db.scalars(select(TripBudget).where(TripBudget.trip_id.in_(trip_ids)))
    } if trip_ids else {}
    expenses_by_trip: dict[int, list[dict]] = {}
    if trip_ids:
        for expense in db.scalars(select(Expense).where(Expense.trip_id.in_(trip_ids)).order_by(Expense.id)):
            expenses_by_trip.setdefault(expense.trip_id, []).append({
                'amount_cents': expense.amount_cents,
                'category': expense.category,
                'expense_date': expense.expense_date,
                'place_id': expense.place_id,
                'note': expense.note,
            })

    trips = [{
        'id': trip.id,
        'role': role,
        'title': trip.title,
        'city': trip.city,
        'version': trip.version,
        'is_public': bool(trip.is_public),
        'deleted_at': trip.deleted_at,
        'budget_cents': budgets.get(trip.id),
        'expenses': expenses_by_trip.get(trip.id, []),
        'data': _trip_data(trip.data),
    } for trip, role in entries]

    memories = [{
        'category': memory.category,
        'scope': memory.scope,
        'key': memory.key,
        'value': memory.value,
        'confidence': memory.confidence,
        'created_at': memory.created_at.isoformat() if memory.created_at else None,
        'updated_at': memory.updated_at.isoformat() if memory.updated_at else None,
        'expires_at': memory.expires_at.isoformat() if memory.expires_at else None,
    } for memory in db.scalars(
        select(UserMemory)
        .where(UserMemory.user_id == user.id, UserMemory.superseded_at.is_(None))
        .order_by(UserMemory.id)
    )]

    exported_at = datetime.now(timezone.utc)
    payload = {
        'exported_at': exported_at.isoformat(),
        'account': {
            'username': user.username,
            'email': user.email,
            'email_verified': bool(user.email_verified_at),
            'accepted_terms_at': user.accepted_terms_at,
            'memory_enabled': bool(user.memory_enabled),
        },
        'trips': trips,
        'memories': memories,
    }
    return JSONResponse(
        content=payload,
        headers={'Content-Disposition': f'attachment; filename="xingji-export-{exported_at:%Y%m%d}.json"'},
    )


@router.delete('')
def delete_account(body: DeleteAccount, response: Response,
                   user: User = Depends(current_user), db: DBSession = Depends(db_session)):
    """立即注销：验密码与确认词后，在同一个事务里按外键顺序硬删该用户的数据。

    删除范围只由 user_id 与“该用户行程 id”子查询决定：别人的行程、别人 fork 的副本、
    别人行程里的预算/支出/协作者都不在范围内。先执行完全部 DELETE 再 commit，
    任何一步失败都整体回滚，cookie 只在提交成功后清除。
    """
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, PASSWORD_WRONG)
    if body.confirm != DELETE_CONFIRM:
        raise HTTPException(422, DELETE_CONFIRM_WRONG)
    try:
        trip_ids = select(Trip.id).where(Trip.user_id == user.id)
        # spec 2.3 的外键顺序：先清行程的派生数据，再清成员关系，最后删主表
        db.execute(delete(Expense).where(Expense.trip_id.in_(trip_ids)))
        db.execute(delete(TripBudget).where(TripBudget.trip_id.in_(trip_ids)))
        db.execute(delete(ShareLink).where(ShareLink.trip_id.in_(trip_ids)))
        db.execute(delete(TripInvite).where(TripInvite.trip_id.in_(trip_ids)))
        db.execute(delete(TripCollaborator).where(TripCollaborator.trip_id.in_(trip_ids)))
        # 该用户作为别人行程协作者的成员行：只删这一行，不动别人的行程
        db.execute(delete(TripCollaborator).where(TripCollaborator.user_id == user.id))
        db.execute(delete(Trip).where(Trip.user_id == user.id))
        db.execute(delete(AccountToken).where(AccountToken.user_id == user.id))
        # 举报记录按设计独立于行程/账号生命周期：保留审计内容，但解除与注销用户的关联。
        db.execute(update(TripReport).where(TripReport.reporter_user_id == user.id)
                   .values(reporter_user_id=None))
        # 长期记忆属于个人数据：SQLite 未开启外键级联，必须显式删除（含已被取代的历史行）
        db.execute(delete(UserMemory).where(UserMemory.user_id == user.id))
        db.execute(delete(User).where(User.id == user.id))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception('注销失败，已回滚（user_id=%s）', user.id)
        raise HTTPException(500, DELETE_FAILED) from exc
    response.delete_cookie(accounts.SESSION_COOKIE, path='/')
    return {'ok': True}
