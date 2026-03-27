"""
Browser Tools — Agent 可调用的浏览器工具函数。
所有函数同步。通过 BrowserRuntime 管理页面生命周期和 CDP 通信。

Guard 集成：每次操作后自动采集页面指纹并经过 ActionLoopDetector 检查。
警告信息附加在返回值的 "_guard_warnings" 字段中，调度层自行决定如何处理。

此文件现为薄 re-export 层，实际实现在 browser_navigation.py 和 browser_interaction.py。
"""
from src.core.browser_guard import ActionLoopDetector, get_loop_detector, _loop_detector  # noqa: F401
from src.core.browser_navigation import *  # noqa: F401,F403
from src.core.browser_interaction import *  # noqa: F401,F403


# 向后兼容：原有的 get_loop_detector 函数
# 现在委托给 browser_guard 模块的同名函数
get_loop_detector = get_loop_detector  # re-export
