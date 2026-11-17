"""会话密钥解析：生产缺配置必须启动失败，本地开发仍可自建文件复用。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend import auth

ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_explicit_session_secret(monkeypatch, tmp_path):
    """生产缺 SESSION_SECRET：启动阶段报错，不能悄悄生成只在本进程有效的密钥。"""
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('SESSION_SECRET', raising=False)
    with pytest.raises(RuntimeError, match='SESSION_SECRET'):
        auth._secret(tmp_path)
    assert not (tmp_path / '.session-secret').exists(), '生产不应落本地密钥文件'


def test_production_uses_configured_session_secret(monkeypatch, tmp_path):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SESSION_SECRET', 's' * 40)
    assert auth._secret(tmp_path) == 's' * 40
    assert not (tmp_path / '.session-secret').exists()


def test_dev_generates_and_reuses_local_secret(monkeypatch, tmp_path):
    """本地开发：首次生成 64 位 hex 并复用；重启后 cookie 仍有效。"""
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('SESSION_SECRET', raising=False)
    first = auth._secret(tmp_path)
    second = auth._secret(tmp_path)
    assert first == second
    assert len(first) == 64
    assert int(first, 16) >= 0
    path = tmp_path / '.session-secret'
    assert path.read_text(encoding='ascii').strip() == first
    if os.name == 'posix':
        assert path.stat().st_mode & 0o777 == 0o600


def test_importing_app_in_production_without_secret_fails():
    """真实启动路径：导入 backend.main 就失败，错误信息点明 SESSION_SECRET。"""
    env = {
        **os.environ,
        'APP_ENV': 'production',
        'SESSION_SECRET': '',
        'APP_BASE_URL': 'https://trip.example.com',
        'DATABASE_URL': 'sqlite://',
        'PYTHONIOENCODING': 'utf-8',
    }
    # 与 tests/test_d3_backend_fixes.py 的启动校验用例同一套 _wmi 占位，避免本机 WMI 导入挂死。
    import_code = (
        "import sys, types\n"
        "m = types.ModuleType('_wmi')\n"
        "m.exec_query = lambda q: (_ for _ in ()).throw(OSError('wmi disabled'))\n"
        "sys.modules.setdefault('_wmi', m)\n"
        "import backend.main\n"
    )
    proc = subprocess.run(
        [sys.executable, '-c', import_code],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=120,
    )
    assert proc.returncode != 0
    assert 'SESSION_SECRET' in proc.stderr
