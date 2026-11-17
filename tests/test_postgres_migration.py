"""方案B 阶段1：PostgreSQL 16 + Alembic 的回归测试。

不依赖真实数据库的部分默认全跑：引擎参数分支、生产环境守卫、迁移文件与 ORM 元数据的一致性
（用临时 SQLite 文件执行 `alembic upgrade head` 后逐列比对）。
真实 PostgreSQL 的集成测试只在设置了 TEST_POSTGRES_URL 时执行，且必须指向一个可丢弃的库。
"""
import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from backend import db as app_db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / 'alembic.ini'
MIGRATION_FILE = PROJECT_ROOT / 'alembic' / 'versions' / '0001_initial.py'
POSTGRES_URL = 'postgresql+psycopg://trip:trip@127.0.0.1:5432/trip_test'
POSTGRES_TEST_URL = os.getenv('TEST_POSTGRES_URL', '').strip()

EXPECTED_INDEXES = {
    'ix_users_username': True,
    'ix_users_email': True,
    'ix_account_tokens_user_id': False,
    'ix_account_tokens_token_hash': True,
    'ix_trips_user_id': False,
    'ix_trips_user_deleted': False,
    'ix_trips_public_deleted': False,
    # 分享码唯一索引：8 位码全局唯一，未启用（NULL）的行不参与冲突。
    'ix_trips_join_code': True,
    'ix_trip_collaborators_trip_id': False,
    'ix_trip_collaborators_user_id': False,
    'ix_trip_invites_trip_id': False,
    'ix_trip_invites_token_hash': True,
    'ix_share_links_trip_id': False,
    'ix_share_links_token_hash': True,
    'ix_expenses_trip_id': False,
    # 全局记忆的 key 唯一是部分唯一索引：只约束未覆盖的行。
    'uq_user_memories_key': True,
    'ix_trip_reports_status_created': False,
    # 同一用户对同一行程的待处理举报唯一：只约束 pending 且举报人非空的行。
    'uq_trip_reports_pending_reporter': True,
}


def _alembic_config(url: str):
    """构造指向项目的 Alembic 配置；日志配置关掉，避免污染 pytest 的 logging。"""
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option('script_location', str(PROJECT_ROOT / 'alembic'))
    config.set_main_option('sqlalchemy.url', url.replace('%', '%%'))
    config.attributes['configure_logger'] = False
    return config


def _sqlite_engine(tmp_path: Path, name: str = 'schema.db'):
    url = f'sqlite:///{(tmp_path / name).as_posix()}'
    return url, create_engine(url)


def test_postgres_engine_options(monkeypatch):
    for key in ('DB_POOL_SIZE', 'DB_MAX_OVERFLOW', 'DB_POOL_TIMEOUT'):
        monkeypatch.delenv(key, raising=False)
    options = app_db._engine_options(POSTGRES_URL)
    assert options['pool_pre_ping'] is True
    assert options['pool_size'] == 5
    assert options['max_overflow'] == 5
    assert options['pool_timeout'] == 10
    assert options['pool_recycle'] == 1800
    assert options['connect_args'] == {
        'connect_timeout': 5,
        'application_name': 'xingji-api',
        'options': '-c statement_timeout=15000',
    }


def test_postgres_engine_options_respect_env_overrides(monkeypatch):
    monkeypatch.setenv('DB_POOL_SIZE', '8')
    monkeypatch.setenv('DB_MAX_OVERFLOW', '3')
    monkeypatch.setenv('DB_POOL_TIMEOUT', '7')
    options = app_db._engine_options(POSTGRES_URL)
    assert (options['pool_size'], options['max_overflow'], options['pool_timeout']) == (8, 3, 7.0)


def test_sqlite_engine_options_unchanged(monkeypatch):
    for key in ('DB_POOL_SIZE', 'DB_MAX_OVERFLOW', 'DB_POOL_TIMEOUT'):
        monkeypatch.delenv(key, raising=False)
    options = app_db._engine_options('sqlite:///./trip.db')
    assert options['connect_args'] == {'check_same_thread': False}
    assert (options['pool_size'], options['max_overflow'], options['pool_timeout']) == (10, 20, 15.0)
    # 内存库用的是 SingletonThreadPool，不能套 QueuePool 参数。
    memory = app_db._engine_options('sqlite://')
    assert 'pool_size' not in memory and memory['connect_args'] == {'check_same_thread': False}


def test_is_postgres_and_is_sqlite_helpers():
    assert app_db.is_postgres(POSTGRES_URL) and not app_db.is_sqlite(POSTGRES_URL)
    assert app_db.is_sqlite('sqlite:///./trip.db') and not app_db.is_postgres('sqlite:///./trip.db')
    assert app_db.is_sqlite('sqlite+pysqlite:///:memory:')
    # Engine 对象同样可判断（engine.url 是 URL 实例，不走字符串解析）。
    assert app_db.is_sqlite(create_engine('sqlite://'))


