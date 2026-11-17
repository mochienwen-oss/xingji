"""账户领域服务：邮箱规范化、用户状态与会话 cookie。"""
import os
import re

from fastapi import Response

from ..auth import make_token
from ..db import User

EMAIL_MAX_LENGTH = 254
SESSION_COOKIE = 'trip_session'
SESSION_MAX_AGE = 604800

_EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def normalize_email(raw: str) -> str:
    """strip + lower 后校验：长度 ≤254、无控制字符、形状 user@host.tld；非法抛 ValueError。"""
    value = (raw or '').strip().lower()
    if not value:
        raise ValueError('请输入邮箱地址。')
    if len(value) > EMAIL_MAX_LENGTH:
        raise ValueError('邮箱地址过长。')
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise ValueError('邮箱地址包含无效字符。')
    if not _EMAIL_PATTERN.match(value):
        raise ValueError('请输入有效的邮箱地址。')
    return value


def user_state(user: User) -> dict:
    """登录/注册/me 共用的账户状态：未绑邮箱、未验证、未同意条款都由字段自身推导。"""
    email = (user.email or '').strip()
    return {
        'username': user.username,
        'email': email,
        'email_verified': bool(email and user.email_verified_at),
        'needs_terms': not user.accepted_terms_at,
        'needs_email': not email,
        'accepted_terms_at': user.accepted_terms_at,
    }


def cookie_secure() -> bool:
    """cookie 是否只走 HTTPS。

    显式设置 COOKIE_SECURE 时以它为准；未设置时按 APP_BASE_URL 推导，
    避免生产 HTTPS 部署忘记打开 Secure 而降级成明文 cookie。
    """
    raw = os.getenv('COOKIE_SECURE')
    if raw is not None and raw.strip():
        return raw.strip().lower() == 'true'
    return os.getenv('APP_BASE_URL', '').strip().lower().startswith('https://')


def set_session_cookie(response: Response, user: User) -> None:
    """写会话 cookie：token 必须带用户当前 session_version，改密/重置后旧 cookie 才会失效。"""
    response.set_cookie(
        SESSION_COOKIE,
        make_token(user.id, int(user.session_version or 0), user.session_nonce or ''),
        httponly=True,
        samesite='lax',
        secure=cookie_secure(),
        max_age=SESSION_MAX_AGE,
        path='/',
    )
