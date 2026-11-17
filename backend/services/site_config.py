"""生产环境启动校验：把"能启动"与"能安全公开"区分开。

只校验客观不安全的配置，不替负责人决定 SMTP、备案或法务主体：
- APP_BASE_URL 必须是 https 公网地址，邮件/分享/OG 链接不能指向 localhost；
- COOKIE_SECURE 不能显式设为 false（未设置时由 accounts.cookie_secure 按 https 推导）。

开发/测试（APP_ENV 未设置或非 production）完全不受影响。
"""
import os
from urllib.parse import urlsplit

_LOCAL_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1'}
# 开发默认：与后端 8000 端口对齐；生产必须显式配置，见 validate_production。
DEFAULT_DEV_BASE_URL = 'http://127.0.0.1:8000'


def is_production(app_env: str | None = None) -> bool:
    value = app_env if app_env is not None else os.getenv('APP_ENV', '')
    return (value or '').strip().lower() == 'production'


def configured_base_url() -> str:
    """APP_BASE_URL 原值（去掉尾部斜杠）；未配置返回空串。"""
    return os.getenv('APP_BASE_URL', '').strip().rstrip('/')


def base_url() -> str:
    """站点根地址：邮件、分享页、robots/sitemap 共用；未配置时用本机开发默认值。"""
    return configured_base_url() or DEFAULT_DEV_BASE_URL


def validate_production(app_env: str | None = None) -> list[str]:
    """返回阻塞启动的配置问题；空列表表示通过。"""
    if not is_production(app_env):
        return []
    errors: list[str] = []
    base = configured_base_url()
    if not base:
        errors.append('APP_BASE_URL 未配置：验证/重置邮件与分享链接会指向本机地址')
    else:
        parsed = urlsplit(base)
        if parsed.scheme != 'https':
            errors.append('APP_BASE_URL 必须是 https 地址')
        if not parsed.netloc:
            errors.append('APP_BASE_URL 缺少主机名')
        elif (parsed.hostname or '').lower() in _LOCAL_HOSTS:
            errors.append('APP_BASE_URL 不能指向 localhost/127.0.0.1')
    cookie = os.getenv('COOKIE_SECURE')
    if cookie is not None and cookie.strip().lower() not in ('', 'true'):
        errors.append(f'COOKIE_SECURE 在 production 只能留空或设为 true（当前为 {cookie.strip()!r}）')
    return errors


def validate_startup() -> None:
    """生产配置不安全时直接拒绝启动，避免带病上线。"""
    errors = validate_production()
    if errors:
        raise RuntimeError('生产配置不安全：' + '；'.join(errors))
