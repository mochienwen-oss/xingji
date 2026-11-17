"""P1：ensure_schema 可重复/并发执行，SQLite 连接开 WAL 与 5 秒忙等待。"""
import threading

import pytest

from sqlalchemy import create_engine, inspect
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.pool import StaticPool

import backend.db as app_db


def test_ensure_schema_twice_on_file_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    app_db.configure_engine(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE trips (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, city VARCHAR(80), data TEXT)')
    app_db.ensure_schema(engine)
    app_db.ensure_schema(engine)  # 第二次执行不能抛
    cols = {c['name'] for c in inspect(engine).get_columns('trips')}
    assert {'title', 'deleted_at', 'version', 'is_public'} <= cols
    engine.dispose()


def test_ensure_schema_concurrent_startup(tmp_path):
    """模拟多 worker 同时启动：重复加列被吞掉，不能有异常冒出来。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={'check_same_thread': False})
    app_db.configure_engine(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE trips (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, city VARCHAR(80), data TEXT)')
    failures = []
    def migrate():
        try:
            app_db.ensure_schema(engine)
        except Exception as exc:  # noqa: BLE001 - 测试要看到任何异常
            failures.append(exc)
    threads = [threading.Thread(target=migrate) for _ in range(3)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert failures == []
    cols = {c['name'] for c in inspect(engine).get_columns('trips')}
    assert {'title', 'deleted_at', 'version', 'is_public'} <= cols
    engine.dispose()


def test_ensure_schema_swallows_duplicate_column(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'dup.db'}")
    app_db.Base.metadata.create_all(engine)  # 表已是最新结构

    class Blind:
        """谎报 trips 没有新列，逼 4 条 ALTER 全部撞上 duplicate column。"""
        def get_table_names(self): return ['trips']
        def get_columns(self, name): return [{'name': 'id'}]

    monkeypatch.setattr(app_db, 'inspect', lambda target: Blind())
    app_db.ensure_schema(engine)  # 不应抛出
    columns = {c['name'] for c in sa_inspect(engine).get_columns('trips')}
    assert {'title', 'deleted_at', 'version', 'is_public'} <= columns, '吞掉重复列错误后表结构不能被破坏'
    engine.dispose()


def test_ensure_schema_adds_invite_and_share_columns_without_data_loss(tmp_path):
    """旧库只有两列时增量 ALTER 加列，且已有邀请/分享数据原样保留。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    app_db.configure_engine(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE trips (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, city VARCHAR(80), data TEXT)')
        conn.exec_driver_sql('CREATE TABLE trip_invites (id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER, token_hash VARCHAR(64) NOT NULL UNIQUE, created_at VARCHAR(32) NOT NULL)')
        conn.exec_driver_sql('CREATE TABLE share_links (id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER, token_hash VARCHAR(64) NOT NULL UNIQUE)')
        conn.exec_driver_sql("INSERT INTO trip_invites (trip_id, token_hash, created_at) VALUES (1, 'legacy-hash', '2026-01-01T00:00:00+00:00')")
        conn.exec_driver_sql("INSERT INTO share_links (trip_id, token_hash) VALUES (1, 'legacy-share')")
    app_db.ensure_schema(engine)
    app_db.ensure_schema(engine)  # 重复执行不抛
    assert 'expires_at' in {c['name'] for c in inspect(engine).get_columns('trip_invites')}
    assert 'revoked_at' in {c['name'] for c in inspect(engine).get_columns('share_links')}
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*), MAX(token_hash) FROM trip_invites').one() == (1, 'legacy-hash')
        assert conn.exec_driver_sql('SELECT token_hash, revoked_at FROM share_links').one() == ('legacy-share', None)
    engine.dispose()


def test_pragmas_are_applied(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pragma.db'}")
    app_db.configure_engine(engine)
    app_db.configure_engine(engine)  # 重复注册只生效一次
    with engine.connect() as conn:
        assert conn.exec_driver_sql('PRAGMA journal_mode').scalar().lower() == 'wal'
        assert conn.exec_driver_sql('PRAGMA busy_timeout').scalar() == 5000
    engine.dispose()


def test_pragmas_on_memory_engine():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    app_db.configure_engine(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('PRAGMA busy_timeout').scalar() == 5000
        # 内存库的 journal_mode 仍然是 memory，只断言不报错
        assert conn.exec_driver_sql('PRAGMA journal_mode').scalar().lower() in ('memory', 'wal')
    engine.dispose()


def _legacy_users_engine(tmp_path, name, email_column=False):
    """只有旧列的 users 表：不依赖 trips 是否存在，用来验证账户列迁移。"""
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    app_db.configure_engine(engine)
    columns = 'id INTEGER PRIMARY KEY AUTOINCREMENT, username VARCHAR(80) NOT NULL UNIQUE, password_hash VARCHAR(256) NOT NULL'
    if email_column:
        columns += ', email VARCHAR(254)'
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE users ({columns})')
    return engine


def test_ensure_schema_adds_account_columns_without_trips(tmp_path):
    engine = _legacy_users_engine(tmp_path, 'users-only.db')
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO users (username, password_hash) VALUES ('old', 'hash')")
    app_db.ensure_schema(engine)
    app_db.ensure_schema(engine)  # 幂等
    cols = {c['name'] for c in inspect(engine).get_columns('users')}
    assert {'email', 'pending_email', 'email_verified_at', 'accepted_terms_at', 'session_version', 'session_nonce'} <= cols
    indexes = {i['name'] for i in inspect(engine).get_indexes('users')}
    assert 'ix_users_email' in indexes
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT session_version, email FROM users').one() == (0, None)
    engine.dispose()


def test_ensure_schema_rejects_duplicate_emails_with_masked_value(tmp_path):
    engine = _legacy_users_engine(tmp_path, 'dup-email.db', email_column=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO users (username, password_hash, email) VALUES ('a', 'h1', 'dup@example.com')")
        conn.exec_driver_sql("INSERT INTO users (username, password_hash, email) VALUES ('b', 'h2', 'dup@example.com')")
        conn.exec_driver_sql("INSERT INTO users (username, password_hash, email) VALUES ('c', 'h3', NULL)")
    with pytest.raises(RuntimeError) as excinfo:
        app_db.ensure_schema(engine)
    message = str(excinfo.value)
    assert 'd***@example.com' in message, '重复邮箱要以脱敏值报错，不能静默跳过'
    assert 'dup@example.com' not in message
    engine.dispose()
