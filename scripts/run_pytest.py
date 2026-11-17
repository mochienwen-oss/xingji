"""运行 pytest 的本地启动器。

某些本机 Python 发行版的 platform.py 在导入时会加载原生 _wmi，WMI 初始化可能卡死；
先用假的 _wmi 让平台探测回退，再执行真正的 site 初始化，最后跑 pytest。
用法：python -S scripts/run_pytest.py tests/ -q
"""
import sys

from wmi_shim import install  # scripts/ 在 sys.path[0]

install('wmi disabled for local test runner')

import site  # noqa: E402
site.main()

import pytest  # noqa: E402

raise SystemExit(pytest.main(sys.argv[1:]))
