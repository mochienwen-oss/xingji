import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import hash_password
from backend.db import Base, User, configure_engine
import backend.db as app_db
from backend.main import app
from backend.api.dependencies import db_session
import backend.main as main
from backend.services import amap, metrics, planning, quota, ratelimit

@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """每个测试都从空令牌桶、空配额计数和空高德地点缓存开始，避免跨用例污染。"""
    ratelimit.reset()
    quota.reset()
    amap.reset_place_cache()
    metrics.reset()
    yield
    ratelimit.reset()
    quota.reset()
    amap.reset_place_cache()
    metrics.reset()

@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    configure_engine(engine)
    monkeypatch.setattr(main, 'engine', engine)
    # 健康检查等旁路代码直接读 backend.db.engine：指向同一个内存库，避免连到开发库
    monkeypatch.setattr(app_db, 'engine', engine)
    # 测试辅助直接访问数据库时用同一会话工厂，避免污染开发库
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(app_db, 'Session', sessions)
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add_all([User(username='alice', password_hash=hash_password('password1')), User(username='bob', password_hash=hash_password('password2'))])
        db.commit()
    def override_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[db_session] = override_db
    places = [dict(id=str(i), name=f'景点{i}', address='地址', location=f'120.{i},30.{i}', opentime='', cost='', source_time='2026-01-01T00:00:00Z') for i in range(1, 5)]
    async def search(city, keyword):
        return places
    async def find_places(ids):
        return {p['id']: p for p in places if p['id'] in ids}
    async def generate(request, candidates, **kwargs):
        return [{'stops': [{'place': candidates[i], 'duration': 90, 'reason': '推荐'}]} for i in range(request['days'])]
    async def route(a, b, mode, city):
        return {'origin': a['id'], 'destination': b['id'], 'mode': mode, 'duration': 600, 'polyline': [[[120, 30], [121, 31]]], 'source_time': '2026-01-01T00:00:00Z'}
    monkeypatch.setattr(amap, 'search_places', search)
    monkeypatch.setattr(amap, 'find_places', find_places)
    monkeypatch.setattr(planning, 'generate_plan', generate)
    monkeypatch.setattr(amap, 'route_between', route)
    with TestClient(app) as c:
        yield c, places
    app.dependency_overrides.clear()
    engine.dispose()

def login(c, username='alice', password='password1'):
    return c.post('/api/login', json={'username': username, 'password': password})

@pytest.fixture
def anyio_backend():
    return 'asyncio'
