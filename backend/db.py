import logging
import os
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                       UniqueConstraint, create_engine, event, inspect, text)
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .services.env import env_float, env_int

logger = logging.getLogger(__name__)

def _pragmas(connection, _record) -> None:
    """每条连接都开 WAL 与忙等待：读不阻塞写，锁冲突先等而不是立刻 500。"""
    cursor = connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute(f'PRAGMA busy_timeout={env_int("SQLITE_BUSY_TIMEOUT_MS", 5000, minimum=0)}')
        cursor.execute('PRAGMA synchronous=NORMAL')
    finally:
        cursor.close()

def configure_engine(target) -> None:
    """给 SQLite engine 挂上 PRAGMA 监听；内存库的 journal_mode 会保持 memory，不影响测试。"""
    if target.dialect.name != 'sqlite' or event.contains(target, 'connect', _pragmas):
        return
    event.listen(target, 'connect', _pragmas)

DEFAULT_DATABASE_URL = 'sqlite:///./trip.db'
# Alembic 初始迁移建出的业务表：PostgreSQL 启动时缺一张就说明迁移没跑完或没跑。
CORE_TABLES = ('users', 'account_tokens', 'trips', 'trip_collaborators',
               'trip_invites', 'share_links', 'trip_budgets', 'expenses', 'user_memories',
               'trip_reports', 'analytics_daily')
POSTGRES_POOL_RECYCLE = 1800
POSTGRES_CONNECT_TIMEOUT = 5
POSTGRES_APPLICATION_NAME = 'xingji-api'
POSTGRES_STATEMENT_TIMEOUT_MS = 15000

def _dialect_of(target) -> str:
    """从 URL 字符串 / URL 对象 / Engine 里取方言名，只做分支判断，不建立连接。"""
    url = getattr(target, 'url', target)
    backend = getattr(url, 'get_backend_name', None)
    if callable(backend):
        return str(backend()).lower()
    raw = str(url or '').strip().lower()
    return raw.split('://', 1)[0].split('+', 1)[0] if '://' in raw else ''

def is_sqlite(target) -> bool:
    """SQLite 是本地开发/测试后端：自动建表 + ensure_schema 增量补列。"""
    return _dialect_of(target) == 'sqlite'

def is_postgres(target) -> bool:
    """PostgreSQL 是生产后端：schema 只由 Alembic 管理（postgresql+psycopg://...）。"""
    return _dialect_of(target).startswith('postgres')

def _engine_options(url: str) -> dict:
    """连接池参数按方言给默认值；内存测试库不要套 QueuePool 参数。"""
    if is_postgres(url):
        # 生产池刻意保守：闪断靠 pre_ping 换连接，排队超时就让请求快速失败，不在数据库上堆连接。
        return {
            'pool_pre_ping': True,
            'pool_size': env_int('DB_POOL_SIZE', 5, minimum=1),
            'max_overflow': env_int('DB_MAX_OVERFLOW', 5, minimum=0),
            'pool_timeout': env_float('DB_POOL_TIMEOUT', 10.0, minimum=0.1),
            'pool_recycle': POSTGRES_POOL_RECYCLE,
            'connect_args': {
                'connect_timeout': POSTGRES_CONNECT_TIMEOUT,
                'application_name': POSTGRES_APPLICATION_NAME,
                # 单条语句 15 秒上限：慢查询在数据库侧被掐断，不会占满连接池。
                'options': f'-c statement_timeout={POSTGRES_STATEMENT_TIMEOUT_MS}',
            },
        }
    options: dict = {'pool_pre_ping': True}
    pool_size = env_int('DB_POOL_SIZE', 10, minimum=1)
    max_overflow = env_int('DB_MAX_OVERFLOW', 20, minimum=0)
    pool_timeout = env_float('DB_POOL_TIMEOUT', 15.0, minimum=0.1)
    if is_sqlite(url):
        options['connect_args'] = {'check_same_thread': False}
        # sqlite://（空库名）、sqlite:///:memory: 都用 SingletonThreadPool，套 QueuePool 参数会直接报错。
        database = url.split('://', 1)[1] if '://' in url else ''
        is_memory = database in ('', ':memory:') or ':memory:' in database
        if not is_memory:
            options.update(pool_size=pool_size, max_overflow=max_overflow,
                           pool_timeout=pool_timeout, pool_recycle=1800)
    else:
        options.update(pool_size=pool_size, max_overflow=max_overflow,
                       pool_timeout=pool_timeout, pool_recycle=1800)
    return options

