"""SMTP 邮件服务：只用标准库 smtplib / email / ssl，失败不抛到端点。

配置来自环境变量（示例见 .env.example）：
SMTP_HOST、SMTP_PORT、SMTP_SECURITY、SMTP_USER、SMTP_PASSWORD、SMTP_FROM、
SMTP_FROM_NAME、APP_BASE_URL。

对外接口：
- configured() -> bool
- validate_config() -> None（生产缺 APP_BASE_URL 时抛 RuntimeError，导入期也会校验）
- send(to, subject, text, html=None) -> bool
- verification_link(token) / reset_link(token) -> str
- verification_email(link) / change_email(link) / password_reset_email(link)
  均返回 (subject, text, html)，HTML 只插入链接，不拼接用户名或邮箱等用户输入。

日志只记录异常类型与收件域名，不记录正文、token 或 SMTP 授权码。
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from . import metrics, site_config

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 10
_DEFAULT_FROM_NAME = '行迹 Trip'
_DEFAULT_PORTS = {'ssl': 465, 'starttls': 587, 'none': 25}

_unconfigured_warned = False


def _env(name: str, default: str = '') -> str:
    return os.getenv(name, default).strip()


def configured() -> bool:
    """SMTP_HOST 与 SMTP_FROM 都存在才算可发信。"""
    return bool(_env('SMTP_HOST') and _env('SMTP_FROM'))


def _security() -> str:
    value = _env('SMTP_SECURITY', 'starttls').lower()
    # 未知值按 starttls 处理，避免误降级成明文。
    return value if value in _DEFAULT_PORTS else 'starttls'


def _port(security: str) -> int:
    raw = _env('SMTP_PORT')
    if raw:
        try:
            port = int(raw)
        except ValueError:
            port = 0
        if 0 < port < 65536:
            return port
    return _DEFAULT_PORTS[security]


def validate_config() -> None:
    """生产环境启动前校验站点地址与 cookie 安全。

    具体规则在 backend/services/site_config.py：APP_BASE_URL 必须是 https 公网地址、
    不能是本机地址，COOKIE_SECURE 不能显式关闭。模块导入时也会调用一次
    （main.py 导入路由时触发），所以配置不安全会让进程起不来，而不是等到发邮件才暴露。
    """
    site_config.validate_startup()


def verification_link(token: str) -> str:
    return f'{site_config.base_url()}/#verify={token}'


def reset_link(token: str) -> str:
    return f'{site_config.base_url()}/#reset={token}'


def _recipient_domain(address: str) -> str:
    _, _, domain = address.rpartition('@')
    return domain.lower() or 'unknown'


def _build_message(to: str, subject: str, text: str, html: str | None) -> EmailMessage:
    from_addr = _env('SMTP_FROM')
    from_name = _env('SMTP_FROM_NAME', _DEFAULT_FROM_NAME) or _DEFAULT_FROM_NAME
    message = EmailMessage()
    message['From'] = f'{from_name} <{from_addr}>'
    message['To'] = to
    message['Subject'] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype='html')
    return message


def _new_client(security: str, host: str, port: int):
    if security == 'ssl':
        return smtplib.SMTP_SSL(
            host, port, timeout=SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context()
        )
    return smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """同步发送一封邮件；未配置或失败返回 False，由调用方决定响应语义。"""
    global _unconfigured_warned
    if not configured():
        if not _unconfigured_warned:
            logger.warning('SMTP 未配置（缺少 SMTP_HOST 或 SMTP_FROM），邮件不会发送')
            _unconfigured_warned = True
        metrics.observe_email('unconfigured')
        return False

    security = _security()
    client = None
    try:
        client = _new_client(security, _env('SMTP_HOST'), _port(security))
        if security == 'starttls':
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        user = _env('SMTP_USER')
        if user:
            client.login(user, os.getenv('SMTP_PASSWORD', ''))
        client.send_message(_build_message(to, subject, text, html))
        metrics.observe_email('sent')
        return True
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        metrics.observe_email('failed')
        logger.warning('邮件发送失败：%s（收件域名=%s）', type(exc).__name__, _recipient_domain(to))
        return False
    finally:
        if client is not None:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass


_HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<body style="margin:0;padding:24px;background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px">
    <h2 style="margin:0 0 16px;font-size:20px">{title}</h2>
    <p style="margin:0 0 16px;line-height:1.7">{lead}</p>
    <p style="margin:0 0 20px"><a href="{link}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:#2563eb;color:#ffffff;text-decoration:none">{action}</a></p>
    <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.6">如果按钮无法点击，请复制链接到浏览器打开：<br>{link}</p>
  </div>
</body>
</html>
"""


def _html(title: str, lead: str, action: str, link: str) -> str:
    # 只替换固定模板中的占位符；title/lead/action 都是模块内常量，link 由 token 生成。
    return (
        _HTML_PAGE.replace('{title}', title)
        .replace('{lead}', lead)
        .replace('{action}', action)
        .replace('{link}', link)
    )


_VERIFICATION_TEXT = """你好，

在 24 小时内打开下面的链接完成邮箱验证。不是你本人操作可忽略。

{link}

行迹 Trip
"""

_CHANGE_EMAIL_TEXT = """你好，

请在 24 小时内打开下面的链接确认新邮箱。确认后，这个邮箱将用于登录找回。

{link}

如果不是你本人操作，请忽略这封邮件。

行迹 Trip
"""

_PASSWORD_RESET_TEXT = """你好，

请打开下面的链接重置行迹密码。链接 30 分钟内有效，只能使用一次。

{link}

不是你本人操作请忽略，并考虑修改密码。

行迹 Trip
"""


def verification_email(link: str) -> tuple[str, str, str]:
    """验证邮箱：返回（主题, 纯文本, HTML）。"""
    return (
        '验证你的行迹邮箱',
        _VERIFICATION_TEXT.replace('{link}', link),
        _html(
            '验证你的行迹邮箱',
            '在 24 小时内打开下面的链接完成邮箱验证。不是你本人操作可忽略。',
            '验证我的邮箱',
            link,
        ),
    )


def change_email(link: str) -> tuple[str, str, str]:
    """修改邮箱：返回（主题, 纯文本, HTML）。"""
    return (
        '确认你的新邮箱',
        _CHANGE_EMAIL_TEXT.replace('{link}', link),
        _html(
            '确认你的新邮箱',
            '请在 24 小时内打开下面的链接确认。确认后，这个邮箱将用于登录找回。',
            '确认新邮箱',
            link,
        ),
    )


def password_reset_email(link: str) -> tuple[str, str, str]:
    """重置密码：返回（主题, 纯文本, HTML）。"""
    return (
        '重置你的行迹密码',
        _PASSWORD_RESET_TEXT.replace('{link}', link),
        _html(
            '重置你的行迹密码',
            '链接 30 分钟内有效，只能使用一次。不是你本人操作请忽略，并考虑修改密码。',
            '重置密码',
            link,
        ),
    )


# 导入期即校验：生产环境缺 APP_BASE_URL 时 app 起不来（main.py 导入路由会先导入本模块），
# 而不是等到用户点「修改邮箱」才发出指向 127.0.0.1 的死链。
validate_config()
