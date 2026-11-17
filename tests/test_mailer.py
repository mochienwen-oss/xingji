"""B2 邮件服务测试：不访问真实 SMTP，全部用 monkeypatch 与假客户端。"""
import logging
import smtplib
import ssl

import pytest

from backend.services import mailer, metrics


@pytest.fixture(autouse=True)
def _clean_mailer_env(monkeypatch):
    """每个用例都从「未配置」状态开始，并重置模块级 warning 标志。"""
    for name in (
        'SMTP_HOST',
        'SMTP_PORT',
        'SMTP_SECURITY',
        'SMTP_USER',
        'SMTP_PASSWORD',
        'SMTP_FROM',
        'SMTP_FROM_NAME',
        'APP_BASE_URL',
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mailer, '_unconfigured_warned', False)


def _configure(monkeypatch, **overrides):
    values = {
        'SMTP_HOST': 'smtp.example.com',
        'SMTP_FROM': 'no-reply@example.com',
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class _FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls_context = context
        self.calls = []

    def ehlo(self):
        self.calls.append('ehlo')

    def starttls(self, context=None):
        self.calls.append('starttls')
        self.tls_context = context

    def login(self, user, password):
        self.calls.append(('login', user, password))

    def send_message(self, message):
        self.message = message
        self.calls.append('send_message')

    def quit(self):
        self.calls.append('quit')


@pytest.fixture
def fake_smtp(monkeypatch):
    created = []

    class Factory(_FakeSMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(smtplib, 'SMTP', Factory)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', Factory)
    return created


def test_send_records_outcome_metrics(fake_smtp, monkeypatch):
    metrics.reset()
    assert mailer.send('alice@example.com', '主题', '正文') is False
    _configure(monkeypatch, SMTP_SECURITY='none')
    assert mailer.send('alice@example.com', '主题', '正文') is True
    snapshot = metrics.snapshot()
    assert snapshot['email']['by_outcome'] == {'unconfigured': 1, 'sent': 1}


def test_send_failure_records_failed_metric(monkeypatch):
    metrics.reset()
    _configure(monkeypatch, SMTP_SECURITY='ssl')

    def broken(*args, **kwargs):
        raise OSError('network down')

    monkeypatch.setattr(smtplib, 'SMTP_SSL', broken)
    assert mailer.send('alice@example.com', '主题', '正文') is False
    assert metrics.snapshot()['email']['by_outcome'] == {'failed': 1}


def test_configured_requires_host_and_from(monkeypatch):
    assert mailer.configured() is False
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
    assert mailer.configured() is False
    monkeypatch.delenv('SMTP_HOST')
    monkeypatch.setenv('SMTP_FROM', 'no-reply@example.com')
    assert mailer.configured() is False
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
    assert mailer.configured() is True


def test_unconfigured_send_returns_false_without_connecting(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError('未配置时不应尝试连接 SMTP')

    monkeypatch.setattr(smtplib, 'SMTP', explode)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', explode)
    assert mailer.send('alice@example.com', '主题', '正文') is False


def test_unconfigured_warns_only_once(caplog):
    with caplog.at_level(logging.WARNING, logger=mailer.logger.name):
        assert mailer.send('alice@example.com', '主题', '正文') is False
        assert mailer.send('bob@example.com', '主题', '正文') is False
    warnings = [r for r in caplog.records if r.name == mailer.logger.name and r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_links_use_app_base_url_without_trailing_slash(monkeypatch):
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com/')
    assert mailer.verification_link('tok-ABC_123') == 'https://trip.example.com/#verify=tok-ABC_123'
    assert mailer.reset_link('tok-ABC_123') == 'https://trip.example.com/#reset=tok-ABC_123'


def test_links_default_base_url(monkeypatch):
    # P1-4：开发默认前缀与后端 8000 端口对齐（旧默认 8001 会发出打不开的链接）。
    assert mailer.verification_link('abc') == 'http://127.0.0.1:8000/#verify=abc'
    assert mailer.reset_link('abc') == 'http://127.0.0.1:8000/#reset=abc'


def test_links_do_not_urlencode_token(monkeypatch):
    monkeypatch.setenv('APP_BASE_URL', 'https://trip.example.com')
    assert mailer.reset_link('a+b/c=') == 'https://trip.example.com/#reset=a+b/c='


@pytest.mark.parametrize(
    ('security', 'port'),
    [('ssl', 465), ('starttls', 587), ('none', 25)],
)
def test_send_uses_security_mode_timeout_and_single_recipient(fake_smtp, monkeypatch, security, port):
    _configure(
        monkeypatch,
        SMTP_SECURITY=security,
        SMTP_USER='mailer@example.com',
        SMTP_PASSWORD='auth-secret',
        SMTP_FROM_NAME='行迹 Trip',
    )
    assert mailer.send('alice@example.com', '验证你的行迹邮箱', '纯文本正文', '<p>HTML 正文</p>') is True

    assert len(fake_smtp) == 1
    client = fake_smtp[0]
    assert (client.host, client.port, client.timeout) == ('smtp.example.com', port, 10)
    assert ('login', 'mailer@example.com', 'auth-secret') in client.calls
    assert 'send_message' in client.calls
    assert client.calls[-1] == 'quit'
    if security == 'starttls':
        assert 'starttls' in client.calls
    else:
        assert 'starttls' not in client.calls

    message = client.message
    assert message['Subject'] == '验证你的行迹邮箱'
    assert message['From'] == '行迹 Trip <no-reply@example.com>'
    assert message['To'] == 'alice@example.com'
    assert '纯文本正文' in message.get_body(preferencelist=('plain',)).get_content()
    assert '<p>HTML 正文</p>' in message.get_body(preferencelist=('html',)).get_content()


def test_send_skips_login_when_user_empty(fake_smtp, monkeypatch):
    _configure(monkeypatch, SMTP_SECURITY='none')
    assert mailer.send('alice@example.com', '主题', '正文') is True
    assert not any(isinstance(call, tuple) for call in fake_smtp[0].calls)


@pytest.mark.parametrize(
    'error',
    [
        smtplib.SMTPException('smtp down'),
        OSError('network down'),
        ssl.SSLError('tls down'),
    ],
)
def test_send_failure_returns_false_and_logs_type_and_domain(monkeypatch, caplog, error):
    _configure(
        monkeypatch,
        SMTP_SECURITY='ssl',
        SMTP_USER='mailer@example.com',
        SMTP_PASSWORD='auth-secret',
    )

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(smtplib, 'SMTP_SSL', broken)
    with caplog.at_level(logging.WARNING, logger=mailer.logger.name):
        assert mailer.send('alice@example.com', '主题', '这是正文', '<p>这是正文</p>') is False

    messages = [r.getMessage() for r in caplog.records if r.name == mailer.logger.name]
    joined = ' '.join(messages)
    assert type(error).__name__ in joined
    assert 'example.com' in joined
    assert '这是正文' not in joined
    assert 'auth-secret' not in joined


def test_templates_match_spec_and_include_link():
    verify_link = 'https://trip.example.com/#verify=t'
    subject, text, html = mailer.verification_email(verify_link)
    assert subject == '验证你的行迹邮箱'
    assert '24 小时' in text and verify_link in text
    assert verify_link in html and '<a href=' in html

    change_link = 'https://trip.example.com/#verify=c'
    subject, text, html = mailer.change_email(change_link)
    assert subject == '确认你的新邮箱'
    assert '24 小时' in text and change_link in text
    assert change_link in html

    reset_link = 'https://trip.example.com/#reset=r'
    subject, text, html = mailer.password_reset_email(reset_link)
    assert subject == '重置你的行迹密码'
    assert '30 分钟' in text and reset_link in text
    assert reset_link in html