_DATABASE_URL = os.getenv('DATABASE_URL', DEFAULT_DATABASE_URL)
engine = create_engine(_DATABASE_URL, **_engine_options(_DATABASE_URL))
configure_engine(engine)
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    # 账户体系后加的列：旧库由 ensure_schema 增量 ALTER。邮箱唯一性用部分唯一索引：
    # NULL（未填/未验证）不参与唯一性，与 Alembic 0001 的定义保持一致。
    email: Mapped[str | None] = mapped_column(String(254))
    pending_email: Mapped[str | None] = mapped_column(String(254))
    email_verified_at: Mapped[str | None] = mapped_column(String(32))
    accepted_terms_at: Mapped[str | None] = mapped_column(String(32))
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0', default=0)
    # 会话随机盐：绑定「这一行用户」而不是只绑定 id，防止 SQLite 主键复用后旧 cookie 接管新账号。
    session_nonce: Mapped[str] = mapped_column(String(64), nullable=False, server_default='', default='')
    # 全局记忆总开关：关掉后不再抽取/注入，已有记忆保留。迁移里 server_default 用 true（PG 的 boolean 不接受 '1'）。
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'), default=True)
    __table_args__ = (
        Index('ix_users_email', 'email', unique=True,
              sqlite_where=text('email IS NOT NULL'),
              postgresql_where=text('email IS NOT NULL')),
    )

class AccountToken(Base):
    """邮箱验证/换绑/重置密码的一次性 token：只存 sha256，明文仅出现在邮件链接里。"""
    __tablename__ = 'account_tokens'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[str] = mapped_column(String(32))
    used_at: Mapped[str | None] = mapped_column(String(32))

class Trip(Base):
    __tablename__ = 'trips'
    # AUTOINCREMENT 让主键永不复用：过期清理删掉最高 id 后，新行程也不会继承旧协作者/旧邀请。
    # 复合索引覆盖“我的行程”与广场列表最常见的过滤条件，避免用户量上来后全表扫。
    __table_args__ = (
        Index('ix_trips_user_deleted', 'user_id', 'deleted_at'),
        Index('ix_trips_public_deleted', 'is_public', 'deleted_at'),
        {'sqlite_autoincrement': True},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    city: Mapped[str] = mapped_column(String(80))
    data: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(120))
    deleted_at: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0', default=0)
    is_public: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0', default=0)
    # 最近一次保存的人与时间：冲突弹层据此说明“线上版本最近由谁保存”，不替代逐字段 diff。
    last_edited_by: Mapped[str | None] = mapped_column(String(80))
    last_edited_at: Mapped[str | None] = mapped_column(String(32))
    # 分享码：8 位大写字母+数字（去掉易混字符），朋友输入它加入协作；空值表示未启用。
    # 唯一性由唯一索引兜底：并发下撞码时后提交的一次会失败，由 services/join_codes 换码重试。
    join_code: Mapped[str | None] = mapped_column(String(8), unique=True, index=True)

