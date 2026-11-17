"""本地 Windows 启动器的 _wmi 占位模块。

某些本机 Python 发行版的 platform.py 在导入时会加载原生 _wmi，WMI 初始化可能卡死。
在导入 platform 前调用 install()，让平台版本探测回退到 sys.getwindowsversion；
仅影响本地开发/测试启动，不改变生产启动方式。
"""
import sys
import types


def install(reason: str) -> None:
    """注册假的 _wmi 模块；reason 写进异常消息，便于区分调用方。"""
    fake = types.ModuleType('_wmi')

    def _exec_query(_query):
        raise OSError(reason)

    fake.exec_query = _exec_query
    sys.modules['_wmi'] = fake
