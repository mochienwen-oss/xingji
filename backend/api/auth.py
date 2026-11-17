import logging
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from ..auth import hash_password, read_token, verify_password
from ..db import User
from ..schemas import Login, Register
from ..services import account_tokens, accounts, analytics, mailer
from ..services.env import env_int
from .dependencies import current_user, db_session

logger = logging.getLogger(__name__)
router = APIRouter()

VERIFY_EMAIL_TTL_SECONDS = 24 * 60 * 60
USERNAME_TAKEN = '用户名已被使用，请换一个。'
EMAIL_TAKEN = '这个邮箱已绑定其他账号，请换一个或直接登录。'
# 登录防爆破：失败计数与锁定按「用户名 + 客户端 IP」联合记录，同一来源连续失败达到上限后锁定该组合。
# 取舍：计数挂在账号上时，广场/分享页公开用户名，任何人都能连输错密码把任意用户锁 15 分钟并持续续锁（DoS）；
# 按来源 IP 分桶后，锁定只落在爆破来源，其他 IP 用正确密码登录不受影响。代价与 ratelimit.py 相同：
# 进程内计数不跨 worker/重启共享，单机 uvicorn 部署下可接受，重启只是清空计数。
# 锁定状态不再落库；users 表原有的 failed_login_count / last_failed_login_at / locked_until 三列已由 0009 迁移删除。
LOGIN_MAX_FAILURES = env_int('LOGIN_MAX_FAILURES', 10, minimum=1)
LOGIN_LOCK_SECONDS = env_int('LOGIN_LOCK_SECONDS', 900, minimum=60)
LOGIN_LOCKED_MESSAGE = '尝试次数过多，账号已暂时锁定，请稍后再试。'

SUPPORT_EMAIL_PATTERN = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')

def support_email() -> str:
    """客服邮箱由部署环境提供；格式不合法时不下发，前端会隐藏反馈入口。"""
    value = os.getenv('SUPPORT_EMAIL', '').strip()
    return value if SUPPORT_EMAIL_PATTERN.fullmatch(value) else ''

def operator_info() -> dict:
    """运营主体信息由部署环境提供；未配置时保持演示版文案。

    这里只负责下发可展示的公开信息，不推断或伪造公司主体、备案号与管辖地。
    """
    contact = os.getenv('OPERATOR_CONTACT_EMAIL', '').strip()
    return {
        'name': os.getenv('OPERATOR_NAME', '').strip()[:120],
        'contact_email': contact if SUPPORT_EMAIL_PATTERN.fullmatch(contact) else '',
        'jurisdiction': os.getenv('OPERATOR_JURISDICTION', '').strip()[:120],
        'icp_number': os.getenv('ICP_NUMBER', '').strip()[:60],
    }

@router.get('/api/config')
def config():
    return {
        'amap_js_key': os.getenv('AMAP_JS_KEY', ''),
        'amap_js_security_code': os.getenv('AMAP_JS_SECURITY_CODE', ''),
        'support_email': support_email(),
        'operator': operator_info(),
    }

# (用户名, IP) -> (连续失败次数, 最近一次失败时间, 锁定截止时间)；进程内实现，模式与 ratelimit._buckets 一致。
_LOGIN_FAILURES: dict[tuple[str, str], tuple[int, datetime, datetime | None]] = {}
# 防止用大量「用户名 × IP」组合堆内存：达到上限时清掉一小时未活跃且未锁定的条目。
_MAX_LOGIN_FAILURES = 10000


def _reset_login_failures() -> None:
    """清空登录失败计数（测试用，对应 ratelimit.reset）。"""
    _LOGIN_FAILURES.clear()


def _client_ip(request: Request) -> str:
    """来源 IP 与 main.py 限流中间件同源：只取直连地址，不解析 X-Forwarded-For（反代场景是独立问题）。"""
    return request.client.host if request.client else 'unknown'


def _lock_remaining(username: str, ip: str, now: datetime) -> int:
    """返回该 (用户名, IP) 剩余锁定秒数；0 表示未锁定或已到期。"""
    entry = _LOGIN_FAILURES.get((username, ip))
    if not entry:
        return 0
    locked_until = entry[2]
    if not locked_until or locked_until <= now:
        return 0
    return max(1, math.ceil((locked_until - now).total_seconds()))