class TripCollaborator(Base):
    """可编辑协作者：接受邀请后建立，行程对成员可读写。"""
    __tablename__ = 'trip_collaborators'
    __table_args__ = (UniqueConstraint('trip_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey('trips.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(20), default='edit')
    created_at: Mapped[str] = mapped_column(String(32))

class TripInvite(Base):
    """一次性协作邀请令牌（只存哈希，接受后生成协作者记录）。"""
    __tablename__ = 'trip_invites'
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey('trips.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    # 过期时间（ISO/UTC）：老库由 ensure_schema 补列，历史行留空按 created_at + 7 天推算。
    expires_at: Mapped[str | None] = mapped_column(String(32))

class ShareLink(Base):
    __tablename__ = 'share_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey('trips.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 撤销时间（ISO/UTC）：非空即失效；撤销保留记录，便于排查旧链接。
    revoked_at: Mapped[str | None] = mapped_column(String(32))

class TripBudget(Base):
    __tablename__ = 'trip_budgets'
    trip_id: Mapped[int] = mapped_column(ForeignKey('trips.id'), primary_key=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Expense(Base):
    __tablename__ = 'expenses'
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey('trips.id'), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(20))
    expense_date: Mapped[str] = mapped_column(String(10))
    place_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default='')

def _utcnow() -> datetime:
    """UTC naive：DateTime 列在 SQLite/PostgreSQL 都不带时区，统一存 UTC 裸时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class UserMemory(Base):
    """跨会话的全局记忆：同一 (user, category, key) 只保留一个生效版本。

    唯一性用部分唯一索引 uq_user_memories_key 表达（只约束 superseded_at IS NULL 的行）：
    值变了要把旧行留档再插新行，全量唯一约束会和这条历史保留策略直接冲突。
    """
    __tablename__ = 'user_memories'
    __table_args__ = (
        Index('uq_user_memories_key', 'user_id', 'category', 'key', unique=True,
              sqlite_where=text('superseded_at IS NULL'),
              postgresql_where=text('superseded_at IS NULL')),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False, default='')
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default='')
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

class AnalyticsDaily(Base):
    """首方产品事件日计数：只存「哪一天、哪个事件、发生几次」，不含用户、IP、行程或内容。

    不引入第三方 SDK：注册/登录/生成/保存/分享/fork 都在服务端已知结果后记录，
    因此不需要浏览器上报，也不会被前端脚本误触发或广告拦截。
    """
    __tablename__ = 'analytics_daily'
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0')

class TripReport(Base):
    """UGC 举报：内容下架后仍保留审计记录，因此 trip_id/reporter_user_id 有意不设外键。"""
    __tablename__ = 'trip_reports'
    __table_args__ = (
        Index('ix_trip_reports_status_created', 'status', 'created_at'),
        # 同一用户对同一行程只保留一条待处理举报：并发重复提交由该部分唯一索引兜底，
        # 运营处理完（status 不再是 pending）后同一用户仍可再次举报。
        Index('uq_trip_reports_pending_reporter', 'trip_id', 'reporter_user_id', unique=True,
              sqlite_where=text("status = 'pending' AND reporter_user_id IS NOT NULL"),
              postgresql_where=text("status = 'pending' AND reporter_user_id IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trip_title: Mapped[str | None] = mapped_column(String(120))
    trip_city: Mapped[str] = mapped_column(String(80), nullable=False)
    reporter_user_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default='')
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='plaza')
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(String(32))
    resolution: Mapped[str] = mapped_column(String(200), nullable=False, default='')

def _add_columns(target_engine, table: str, statements: dict) -> None:
    """给已有表补缺失列：表不存在或列已存在就跳过，并发启动撞上的重复列视为已迁移。"""
    inspector = inspect(target_engine)
    if table not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns(table)}
    for name, stmt in statements.items():
        if name in cols:
            continue
        try:
            with target_engine.begin() as conn:
                conn.execute(stmt)
        except OperationalError as exc:
            # 多 worker 并发启动时另一进程可能已加列：重复列视为已迁移，其它错误照常抛出。
            if 'duplicate column' in str(exc).lower():
                continue
            if name not in {c['name'] for c in inspect(target_engine).get_columns(table)}:
                raise

def _mask_email(value: str) -> str:
    """日志与异常里只留首字母和域名，避免把完整邮箱写出去。"""
    local, _, domain = (value or '').strip().partition('@')
    if not domain:
        return '***'
    return f'{local[:1] or "*"}***@{domain}'

def _ensure_users_schema(target_engine) -> None:
    """users 是账户体系的地基：即使旧库还没有 trips 表也要补列并建邮箱唯一索引。"""
    _add_columns(target_engine, 'users', {
        'email': text("ALTER TABLE users ADD COLUMN email VARCHAR(254)"),
        'pending_email': text("ALTER TABLE users ADD COLUMN pending_email VARCHAR(254)"),
        'email_verified_at': text("ALTER TABLE users ADD COLUMN email_verified_at VARCHAR(32)"),
        'accepted_terms_at': text("ALTER TABLE users ADD COLUMN accepted_terms_at VARCHAR(32)"),
        'session_version': text("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"),
        'session_nonce': text("ALTER TABLE users ADD COLUMN session_nonce VARCHAR(64) NOT NULL DEFAULT ''"),
        # SQLite 的 ALTER 只认常量字面量，用 1 而不是 true；旧库的历史用户默认开启记忆。
        'memory_enabled': text('ALTER TABLE users ADD COLUMN memory_enabled BOOLEAN NOT NULL DEFAULT 1'),
    })
    if 'users' not in inspect(target_engine).get_table_names():
        return
    with target_engine.connect() as conn:
        duplicates = conn.execute(text(
            'SELECT email, COUNT(*) FROM users WHERE email IS NOT NULL GROUP BY email HAVING COUNT(*) > 1'
        )).all()
    if duplicates:
        masked = ', '.join(_mask_email(row[0]) for row in duplicates)
        # 唯一索引建不起来就不能静默跳过，否则邮箱唯一性形同虚设：直接让启动失败。
        logger.error('users.email 存在重复值，无法创建唯一索引：%s', masked)
        raise RuntimeError(f'users.email 存在重复值，无法创建唯一索引：{masked}')
    with target_engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email) WHERE email IS NOT NULL"))

def ensure_schema(target_engine=engine) -> None:
    """create_all 不会给已有表加列；对旧 trip.db 做增量 ALTER（只加列、不动数据）。"""
    if not is_sqlite(target_engine):
        # PostgreSQL 的表结构只由 Alembic 管：下面全是 SQLite 方言的 ALTER/PRAGMA。
        raise RuntimeError('ensure_schema 只能用于 SQLite；PostgreSQL schema 由 `alembic upgrade head` 管理')
    _ensure_users_schema(target_engine)
    if 'trips' not in inspect(target_engine).get_table_names():
        return
    _add_columns(target_engine, 'trips', {
        'title': text("ALTER TABLE trips ADD COLUMN title VARCHAR(120)"),
        'deleted_at': text("ALTER TABLE trips ADD COLUMN deleted_at VARCHAR(32)"),
        'version': text("ALTER TABLE trips ADD COLUMN version INTEGER DEFAULT 0"),
        'is_public': text("ALTER TABLE trips ADD COLUMN is_public INTEGER DEFAULT 0"),
        'last_edited_by': text("ALTER TABLE trips ADD COLUMN last_edited_by VARCHAR(80)"),
        'last_edited_at': text("ALTER TABLE trips ADD COLUMN last_edited_at VARCHAR(32)"),
        'join_code': text("ALTER TABLE trips ADD COLUMN join_code VARCHAR(8)"),
    })
    # create_all 不会给已有表补索引：旧库启动时补建，重复执行无副作用。
    for statement in (
        'CREATE INDEX IF NOT EXISTS ix_trips_user_deleted ON trips (user_id, deleted_at)',
        'CREATE INDEX IF NOT EXISTS ix_trips_public_deleted ON trips (is_public, deleted_at)',
        # 分享码唯一索引：SQLite/PostgreSQL 的唯一索引都允许多个 NULL，
        # 因此“未启用分享码”的历史行程不会互相冲突。
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_trips_join_code ON trips (join_code)',
    ):
        with target_engine.begin() as conn:
            conn.execute(text(statement))
    # 邀请过期与分享撤销是后加的能力：只补列，历史行保持 NULL 由业务层兜底推算。
    _add_columns(target_engine, 'trip_invites', {
        'expires_at': text("ALTER TABLE trip_invites ADD COLUMN expires_at VARCHAR(32)"),
    })
    _add_columns(target_engine, 'share_links', {
        'revoked_at': text("ALTER TABLE share_links ADD COLUMN revoked_at VARCHAR(32)"),
    })

def assert_supported_database(target=None, app_env: str | None = None) -> None:
    """生产环境禁止 SQLite：容器/多进程下没有可靠的并发写、在线备份与迁移语义。

    APP_ENV 未设置（本地开发、pytest）时不受影响，正常走 SQLite 分支。
    """
    target = engine if target is None else target
    env = (app_env if app_env is not None else os.getenv('APP_ENV', '')).strip().lower()
    if env == 'production' and is_sqlite(target):
        raise RuntimeError(
            'APP_ENV=production 时禁止使用 SQLite：请把 DATABASE_URL 指向 PostgreSQL'
            '（postgresql+psycopg://<user>:<password>@<host>:5432/<database>），'
            '并在部署时执行 `alembic upgrade head`。'
        )


def verify_postgres_schema(target_engine) -> None:
    """PostgreSQL 启动只做校验：不自动建表、不自动改表，schema 一律来自 Alembic。"""
    try:
        tables = set(inspect(target_engine).get_table_names())
    except SQLAlchemyError as exc:
        raise RuntimeError(
            '无法连接 PostgreSQL 或读取表清单：请确认数据库已启动、DATABASE_URL 正确，'
            '并已执行 `alembic upgrade head`。'
        ) from exc
    if 'alembic_version' not in tables:
        raise RuntimeError(
            'PostgreSQL 数据库尚未初始化（缺少 alembic_version 表）：'
            '请在项目根目录执行 `alembic upgrade head` 后再启动服务。'
        )
    missing = [name for name in CORE_TABLES if name not in tables]
    if missing:
        raise RuntimeError(
            f'PostgreSQL 数据库缺少核心表：{", ".join(missing)}。'
            '请执行 `alembic upgrade head` 完成迁移后再启动服务。'
        )


def prepare_database(target_engine=None) -> None:
    """启动时的 schema 准备：SQLite 自动建表+补列；PostgreSQL 只校验迁移是否已执行。"""
    target = engine if target_engine is None else target_engine
    assert_supported_database(target)
    if is_postgres(target):
        verify_postgres_schema(target)
        return
    Base.metadata.create_all(target)
    ensure_schema(target)
