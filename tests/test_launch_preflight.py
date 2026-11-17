from types import SimpleNamespace

from scripts import launch_preflight


BASE_ENV = {
    'APP_ENV': 'production',
    'APP_BASE_URL': 'https://trip.example.com',
    'COOKIE_SECURE': 'true',
    'DATABASE_URL': 'postgresql+psycopg://trip:secret@db.internal:5432/trip',
    'SESSION_SECRET': 's' * 40,
    'ADMIN_TOKEN': 'a' * 40,
    'SMTP_HOST': 'smtp.example.com',
    'SMTP_FROM': 'no-reply@example.com',
    'SMTP_SECURITY': 'starttls',
    'SMTP_USER': 'mailer',
    'SMTP_PASSWORD': 'mail-secret',
    'SUPPORT_EMAIL': 'support@example.com',
    'OPERATOR_NAME': '行迹工作室',
    'OPERATOR_CONTACT_EMAIL': 'legal@example.com',
    'OPERATOR_JURISDICTION': '杭州',
    'ICP_NUMBER': '浙ICP备00000000号',
    'AMAP_WEB_KEY': 'amap-web',
    'AMAP_JS_KEY': 'amap-js',
    'AMAP_JS_SECURITY_CODE': 'security',
    'LLM_API_KEY': 'llm-key',
    'LLM_MODEL': 'deepseek-flash',
}


def _failed(names):
    return {item['name'] for item in names if item['required'] and not item['ok']}


def test_valid_production_env_has_no_required_failures():
    checks = launch_preflight.validate_environment(BASE_ENV)
    assert _failed(checks) == set()


def test_environment_flags_common_launch_blockers():
    env = dict(BASE_ENV)
    env.update({
        'APP_ENV': 'development',
        'APP_BASE_URL': 'http://127.0.0.1:8000',
        'COOKIE_SECURE': 'false',
        'DATABASE_URL': 'sqlite:///./trip.db',
        'ADMIN_TOKEN': '',
        'SMTP_HOST': '',
        'SUPPORT_EMAIL': 'not-an-email',
        'OPERATOR_NAME': '',
        'AMAP_WEB_KEY': '',
        'LLM_API_KEY': '',
    })
    failed = _failed(launch_preflight.validate_environment(env))
    assert {
        'APP_ENV', 'APP_BASE_URL', 'COOKIE_SECURE', 'DATABASE_URL',
        'ADMIN_TOKEN', 'SMTP_HOST', 'SUPPORT_EMAIL', 'OPERATOR_NAME',
        'AMAP_WEB_KEY', 'LLM_API_KEY',
    } <= failed


def test_cookie_secure_shares_the_backend_strict_rule():
    """与 backend/services/site_config.py 同口径：只有留空或 true 能通过。"""
    for value in ('', 'true', 'TRUE'):
        env = dict(BASE_ENV, COOKIE_SECURE=value)
        check = next(item for item in launch_preflight.validate_environment(env) if item['name'] == 'COOKIE_SECURE')
        assert check['ok'] is True, value
    for value in ('false', '1', '0', 'no', 'yes'):
        env = dict(BASE_ENV, COOKIE_SECURE=value)
        check = next(item for item in launch_preflight.validate_environment(env) if item['name'] == 'COOKIE_SECURE')
        assert check['ok'] is False, value


def test_unknown_smtp_security_is_flagged():
    env = dict(BASE_ENV, SMTP_SECURITY='none')
    check = next(item for item in launch_preflight.validate_environment(env) if item['name'] == 'SMTP_SECURITY')
    assert check['ok'] is False
    assert check['required'] is True


def test_alembic_head_matches_latest_migration():
    assert launch_preflight.alembic_head() == '0009_cleanup_dead_schema'


def test_alembic_head_is_unknown_when_history_branches(tmp_path):
    """多 head 时分叉，期望版本不唯一：返回空串让 DATABASE 必检项失败。"""
    (tmp_path / 'a.py').write_text("revision = 'aaa'\ndown_revision = None\n", encoding='utf-8')
    (tmp_path / 'b.py').write_text("revision = 'bbb'\ndown_revision = 'aaa'\n", encoding='utf-8')
    (tmp_path / 'c.py').write_text("revision = 'ccc'\ndown_revision = 'aaa'\n", encoding='utf-8')
    assert launch_preflight.alembic_head(tmp_path) == ''


def test_frontend_build_requires_index_and_assets(tmp_path):
    dist = tmp_path / 'dist'
    assert launch_preflight.check_frontend_build(dist)['ok'] is False
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html></html>', encoding='utf-8')
    assert launch_preflight.check_frontend_build(dist)['ok'] is False
    (dist / 'assets' / 'index-abc.js').write_text('', encoding='utf-8')
    (dist / 'assets' / 'index-abc.css').write_text('', encoding='utf-8')
    assert launch_preflight.check_frontend_build(dist)['ok'] is True


def test_parse_database_url_keeps_connection_fields_and_decodes_password():
    settings = launch_preflight.parse_database_url(
        'postgresql+psycopg://trip:p%40ss@db.internal:5433/trip?sslmode=require'
    )
    assert settings == {
        'host': 'db.internal', 'port': '5433', 'user': 'trip',
        'password': 'p@ss', 'database': 'trip', 'sslmode': 'require',
    }


def test_check_database_compares_alembic_version(monkeypatch):
    monkeypatch.setattr(launch_preflight.shutil, 'which', lambda name: 'psql')
    seen = {}

    def fake_run(command, **kwargs):
        seen['command'] = command
        return SimpleNamespace(returncode=0, stdout='0006_analytics_daily\n', stderr='')

    monkeypatch.setattr(launch_preflight.subprocess, 'run', fake_run)
    check = launch_preflight.check_database(
        'postgresql+psycopg://trip:secret@db.internal/trip', '0006_analytics_daily'
    )
    assert check['ok'] is True
    assert '0006_analytics_daily' in check['detail']
    assert '-h' in seen['command']


def test_check_database_reports_mismatch(monkeypatch):
    monkeypatch.setattr(launch_preflight.shutil, 'which', lambda name: 'psql')
    monkeypatch.setattr(
        launch_preflight.subprocess, 'run',
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='0005_trip_last_edited\n', stderr=''),
    )
    check = launch_preflight.check_database(
        'postgresql+psycopg://trip:secret@db.internal/trip', '0006_analytics_daily'
    )
    assert check['ok'] is False
    assert '0005' in check['detail']