def _prune_login_failures(now: datetime) -> None:
    """条目数达到上限时清掉既未锁定又一小时无动静的组合，模式抄自 ratelimit.check。"""
    if len(_LOGIN_FAILURES) < _MAX_LOGIN_FAILURES:
        return
    idle = timedelta(seconds=3600)
    for key, (_count, last_seen, locked_until) in list(_LOGIN_FAILURES.items()):
        if (locked_until is None or locked_until <= now) and now - last_seen > idle:
            _LOGIN_FAILURES.pop(key, None)
    # 全是活跃组合时按最近失败时间强制淘汰约 10%：内存有硬上限，
    # 代价是极端情况下少量失败计数被重置（锁定提前解除），优先保证服务不被打满。
    if len(_LOGIN_FAILURES) >= _MAX_LOGIN_FAILURES:
        overflow = max(1, len(_LOGIN_FAILURES) // 10)
        for key, _ in sorted(_LOGIN_FAILURES.items(), key=lambda item: item[1][1])[:overflow]:
            _LOGIN_FAILURES.pop(key, None)


def _record_login_failure(user: User, now: datetime, request: Request) -> int:
    """记录一次 (用户名, IP) 失败；达到上限时写入锁定并返回锁定秒数。"""
    ip = _client_ip(request)
    key = (user.username, ip)
    count = (_LOGIN_FAILURES.get(key) or (0, now, None))[0] + 1
    locked_until = now + timedelta(seconds=LOGIN_LOCK_SECONDS) if count >= LOGIN_MAX_FAILURES else None
    _prune_login_failures(now)
    _LOGIN_FAILURES[key] = (count, now, locked_until)
    if count < LOGIN_MAX_FAILURES:
        logger.info('登录失败 username=%s user_id=%s ip=%s failures=%s', user.username, user.id, ip, count)
        return 0
    # 审计：锁定是安全事件，必须能在日志里追溯（不记录密码）。
    logger.warning(
        '登录失败次数达到上限，账号已锁定 username=%s user_id=%s ip=%s failures=%s lock_seconds=%s',
        user.username, user.id, ip, count, LOGIN_LOCK_SECONDS,
    )
    return LOGIN_LOCK_SECONDS


@router.post('/api/login')
def login(body: Login, request: Request, response: Response, db: DBSession = Depends(db_session)):
    user = db.scalar(select(User).where(User.username == body.username))
    now = datetime.now(timezone.utc)
    if user:
        ip = _client_ip(request)
        remaining = _lock_remaining(user.username, ip, now)
        if remaining:
            logger.warning('登录被拒：账号仍在锁定中 username=%s user_id=%s ip=%s remaining=%ss',
                           user.username, user.id, ip, remaining)
            raise HTTPException(429, LOGIN_LOCKED_MESSAGE, headers={'Retry-After': str(remaining)})
    if not user or not verify_password(body.password, user.password_hash):
        if user:
            locked_for = _record_login_failure(user, now, request)
            if locked_for:
                raise HTTPException(429, LOGIN_LOCKED_MESSAGE, headers={'Retry-After': str(locked_for)})
        raise HTTPException(401, '用户名或密码错误')
    # 成功登录即清该 (用户名, IP) 的失败计数，避免偶尔输错累积到下一次；
    # 其他 IP 的计数互不影响。
    _LOGIN_FAILURES.pop((user.username, _client_ip(request)), None)
    accounts.set_session_cookie(response, user)
    analytics.record('login')
    return accounts.user_state(user)

async def _send_verification(email: str, token: str) -> bool:
    """发验证邮件；任何失败只记日志，绝不影响已创建的账号。"""
    subject, text, html = mailer.verification_email(mailer.verification_link(token))
    try:
        sent = await anyio.to_thread.run_sync(mailer.send, email, subject, text, html)
    except Exception:
        logger.warning('验证邮件发送异常，账号已创建（收件域名=%s）', email.rpartition('@')[2], exc_info=True)
        return False
    if not sent:
        logger.warning('验证邮件未发出，账号已创建（收件域名=%s）', email.rpartition('@')[2])
    return bool(sent)

@router.post('/api/register')
async def register(body: Register, response: Response, db: DBSession = Depends(db_session)):
    username = body.username.strip()
    if not username:
        raise HTTPException(422, '请输入用户名。')
    if not body.accept_terms:
        raise HTTPException(422, '请先阅读并同意用户协议与隐私说明')
    raw_email = (body.email or '').strip()
    if raw_email:
        try:
            email = accounts.normalize_email(raw_email)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        email = None
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, USERNAME_TAKEN)
    if email and db.scalar(select(User).where(or_(User.email == email, User.pending_email == email))):
        raise HTTPException(409, EMAIL_TAKEN)
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        email=email,
        accepted_terms_at=datetime.now(timezone.utc).isoformat(),
        # 每个账号的会话盐都不同：即使 id 被 SQLite 复用，旧 cookie 也对不上新行。
        session_nonce=secrets.token_hex(16),
    )
    db.add(user)
    try:
        # 唯一约束兜住并发注册：预检查通过后仍可能撞上另一请求刚提交的行
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, '用户名或邮箱已被使用，请换一个。') from exc
    accounts.set_session_cookie(response, user)
    email_sent = False
    if email:
        token = account_tokens.create(db, user.id, account_tokens.KIND_VERIFY_EMAIL, email, VERIFY_EMAIL_TTL_SECONDS)
        db.commit()
        email_sent = await _send_verification(email, token)
    analytics.record('register')
    # 与 /api/me 保持同一份用户状态形状，前端不用为注册单独兜底。
    return {**accounts.user_state(user), 'email_sent': email_sent}

@router.post('/api/logout')
def logout(request: Request, response: Response, db: DBSession = Depends(db_session)):
    """退出登录：清 cookie 之外还要吊销服务端会话。

    session_version +1 会让这枚 token（以及同一账号其它设备）立即失效；
    token 无效或已登出时仍返回 200，前端重复调用是幂等的。
    """
    parsed = read_token(request.cookies.get(accounts.SESSION_COOKIE, ''))
    if parsed:
        uid, session_version, session_nonce = parsed
        user = db.get(User, uid)
        if user and user.session_version == session_version and (user.session_nonce or '') == session_nonce:
            user.session_version = int(user.session_version or 0) + 1
            db.commit()
    response.delete_cookie(accounts.SESSION_COOKIE, path='/')
    return {'ok': True}

@router.get('/api/me')
def me(user: User = Depends(current_user)):
    return accounts.user_state(user)
