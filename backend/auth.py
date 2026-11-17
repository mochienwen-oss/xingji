import base64
import binascii
import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def _random_secret() -> str:
    """进程内随机密钥：只在本进程有效，重启后所有旧 cookie 失效，必须留痕。"""
    logger.warning(
        '会话密钥无法持久化，已改用进程内随机密钥：重启后所有已登录会话都会失效。'
        '生产环境必须在环境变量中配置 SESSION_SECRET（至少 32 字节）。'
    )
    return secrets.token_hex(32)

def _secret(root: Path | None = None) -> str:
    """会话密钥：优先环境变量；本地开发落仓库根 .session-secret 复用，生产必须显式配置。

    生产（APP_ENV=production）缺少 SESSION_SECRET 时直接拒绝启动：自动生成的密钥
    每个 worker、每次重启都不同，表现为登录态随机失效且多副本无法共享会话；这类
    问题上线后很难定位，必须在启动阶段暴露。root 参数只用于测试指定目录。
    """
    env = os.getenv('SESSION_SECRET', '').strip()
    if env:
        if len(env) < 32:
            logger.warning('SESSION_SECRET 长度不足 32 字节，建议换成足够随机的长值。')
        return env
    if (os.getenv('APP_ENV', '') or '').strip().lower() == 'production':
        raise RuntimeError(
            'APP_ENV=production 时必须显式配置 SESSION_SECRET（至少 32 字节随机值）。'
            '缺少它会让每个进程生成不同密钥：登录态随机失效、多 worker/多副本无法共享会话。'
        )
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    path = base / '.session-secret'
    try:
        handle = os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='ascii')
        with handle:
            handle.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    except OSError:
        # 只读文件系统等极端情况退回进程内随机，不阻塞启动；但不能静默，否则线上表现为随机掉线。
        return _random_secret()
    try:
        return path.read_text(encoding='ascii').strip() or _random_secret()
    except (OSError, UnicodeError):
        return _random_secret()

SECRET = _secret()

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}${digest}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, digest = encoded.split('$', 1)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False

def make_token(user_id: int, session_version: int = 0, session_nonce: str = '') -> str:
    """payload 为 uid:expires:session_version:session_nonce，整体再拼签名；7 天过期不变。

    session_nonce 绑定用户这一行：SQLite 删除最高 id 后主键会被新账号复用，
    只认 uid 的旧 cookie 会因此打开新账号；nonce 让旧 token 对不上新行。
    """
    payload = f'{user_id}:{int(time.time()) + 86400 * 7}:{int(session_version)}:{session_nonce}'
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f'{payload}:{sig}'.encode()).decode()

def read_token(token: str) -> tuple[int, int, str] | None:
    """返回 (user_id, session_version, session_nonce)。

    兼容旧格式：四段视为 version 已引入、nonce 为空；三段视为最早版本（version=0）。
    历史用户 nonce 为空，旧 cookie 仍可用；新注册用户的 nonce 随机，旧 cookie 会被拒绝。
    """
    try:
        parts = base64.urlsafe_b64decode(token.encode()).decode().split(':')
    except (ValueError, UnicodeError, TypeError, binascii.Error):
        return None
    try:
        if len(parts) == 5:
            uid, expires, version, nonce, sig = parts
            expected = hmac.new(SECRET.encode(), f'{uid}:{expires}:{version}:{nonce}'.encode(), hashlib.sha256).hexdigest()
            if int(expires) > time.time() and hmac.compare_digest(sig, expected):
                return int(uid), int(version), nonce
        elif len(parts) == 4:
            uid, expires, version, sig = parts
            expected = hmac.new(SECRET.encode(), f'{uid}:{expires}:{version}'.encode(), hashlib.sha256).hexdigest()
            if int(expires) > time.time() and hmac.compare_digest(sig, expected):
                return int(uid), int(version), ''
        elif len(parts) == 3:
            uid, expires, sig = parts
            expected = hmac.new(SECRET.encode(), f'{uid}:{expires}'.encode(), hashlib.sha256).hexdigest()
            if int(expires) > time.time() and hmac.compare_digest(sig, expected):
                return int(uid), 0, ''
    except (ValueError, TypeError):
        return None
    return None
