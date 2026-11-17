#!/usr/bin/env python3
"""公开上线前的配置/环境自检。

用途：在部署机上、启动服务之前跑一遍，把「代码没问题但配置缺失」这一类
上线事故挡在发布前。检查只读、不发送邮件、不调用模型/高德、不改数据库（备份目录缺失时会建空目录）。

用法：
    python scripts/launch_preflight.py
    python scripts/launch_preflight.py --env-file /etc/xingji/trip.env
    python scripts/launch_preflight.py --skip-db

退出码 0 表示必检项全部通过；1 表示存在必检项失败。
所有输出都不包含密码、密钥或 token，只展示「已配置/未配置/长度/域名」。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = PROJECT_ROOT / 'backups'
DEFAULT_DIST = PROJECT_ROOT / 'frontend' / 'dist'
VERSIONS_DIR = PROJECT_ROOT / 'alembic' / 'versions'

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
LOCAL_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1'}

# 生产必检项：任何一项失败都不应公开上线。
REQUIRED_NAMES = {
    'APP_ENV',
    'APP_BASE_URL',
    'COOKIE_SECURE',
    'DATABASE_URL',
    'SESSION_SECRET',
    'ADMIN_TOKEN',
    'SMTP_HOST',
    'SMTP_FROM',
    'SMTP_SECURITY',
    'SUPPORT_EMAIL',
    'OPERATOR_NAME',
    'OPERATOR_CONTACT_EMAIL',
    'OPERATOR_JURISDICTION',
    'AMAP_WEB_KEY',
    'AMAP_JS_KEY',
    'LLM_API_KEY',
    'FRONTEND_BUILD',
}


def _value(env: dict[str, str], name: str) -> str:
    return (env.get(name) or '').strip()


def _add(checks: list[dict], name: str, ok: bool, detail: str, required: bool | None = None) -> None:
    checks.append({
        'name': name,
        'ok': bool(ok),
        'detail': detail,
        'required': REQUIRED_NAMES.issuperset({name}) if required is None else required,
    })


def validate_environment(env: dict[str, str]) -> list[dict]:
    """校验生产配置；返回逐项结果，不读取任何外部服务。兼容 dict/osenviron。"""
    checks: list[dict] = []
    app_env = _value(env, 'APP_ENV').lower()
    _add(checks, 'APP_ENV', app_env == 'production',
         'production' if app_env == 'production' else '应为 production')

    base_url = _value(env, 'APP_BASE_URL')
    parsed = urlsplit(base_url) if base_url else None
    base_ok = bool(
        parsed
        and parsed.scheme == 'https'
        and parsed.hostname
        and parsed.hostname.lower() not in LOCAL_HOSTS
    )
    host = parsed.hostname if parsed else ''
    _add(checks, 'APP_BASE_URL', base_ok, f'https 公网地址（host={host or "空"}）')

    # 与 backend/services/site_config.py 保持同一口径：只接受留空或 true。
    cookie_secure = _value(env, 'COOKIE_SECURE').lower()
    cookie_ok = cookie_secure in ('', 'true')
    _add(checks, 'COOKIE_SECURE', cookie_ok,
         '留空（按 https 自动开启）或 true' if cookie_ok else '只接受留空或 true；false/1/0/no 都会拒绝启动')

    database_url = _value(env, 'DATABASE_URL').lower()
    db_ok = database_url.startswith('postgres')
    _add(checks, 'DATABASE_URL', db_ok,
         'PostgreSQL' if db_ok else '必须使用 PostgreSQL（APP_ENV=production 禁止 SQLite）')

    session_secret = _value(env, 'SESSION_SECRET')
    _add(checks, 'SESSION_SECRET', len(session_secret) >= 32,
         f'已配置（长度 {len(session_secret)}）' if session_secret else '未配置；生产应显式设置 32 字节以上随机值')

    admin_token = _value(env, 'ADMIN_TOKEN')
    _add(checks, 'ADMIN_TOKEN', len(admin_token) >= 32,
         f'已配置（长度 {len(admin_token)}）' if admin_token else '未配置；运营/监控端点会返回 404')

    smtp_host = _value(env, 'SMTP_HOST')
    smtp_from = _value(env, 'SMTP_FROM')
    smtp_security = _value(env, 'SMTP_SECURITY').lower() or 'starttls'
    _add(checks, 'SMTP_HOST', bool(smtp_host), '已配置' if smtp_host else '未配置；验证与找回邮件不会发送')
    _add(checks, 'SMTP_FROM', bool(smtp_from), '已配置' if smtp_from else '未配置发件地址')
    _add(checks, 'SMTP_SECURITY', smtp_security in {'ssl', 'starttls'},
         smtp_security if smtp_security in {'ssl', 'starttls'} else '生产必须为 ssl 或 starttls')
    smtp_user = _value(env, 'SMTP_USER')
    smtp_password = _value(env, 'SMTP_PASSWORD')
    _add(checks, 'SMTP_AUTH', bool(smtp_user) == bool(smtp_password),
         '用户名与密码成对配置' if bool(smtp_user) == bool(smtp_password) else '用户名与密码必须同时配置',
         required=False)

    support_email = _value(env, 'SUPPORT_EMAIL')
    _add(checks, 'SUPPORT_EMAIL', bool(EMAIL_RE.match(support_email)),
         '已配置' if EMAIL_RE.match(support_email) else '未配置或格式不合法；反馈入口会隐藏')

    operator_name = _value(env, 'OPERATOR_NAME')
    operator_contact = _value(env, 'OPERATOR_CONTACT_EMAIL')
    operator_jurisdiction = _value(env, 'OPERATOR_JURISDICTION')
    _add(checks, 'OPERATOR_NAME', bool(operator_name), '已配置' if operator_name else '未配置；条款/隐私页仍显示演示版')
    _add(checks, 'OPERATOR_CONTACT_EMAIL', bool(EMAIL_RE.match(operator_contact)),
         '已配置' if EMAIL_RE.match(operator_contact) else '未配置或格式不合法')
    _add(checks, 'OPERATOR_JURISDICTION', bool(operator_jurisdiction),
         '已配置' if operator_jurisdiction else '未配置管辖地')
    _add(checks, 'ICP_NUMBER', bool(_value(env, 'ICP_NUMBER')),
         '已配置' if _value(env, 'ICP_NUMBER') else '未配置备案号（如适用，上线前补）',
         required=False)

    _add(checks, 'AMAP_WEB_KEY', bool(_value(env, 'AMAP_WEB_KEY')), '已配置' if _value(env, 'AMAP_WEB_KEY') else '未配置；地点搜索/路线不可用')
    _add(checks, 'AMAP_JS_KEY', bool(_value(env, 'AMAP_JS_KEY')), '已配置' if _value(env, 'AMAP_JS_KEY') else '未配置；浏览器地图不可用')
    _add(checks, 'AMAP_JS_SECURITY_CODE', bool(_value(env, 'AMAP_JS_SECURITY_CODE')),
         '已配置' if _value(env, 'AMAP_JS_SECURITY_CODE') else '未配置安全密钥（高德新 Key 需要）',
         required=False)

    llm_key = _value(env, 'LLM_API_KEY') or _value(env, 'DEEPSEEK_API_KEY')
    llm_model = _value(env, 'LLM_MODEL') or _value(env, 'DEEPSEEK_MODEL')
    _add(checks, 'LLM_API_KEY', bool(llm_key), '已配置' if llm_key else '未配置；AI 生成不可用')
    _add(checks, 'LLM_MODEL', bool(llm_model), llm_model or '未配置模型名')
    return checks


def alembic_head(versions_dir: Path = VERSIONS_DIR) -> str:
    """从迁移文件解析当前 head；不 import alembic，避免部署机 Python 环境差异。"""
    revisions: dict[str, str | None] = {}
    for path in sorted(versions_dir.glob('*.py')):
        text = path.read_text(encoding='utf-8')
        match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
        if not match:
            continue
        parent = re.search(r"^down_revision\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", text, re.MULTILINE)
        revisions[match.group(1)] = parent.group(1) if parent and parent.group(1) else None
    parents = {value for value in revisions.values() if value}
    heads = sorted(name for name in revisions if name not in parents)
    # 多 head 说明迁移链分叉，期望版本不唯一：返回空串让 DATABASE 必检项失败，而不是猜一个。
    return heads[0] if len(heads) == 1 else ''


def check_frontend_build(dist_dir: Path = DEFAULT_DIST) -> dict:
    index = dist_dir / 'index.html'
    assets = dist_dir / 'assets'
    scripts = list(assets.glob('*.js')) if assets.is_dir() else []
    styles = list(assets.glob('*.css')) if assets.is_dir() else []
    ok = index.is_file() and bool(scripts) and bool(styles)
    detail = f'{len(scripts)} 个 JS / {len(styles)} 个 CSS' if ok else '缺少 frontend/dist/index.html 或 assets 构建产物'
    return {'name': 'FRONTEND_BUILD', 'ok': ok, 'detail': detail, 'required': True}


def check_backup_dir(backup_dir: Path = DEFAULT_BACKUP_DIR, min_free_bytes: int = 1024 ** 3) -> list[dict]:
    """备份目录必须可写且有足够空间；只创建目录，不写测试文件。"""
    checks: list[dict] = []
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        writable = os.access(backup_dir, os.W_OK)
        detail = str(backup_dir) if writable else f'{backup_dir} 不可写'
    except OSError as exc:
        writable = False
        detail = f'{backup_dir} 无法创建（{type(exc).__name__}）'
    checks.append({'name': 'BACKUP_DIR', 'ok': writable, 'detail': detail, 'required': True})

    try:
        usage = shutil.disk_usage(backup_dir if writable else PROJECT_ROOT)
        free = usage.free >= min_free_bytes
        checks.append({
            'name': 'DISK_FREE',
            'ok': free,
            'detail': f'{usage.free / (1024 ** 3):.1f} GB 可用（建议 ≥1 GB）',
            'required': False,
        })
    except OSError:
        checks.append({'name': 'DISK_FREE', 'ok': False, 'detail': '无法读取磁盘空间', 'required': False})
    return checks


def parse_database_url(url: str) -> dict:
    """只提取 psql 需要的连接字段，不保留密码明文。"""
    raw = url.replace('postgresql+psycopg://', 'postgresql://').replace('postgresql+psycopg2://', 'postgresql://')
    parsed = urlsplit(raw)
    if parsed.scheme not in {'postgres', 'postgresql'} or not parsed.hostname:
        raise ValueError('不是可识别的 PostgreSQL 连接串')
    query = dict(part.split('=', 1) for part in parsed.query.split('&') if '=' in part)
    return {
        'host': parsed.hostname,
        'port': str(parsed.port or 5432),
        'user': unquote(parsed.username or ''),
        'password': unquote(parsed.password or ''),
        'database': parsed.path.lstrip('/') or 'postgres',
        'sslmode': query.get('sslmode', ''),
    }


def check_database(database_url: str, head: str, psql: str = 'psql') -> dict:
    """用 psql 只读校验连接与 alembic 版本；不打印密码。"""
    try:
        settings = parse_database_url(database_url)
    except ValueError as exc:
        return {'name': 'DATABASE', 'ok': False, 'detail': str(exc), 'required': True}
    executable = shutil.which(psql)
    if not executable:
        return {'name': 'DATABASE', 'ok': False, 'detail': '找不到 psql 客户端', 'required': True}
    env = dict(os.environ)
    if settings['password']:
        env['PGPASSWORD'] = settings['password']
    if settings['sslmode']:
        env['PGSSLMODE'] = settings['sslmode']
    command = [
        executable,
        '-h', settings['host'],
        '-p', settings['port'],
        '-U', settings['user'],
        '-d', settings['database'],
        '-tAc', 'SELECT version_num FROM alembic_version',
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'name': 'DATABASE', 'ok': False, 'detail': f'连接失败（{type(exc).__name__}）', 'required': True}
    if result.returncode != 0:
        return {'name': 'DATABASE', 'ok': False, 'detail': '连接失败或缺少 alembic_version 表', 'required': True}
    current = result.stdout.strip()
    ok = bool(head) and current == head
    return {
        'name': 'DATABASE',
        'ok': ok,
        'detail': f'当前 {current or "空"} / 期望 {head or "未知"}',
        'required': True,
    }


def _print(checks: list[dict]) -> None:
    for item in checks:
        if item['ok']:
            mark = 'OK  '
        elif item['required']:
            mark = 'FAIL'
        else:
            mark = 'WARN'
        print(f'[{mark}] {item["name"]:<24} {item["detail"]}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='行迹 Trip 上线前自检')
    parser.add_argument('--env-file', default=str(PROJECT_ROOT / '.env'), help='要加载的 env 文件')
    parser.add_argument('--skip-db', action='store_true', help='跳过数据库连接检查')
    parser.add_argument('--backup-dir', default=str(DEFAULT_BACKUP_DIR), help='备份目录')
    parser.add_argument('--psql', default=os.getenv('PSQL_BIN', 'psql'), help='psql 可执行文件路径')
    args = parser.parse_args(argv)

    env_file = Path(args.env_file)
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    else:
        print(f'[WARN] 未找到 env 文件：{env_file}，只检查当前进程环境变量')

    checks = validate_environment(dict(os.environ))
    checks.append(check_frontend_build())
    checks.extend(check_backup_dir(Path(args.backup_dir)))
    if not args.skip_db:
        checks.append(check_database(_value(dict(os.environ), 'DATABASE_URL'), alembic_head(), args.psql))
    _print(checks)

    failed = [item for item in checks if item['required'] and not item['ok']]
    warned = [item for item in checks if not item['required'] and not item['ok']]
    print()
    print(f'必检 {len(checks) - len(warned)} 项，失败 {len(failed)} 项，提醒 {len(warned)} 项。')
    if failed:
        print('不能公开上线：请先修复 FAIL 项。')
        return 1
    print('必检项全部通过；仍请完成真实邮件、告警与恢复演练。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
