"""全局记忆：users.memory_enabled 默认值、MemoryStore 合并语义、extractor 的结构容错。"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.db as app_db
from backend.db import Base, User, UserMemory
from backend.services.harness.memory import extractor
from backend.services.harness.memory.store import MemoryStore
from backend.services.llm import ModelOutputError


def _now() -> datetime:
    """和 MemoryStore 一致：UTC naive。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def session():
    """内存 SQLite + 一个真实用户；StaticPool 让同一连接在会话之间共享。"""
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(username='memory-user', password_hash='x')
        db.add(user)
        db.commit()
        yield db, user.id
    engine.dispose()


def _rows(db) -> list[UserMemory]:
    return list(db.execute(select(UserMemory).order_by(UserMemory.id)).scalars().all())


# --- 表结构与开关 ---------------------------------------------------------

def test_memory_enabled_defaults_true(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(username='switch', password_hash='x')
        db.add(user)
        db.commit()
        db.refresh(user)
        # ORM 默认值 + 落库后的真实值都必须开启，否则老用户升级后记忆会被静默关掉。
        assert user.memory_enabled is True
        assert db.execute(select(User.memory_enabled)).scalar() is True
        user.memory_enabled = False
        db.commit()
        assert db.execute(select(User.memory_enabled)).scalar() is False
    engine.dispose()


def test_ensure_schema_adds_memory_enabled_to_legacy_users(tmp_path):
    """只带旧列的 users 表：ensure_schema 补列后默认必须是 1（开启），不能是 NULL。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            'CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'username VARCHAR(80) NOT NULL UNIQUE, password_hash VARCHAR(256) NOT NULL)'
        )
        conn.exec_driver_sql("INSERT INTO users (username, password_hash) VALUES ('old', 'h')")
    app_db.ensure_schema(engine)
    app_db.ensure_schema(engine)  # 幂等
    assert 'memory_enabled' in {c['name'] for c in inspect(engine).get_columns('users')}
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT memory_enabled FROM users').scalar() == 1
    engine.dispose()


def test_prepare_database_upgrades_legacy_sqlite(tmp_path):
    """老 trip.db 只有 users 旧列：启动流程要把记忆表和开关一起补上。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-app.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            'CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'username VARCHAR(80) NOT NULL UNIQUE, password_hash VARCHAR(256) NOT NULL)'
        )
        conn.exec_driver_sql("INSERT INTO users (username, password_hash) VALUES ('old', 'h')")
    app_db.prepare_database(engine)  # create_all + ensure_schema
    assert 'user_memories' in set(inspect(engine).get_table_names())
    assert 'memory_enabled' in {c['name'] for c in inspect(engine).get_columns('users')}
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT memory_enabled FROM users').scalar() == 1
    engine.dispose()


def test_user_memories_table_is_created_with_expected_columns(session):
    db, _ = session
    columns = {c['name']: c for c in inspect(db.get_bind()).get_columns('user_memories')}
    assert set(columns) == {
        'id', 'user_id', 'category', 'scope', 'key', 'value', 'evidence',
        'confidence', 'expires_at', 'superseded_at', 'created_at', 'updated_at',
    }
    assert columns['user_id']['nullable'] is False
    assert columns['scope']['nullable'] is False
    assert columns['confidence']['nullable'] is False
    indexes = {i['name']: bool(i['unique']) for i in inspect(db.get_bind()).get_indexes('user_memories')}
    assert indexes['uq_user_memories_key'] is True


# --- MemoryStore.apply ----------------------------------------------------

def test_apply_updates_same_value_without_new_row(session):
    db, user_id = session
    store = MemoryStore(db)
    assert store.apply(user_id, [{'category': 'preference', 'key': '饮食', 'value': '不吃辣',
                                  'evidence': '第 3 轮', 'confidence': 0.5}]) == 1
    assert store.apply(user_id, [{'category': 'preference', 'key': '饮食', 'value': '不吃辣',
                                  'evidence': '第 9 轮', 'confidence': 0.9}]) == 1
    db.commit()
    rows = _rows(db)
    assert len(rows) == 1
    assert (rows[0].evidence, rows[0].confidence, rows[0].superseded_at) == ('第 9 轮', 0.9, None)


def test_apply_supersedes_previous_value(session):
    db, user_id = session
    store = MemoryStore(db)
    store.apply(user_id, [{'category': 'preference', 'key': '预算', 'value': '2000 元'}])
    store.apply(user_id, [{'category': 'preference', 'key': '预算', 'value': '3000 元', 'confidence': 0.8}])
    db.commit()
    rows = _rows(db)
    # 值变了：旧行留档、新行生效；部分唯一索引只约束 superseded_at IS NULL 的行。
    assert [row.value for row in rows] == ['2000 元', '3000 元']
    assert rows[0].superseded_at is not None and rows[1].superseded_at is None
    assert [item['value'] for item in store.list_for_user(user_id)] == ['3000 元']