def test_ensure_schema_refuses_postgres():
    pytest.importorskip('psycopg')
    engine = create_engine(POSTGRES_URL)
    try:
        with pytest.raises(RuntimeError, match='SQLite'):
            app_db.ensure_schema(engine)
    finally:
        engine.dispose()


def test_assert_supported_database_rejects_sqlite_in_production():
    with pytest.raises(RuntimeError, match='APP_ENV=production'):
        app_db.assert_supported_database('sqlite:///./trip.db', app_env='production')
    # 非生产环境照常可用；生产 + PostgreSQL 也不会被拦。
    app_db.assert_supported_database('sqlite:///./trip.db', app_env='development')
    app_db.assert_supported_database('sqlite:///./trip.db', app_env=None)
    app_db.assert_supported_database(POSTGRES_URL, app_env='production')


def test_prepare_database_rejects_sqlite_in_production_before_creating_tables(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_ENV', 'production')
    url, engine = _sqlite_engine(tmp_path, 'prod.db')
    try:
        with pytest.raises(RuntimeError, match='APP_ENV=production'):
            app_db.prepare_database(engine)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_prepare_database_builds_sqlite_schema(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_ENV', 'development')
    url, engine = _sqlite_engine(tmp_path, 'dev.db')
    try:
        app_db.prepare_database(engine)
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert set(app_db.CORE_TABLES) <= tables


class _FakeInspector:
    def __init__(self, tables):
        self._tables = list(tables)

    def get_table_names(self):
        return list(self._tables)


def test_verify_postgres_schema_requires_alembic_version(monkeypatch, tmp_path):
    url, engine = _sqlite_engine(tmp_path, 'fake.db')
    try:
        monkeypatch.setattr(app_db, 'inspect', lambda target: _FakeInspector(['users', 'trips']))
        with pytest.raises(RuntimeError, match='alembic_version'):
            app_db.verify_postgres_schema(engine)

        monkeypatch.setattr(
            app_db, 'inspect',
            lambda target: _FakeInspector(list(app_db.CORE_TABLES) + ['alembic_version']),
        )
        app_db.verify_postgres_schema(engine)

        monkeypatch.setattr(
            app_db, 'inspect',
            lambda target: _FakeInspector(['alembic_version', 'users']),
        )
        with pytest.raises(RuntimeError, match='alembic upgrade head'):
            app_db.verify_postgres_schema(engine)
    finally:
        engine.dispose()


def test_migration_file_is_importable_and_chain_is_single_head():
    pytest.importorskip('alembic')
    spec = importlib.util.spec_from_file_location('trip_migration_0001', MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == '0001_initial'
    assert module.down_revision is None
    source = MIGRATION_FILE.read_text(encoding='utf-8')
    assert 'sqlite_autoincrement' not in source
    assert callable(module.upgrade) and callable(module.downgrade)

    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config('sqlite://'))
    assert script.get_heads() == ['0009_cleanup_dead_schema']
    assert script.get_current_head() == '0009_cleanup_dead_schema'
    base = script.get_revision('0001_initial')
    assert base.down_revision is None


def test_alembic_upgrade_matches_models(tmp_path):
    pytest.importorskip('alembic')
    from alembic import command

    url, engine = _sqlite_engine(tmp_path, 'alembic.db')
    try:
        command.upgrade(_alembic_config(url), 'head')
        inspector = inspect(engine)
        metadata = app_db.Base.metadata
        tables = set(inspector.get_table_names())
        assert tables == set(metadata.tables) | {'alembic_version'}

        for table in metadata.sorted_tables:
            migrated = {column['name']: column for column in inspector.get_columns(table.name)}
            assert set(migrated) == {column.name for column in table.columns}, table.name
            for column in table.columns:
                actual = migrated[column.name]
                assert actual['nullable'] == column.nullable, f'{table.name}.{column.name} 可空性不一致'
                assert actual['type'].compile(dialect=engine.dialect) == column.type.compile(
                    dialect=engine.dialect
                ), f'{table.name}.{column.name} 类型不一致'
                assert (actual['default'] is not None) == (
                    column.server_default is not None
                ), f'{table.name}.{column.name} 服务端默认值不一致'

        index_map = {}
        for table in metadata.sorted_tables:
            for index in inspector.get_indexes(table.name):
                index_map[index['name']] = bool(index['unique'])
        assert index_map == EXPECTED_INDEXES
        assert {index.name for table in metadata.sorted_tables for index in table.indexes} == set(EXPECTED_INDEXES)

        # users.email 必须是部分唯一索引：NULL（未填/未验证）不参与唯一性。
        with engine.connect() as connection:
            ddl = connection.execute(
                text("select sql from sqlite_master where type='index' and name='ix_users_email'")
            ).scalar_one()
        assert 'UNIQUE' in ddl.upper() and 'email IS NOT NULL' in ddl

        unique_constraints = inspector.get_unique_constraints('trip_collaborators')
        assert any(set(item['column_names']) == {'trip_id', 'user_id'} for item in unique_constraints)
        assert inspector.get_pk_constraint('trip_budgets')['constrained_columns'] == ['trip_id']
        assert {fk['referred_table'] for fk in inspector.get_foreign_keys('expenses')} == {'trips'}
    finally:
        engine.dispose()

    # 回滚到底应清掉全部业务表（alembic_version 由 Alembic 自己保留），空库可重复迁移。
    engine = create_engine(url)
    try:
        command.downgrade(_alembic_config(url), 'base')
        assert not set(app_db.CORE_TABLES) & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_env_py_reads_database_url(monkeypatch, tmp_path):
    """alembic.ini 里 sqlalchemy.url 留空：env.py 必须从 DATABASE_URL 拿到连接串。"""
    pytest.importorskip('alembic')
    from alembic import command
    from alembic.config import Config

    url = f'sqlite:///{(tmp_path / 'envurl.db').as_posix()}'
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option('script_location', str(PROJECT_ROOT / 'alembic'))
    config.set_main_option('sqlalchemy.url', '')
    config.attributes['configure_logger'] = False
    command.upgrade(config, 'head')

    engine = create_engine(url)
    try:
        assert set(app_db.CORE_TABLES) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_env_py_without_any_url_fails_loudly(monkeypatch, tmp_path):
    """既没有 env.py 注入也没有 DATABASE_URL 时必须报错，不能悄悄回退到 SQLite。"""
    monkeypatch.delenv('DATABASE_URL', raising=False)
    source = (PROJECT_ROOT / 'alembic' / 'env.py').read_text(encoding='utf-8')
    assert "os.getenv('DATABASE_URL')" in source
    assert 'raise RuntimeError' in source


@pytest.mark.skipif(not POSTGRES_TEST_URL, reason='未设置 TEST_POSTGRES_URL，跳过真实 PostgreSQL 集成测试')
def test_postgres_upgrade_head_end_to_end():
    """需要 TEST_POSTGRES_URL 指向一个可丢弃的库；会执行 alembic upgrade head 后回滚。"""
    pytest.importorskip('alembic')
    from alembic import command

    config = _alembic_config(POSTGRES_TEST_URL)
    engine = create_engine(POSTGRES_TEST_URL)
    try:
        command.upgrade(config, 'head')
        inspector = inspect(engine)
        tables = set(inspector.get_table_names(schema='public'))
        assert set(app_db.CORE_TABLES) <= tables
        assert 'alembic_version' in tables
        indexes = {item['name']: item for item in inspector.get_indexes('users', schema='public')}
        assert indexes['ix_users_email']['unique'] is True
        command.downgrade(config, 'base')
    finally:
        engine.dispose()


def test_db_reset_requires_explicit_yes(monkeypatch, tmp_path):
    """不带 --yes 只做预览：列出对象但不删文件、不改结构。"""
    from scripts import db_reset

    monkeypatch.delenv('APP_ENV', raising=False)
    url = f'sqlite:///{(tmp_path / 'reset-preview.db').as_posix()}'
    engine = create_engine(url)
    try:
        app_db.Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    assert db_reset.main(['--url', url]) == 0
    assert (tmp_path / 'reset-preview.db').exists()


def test_db_reset_rebuilds_sqlite_database(monkeypatch, tmp_path):
    from scripts import db_reset

    monkeypatch.setenv('APP_ENV', 'development')
    url = f'sqlite:///{(tmp_path / 'reset.db').as_posix()}'
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE legacy_only (id INTEGER PRIMARY KEY)'))
    finally:
        engine.dispose()

    assert db_reset.main(['--url', url, '--yes']) == 0

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert 'legacy_only' not in tables
    assert set(app_db.CORE_TABLES) <= tables


def test_db_reset_refuses_production_without_force(monkeypatch, tmp_path):
    from scripts import db_reset

    monkeypatch.setenv('APP_ENV', 'production')
    url = f'sqlite:///{(tmp_path / 'prod.db').as_posix()}'
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE keep_me (id INTEGER PRIMARY KEY)'))
    finally:
        engine.dispose()

    assert db_reset.main(['--url', url, '--yes']) == 2
    engine = create_engine(url)
    try:
        assert 'keep_me' in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    # --force 是唯一出口（重置生产库属于事故级操作，必须显式二次确认）。
    assert db_reset.main(['--url', url, '--yes', '--force']) == 0


def test_db_reset_masks_password():
    from scripts import db_reset

    masked = db_reset.masked('postgresql+psycopg://trip:s3cret@127.0.0.1:5432/trip')
    assert 's3cret' not in masked
    assert masked.startswith('postgresql+psycopg://trip:***@127.0.0.1:5432/trip')

