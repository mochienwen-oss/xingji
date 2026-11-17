"""Alembic 运行环境：连接串只从 DATABASE_URL（或调用方显式注入的 sqlalchemy.url）读取。

生产 PostgreSQL 的 schema 全部由 `alembic upgrade head` 建立，应用启动不会 create_all。
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 本地开发习惯：项目根 .env 里的 DATABASE_URL 生效（已存在的环境变量优先）。
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv 是应用依赖，缺失不影响迁移
    pass
else:
    load_dotenv(PROJECT_ROOT / '.env')

from backend.db import Base  # noqa: E402  (需要先把项目根放进 sys.path)

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """显式配置优先（脚本/测试注入），其次环境变量；两者都没有直接失败，不悄悄回退 SQLite。"""
    configured = (config.get_main_option('sqlalchemy.url') or '').strip()
    if configured:
        return configured
    url = (os.getenv('DATABASE_URL') or '').strip()
    if not url:
        raise RuntimeError(
            '未找到数据库连接串：请设置环境变量 DATABASE_URL，例如 '
            'postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database> '
            '（本地开发可用 sqlite:///./trip.db）。'
        )
    return url


def _configure_logging() -> None:
    if config.config_file_name is None:
        return
    if not config.attributes.get('configure_logger', True):
        return
    if not Path(config.config_file_name).exists():
        return
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库（--sql）。"""
    url = _database_url()
    _configure_logging()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    _configure_logging()
    section = config.get_section(config.config_ini_section, {})
    # engine_from_config 对配置值做插值：URL 里的 % 必须转义。
    section['sqlalchemy.url'] = url.replace('%', '%%')
    connectable = engine_from_config(section, prefix='sqlalchemy.', poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
