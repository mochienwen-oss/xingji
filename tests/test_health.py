import logging
import re
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError
from starlette.routing import Route

from fastapi.testclient import TestClient

import backend.db as app_db
import backend.main as main
from backend import __version__
from backend.services import maintenance


def test_health_ok(client):
    c, _ = client
    response = c.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'db': 'ok', 'version': __version__}


def test_health_db_error_returns_503(client, monkeypatch):
    c, _ = client

    class BrokenEngine:
        def connect(self):
            raise OperationalError('SELECT 1', {}, Exception('database is locked'))

    monkeypatch.setattr(app_db, 'engine', BrokenEngine())
    response = c.get('/api/health')
    assert response.status_code == 503
    assert response.json() == {'status': 'degraded', 'db': 'error', 'version': __version__}


def test_health_ignores_bad_cookie(client):
    c, _ = client
    c.cookies.set('trip_session', 'not-a-valid-session-token')
    response = c.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'db': 'ok', 'version': __version__}


def test_health_not_rate_limited(client):
    c, _ = client
    for _ in range(20):
        assert c.get('/api/health').status_code == 200


def test_request_id_is_reused_or_generated(client):
    c, _ = client
    reused = c.get('/api/health', headers={'X-Request-ID': 'client-abc-123'})
    assert reused.headers['X-Request-ID'] == 'client-abc-123'
    generated = c.get('/api/health')
    assert re.fullmatch(r'[0-9a-f]{16}', generated.headers['X-Request-ID'])


def test_access_log_has_no_cookie_or_authorization(client, caplog):
    c, _ = client
    c.cookies.set('trip_session', 'secret-cookie-value')
    with caplog.at_level(logging.INFO, logger='uvicorn.error'):
        response = c.get('/api/health', headers={'Authorization': 'Bearer secret-token'})
    assert response.status_code == 200
    logged = '\n'.join(record.getMessage() for record in caplog.records)
    assert 'GET' in logged and '/api/health' in logged and '200' in logged
    assert response.headers['X-Request-ID'] in logged
    assert 'secret-cookie-value' not in logged
    assert 'secret-token' not in logged


def test_lifespan_cleanup_failure_does_not_block_startup(client, monkeypatch):
    c, _ = client

    def boom(db):
        raise RuntimeError('清理时磁盘炸了')

    monkeypatch.setattr(maintenance, 'purge_expired', boom)
    with TestClient(main.app) as restarted:
        assert restarted.get('/api/health').status_code == 200


@contextmanager
def _temporary_route(path: str, message: str):
    async def endpoint(request):
        raise OperationalError('SELECT 1', {}, Exception(message))

    route = Route(path, endpoint)
    main.app.router.routes.append(route)
    try:
        yield
    finally:
        main.app.router.routes.remove(route)


def test_database_locked_maps_to_503(client):
    c, _ = client
    with _temporary_route('/api/__database_locked', 'database is locked'):
        response = c.get('/api/__database_locked')
    assert response.status_code == 503
    assert response.json() == {'detail': '服务繁忙，请稍后重试。'}
    assert response.headers['Retry-After'] == '5'


def test_database_busy_maps_to_503(client):
    c, _ = client
    with _temporary_route('/api/__database_busy', 'database is busy'):
        response = c.get('/api/__database_busy')
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '5'


def test_other_operational_error_stays_500(client):
    c, _ = client
    with _temporary_route('/api/__database_broken', 'no such table: trips'):
        response = c.get('/api/__database_broken')
    assert response.status_code == 500
    assert response.json() == {'detail': '服务暂时不可用，请稍后重试'}