def test_list_hides_expired_memories(session):
    db, user_id = session
    store = MemoryStore(db)
    store.apply(user_id, [
        {'category': 'project', 'key': '旧计划', 'value': '下个月去成都',
         'expires_at': (_now() - timedelta(days=1)).isoformat()},
        {'category': 'project', 'key': '新计划', 'value': '春节去哈尔滨',
         'expires_at': (_now() + timedelta(days=30)).isoformat()},
        {'category': 'preference', 'key': '口味', 'value': '偏清淡'},
    ])
    db.commit()
    assert {item['key'] for item in store.list_for_user(user_id)} == {'新计划', '口味'}


def test_apply_skips_sensitive_values(session):
    db, user_id = session
    store = MemoryStore(db)
    written = store.apply(user_id, [
        {'category': 'preference', 'key': 'wifi', 'value': 'password: hunter2'},
        {'category': 'preference', 'key': '证件', 'value': '身份证 110101199001011234'},
        {'category': 'preference', 'key': '联系', 'value': '手机号 13800000000'},
        {'category': 'preference', 'key': '邮箱', 'value': '常用邮箱是 a@b.com'},
        {'category': 'preference', 'key': '口味', 'value': '喜欢川菜'},
    ])
    db.commit()
    assert written == 1
    assert [item['value'] for item in store.list_for_user(user_id)] == ['喜欢川菜']


def test_apply_skips_invalid_candidates(session):
    db, user_id = session
    store = MemoryStore(db)
    written = store.apply(user_id, [
        {'category': 'unknown', 'key': 'k1', 'value': 'v'},
        {'category': 'preference', 'key': '', 'value': 'v'},
        {'category': 'preference', 'key': 'k' * 81, 'value': 'v'},
        {'category': 'preference', 'key': 'k2', 'value': 'v' * 501},
        {'category': 'preference', 'key': 'k3', 'value': 'v', 'confidence': 1.5},
        {'category': 'preference', 'key': 'k4', 'value': 'v', 'confidence': '高'},
        {'category': 'preference', 'key': 'k5', 'value': 'v', 'evidence': 'e' * 501},
        {'category': 'preference', 'key': 'k6', 'value': 123},
        'not-a-dict',
        None,
    ])
    db.commit()
    assert written == 0
    assert store.list_for_user(user_id) == []


def test_list_orders_by_confidence_and_respects_limit(session):
    db, user_id = session
    store = MemoryStore(db)
    store.apply(user_id, [
        {'category': 'preference', 'key': 'a', 'value': 'A', 'confidence': 0.4},
        {'category': 'preference', 'key': 'b', 'value': 'B', 'confidence': 0.9},
        {'category': 'preference', 'key': 'c', 'value': 'C', 'confidence': 0.6},
    ])
    db.commit()
    assert [item['key'] for item in store.list_for_user(user_id, limit=2)] == ['b', 'c']
    assert len(store.list_for_user(user_id)) == 3
    assert store.list_for_user(user_id, limit=0) == []


def test_list_is_scoped_to_each_user(session):
    db, user_id = session
    other = User(username='memory-other', password_hash='x')
    db.add(other)
    db.commit()
    store = MemoryStore(db)
    store.apply(user_id, [{'category': 'preference', 'key': 'k', 'value': 'alice 的偏好'}])
    store.apply(other.id, [{'category': 'preference', 'key': 'k', 'value': 'bob 的偏好'}])
    db.commit()
    assert [item['value'] for item in store.list_for_user(user_id)] == ['alice 的偏好']
    assert [item['value'] for item in store.list_for_user(other.id)] == ['bob 的偏好']


