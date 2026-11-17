from backend.services import accounts, site_config


def _prod(monkeypatch, base: str):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('APP_BASE_URL', base)
    monkeypatch.delenv('COOKIE_SECURE', raising=False)


def test_production_requires_https(monkeypatch):
    _prod(monkeypatch, 'http://trip.example.com')
    errors = site_config.validate_production()
    assert any('https' in item for item in errors)


def test_production_rejects_localhost(monkeypatch):
    _prod(monkeypatch, 'https://127.0.0.1:8000')
    errors = site_config.validate_production()
    assert any('localhost' in item for item in errors)


def test_production_accepts_public_https(monkeypatch):
    _prod(monkeypatch, 'https://trip.example.com/')
    assert site_config.validate_production() == []


def test_production_rejects_explicit_insecure_cookie(monkeypatch):
    _prod(monkeypatch, 'https://trip.example.com')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    assert any('COOKIE_SECURE' in item for item in site_config.validate_production())


def test_production_missing_base_url_mentions_variable(monkeypatch):
    _prod(monkeypatch, '')
    assert any('APP_BASE_URL' in item for item in site_config.validate_production())


def test_cookie_secure_defaults_to_https_base(monkeypatch):
    monkeypatch.delenv('COOKIE_SECURE', raising=False)
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com')
    assert accounts.cookie_secure() is True
    monkeypatch.setenv('APP_BASE_URL', 'http://127.0.0.1:8000')
    assert accounts.cookie_secure() is False


def test_cookie_secure_explicit_value_wins(monkeypatch):
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    assert accounts.cookie_secure() is False
    monkeypatch.setenv('COOKIE_SECURE', 'true')
    assert accounts.cookie_secure() is True


def test_site_config_ignores_development(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('APP_BASE_URL', 'http://127.0.0.1:8000')
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    assert site_config.validate_production() == []
