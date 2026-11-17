"""启动本地后端开发服务器。

某些本机 Python 发行版的 platform.py 在导入时会加载原生 _wmi，WMI 初始化可能卡死；
这里在导入 platform 前放入占位模块（见 scripts/wmi_shim.py），让平台版本探测回退。
仅影响本地开发环境，不改变生产启动方式。
"""
import sys
from pathlib import Path

# 以 `python scripts/start_backend.py` 启动时 sys.path[0] 是 scripts/，
# 这里把仓库根目录加入路径，保证能导入 backend.main。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wmi_shim import install  # noqa: E402  (scripts/ 在 sys.path[0])

install('wmi disabled for local runtime')

import platform  # noqa: E402
platform._wmi = None  # type: ignore[attr-defined]
import uvicorn  # noqa: E402

uvicorn.run('backend.main:app', host='127.0.0.1', port=8000)
