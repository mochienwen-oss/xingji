"""应用版本号在前后端各来源之间保持一致。"""
import json
from pathlib import Path

from backend import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_sources_agree():
    package = json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))
    lock = json.loads((ROOT / 'frontend' / 'package-lock.json').read_text(encoding='utf-8'))
    app_info = (ROOT / 'frontend' / 'src' / 'lib' / 'appInfo.ts').read_text(encoding='utf-8')

    assert package['version'] == __version__
    assert lock['version'] == __version__
    assert lock['packages']['']['version'] == __version__
    assert f"APP_VERSION = '{__version__}'" in app_info