def test_apply_leaves_commit_to_caller(tmp_path):
    """store 只 flush 不 commit：调用方不提交，数据就不该落库。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'commit.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username='commit-user', password_hash='x')
        db.add(user)
        db.commit()
        user_id = user.id
    with sessions() as db:
        MemoryStore(db).apply(user_id, [{'category': 'preference', 'key': 'k', 'value': 'v'}])
    with sessions() as db:
        assert db.execute(select(UserMemory)).scalars().all() == []
    engine.dispose()


# --- extractor ------------------------------------------------------------

@pytest.mark.anyio
async def test_extract_memories_returns_cleaned_candidates(monkeypatch):
    calls = {}

    async def fake(messages, max_tokens=4000, on_reply=None):
        calls['messages'] = messages
        calls['max_tokens'] = max_tokens
        return {'memories': [
            {'category': 'preference', 'key': ' 口味 ', 'value': ' 不吃辣 ',
             'evidence': '用户说明', 'confidence': 0.8},
            {'category': 'bogus', 'key': 'x', 'value': 'y'},
            {'category': 'feedback', 'key': '', 'value': 'y'},
            {'category': 'project', 'key': '行程', 'value': '国庆去西安', 'confidence': 3},
            {'category': 'resource', 'key': '地图', 'value': '习惯用高德', 'confidence': 0.5},
        ]}

    monkeypatch.setattr(extractor, 'model_json', fake)
    result = await extractor.extract_memories(
        [{'role': 'user', 'content': '你好'}],
        [{'category': 'preference', 'key': '旧', 'value': '旧值'}],
        {'city': '西安'},
    )

    assert [item['key'] for item in result] == ['口味', '地图']
    assert result[0] == {'category': 'preference', 'scope': '', 'key': '口味', 'value': '不吃辣',
                         'evidence': '用户说明', 'confidence': 0.8}
    assert calls['max_tokens'] == 1200
    system, user = calls['messages']
    assert system['role'] == 'system' and system['content']
    payload = json.loads(user['content'])
    assert payload['最近对话'] == [{'role': 'user', 'content': '你好'}]
    assert payload['对话摘要'] == {'city': '西安'}
    assert payload['已有记忆'][0]['key'] == '旧'


@pytest.mark.anyio
async def test_extract_memories_trims_context_window(monkeypatch):
    captured = {}

    async def fake(messages, max_tokens=4000, on_reply=None):
        captured.update(json.loads(messages[1]['content']))
        return {'memories': []}

    monkeypatch.setattr(extractor, 'model_json', fake)
    await extractor.extract_memories(
        [{'role': 'user', 'content': str(i)} for i in range(20)],
        [{'key': str(i)} for i in range(30)],
        None,
    )

    assert [item['content'] for item in captured['最近对话']] == [str(i) for i in range(8, 20)]
    assert captured['已有记忆'][0] == {'key': '10'}
    assert captured['对话摘要'] == {}


@pytest.mark.anyio
async def test_extract_memories_caps_at_five(monkeypatch):
    async def fake(messages, max_tokens=4000, on_reply=None):
        return {'memories': [{'category': 'preference', 'key': f'k{i}', 'value': f'v{i}'} for i in range(8)]}

    monkeypatch.setattr(extractor, 'model_json', fake)
    assert len(await extractor.extract_memories([], [], None)) == 5


@pytest.mark.anyio
async def test_extract_memories_retries_once_on_model_output_error(monkeypatch):
    calls = {'count': 0}

    async def flaky(messages, max_tokens=4000, on_reply=None):
        calls['count'] += 1
        if calls['count'] == 1:
            raise ModelOutputError('空的 choices')
        return {'memories': [{'category': 'preference', 'key': 'pace', 'value': '慢一点'}]}

    monkeypatch.setattr(extractor, 'model_json', flaky)
    result = await extractor.extract_memories([{'role': 'user', 'content': '我走不动'}], [], None)
    assert calls['count'] == 2
    assert [item['key'] for item in result] == ['pace']


@pytest.mark.anyio
async def test_extract_memories_returns_empty_on_bad_output(monkeypatch):
    async def bad_structure(messages, max_tokens=4000, on_reply=None):
        return {'memories': '不是列表'}

    monkeypatch.setattr(extractor, 'model_json', bad_structure)
    assert await extractor.extract_memories([], [], None) == []

    async def not_a_dict(messages, max_tokens=4000, on_reply=None):
        return ['memories']

    monkeypatch.setattr(extractor, 'model_json', not_a_dict)
    assert await extractor.extract_memories([], [], None) == []

    async def broken(messages, max_tokens=4000, on_reply=None):
        raise ValueError('bad json')

    # 模型/网络错误同样只丢这一轮：记忆是后台增强，不能抛给主流程。
    monkeypatch.setattr(extractor, 'model_json', broken)
    assert await extractor.extract_memories([], [], None) == []


def test_load_prompt_uses_scenario_file_and_falls_back(monkeypatch, tmp_path):
    missing = tmp_path / 'missing.md'
    monkeypatch.setattr(extractor, 'PROMPT_PATH', missing)
    assert extractor.load_prompt() == extractor.FALLBACK_PROMPT

    scenario = tmp_path / 'memory_extract.md'
    scenario.write_text('自定义记忆 prompt', encoding='utf-8')
    monkeypatch.setattr(extractor, 'PROMPT_PATH', scenario)
    assert extractor.load_prompt() == '自定义记忆 prompt'
