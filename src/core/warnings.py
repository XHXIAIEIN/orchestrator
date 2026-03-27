"""
WarningCollector — 非致命警告收集器，偷自 Parallel Search 的 warnings[] 机制。

核心理念：能做就做，但告诉调用者哪里不完美。
  - 不中断执行流（vs 异常）
  - 不丢失信息（vs 静默忽略）
  - 调用方决定是否需要人工介入

用法:
    from src.core.warnings import WarningCollector, warning_context

    # 方式 1: 手动使用
    wc = WarningCollector("router")
    wc.warn("ollama unreachable, fell back to claude")
    wc.warn("response shorter than expected", severity="medium")
    print(wc.warnings)  # [Warning(...), ...]

    # 方式 2: 上下文管理器（自动收集当前上下文的所有警告）
    with warning_context("task_123") as wc:
        wc.warn("something not ideal")
        do_work()
    # wc.warnings 包含所有收集到的警告

    # 方式 3: 全局收集器（跨模块共享）
    from src.core.warnings import get_collector
    get_collector().warn("cross-module warning")
"""
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Warning:
    """单条警告。"""
    message: str
    source: str = ""                   # 产生警告的组件
    severity: str = "low"              # low / medium / high
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __str__(self) -> str:
        return f"[{self.severity}] {self.source}: {self.message}"


class WarningCollector:
    """线程安全的警告收集器。"""

    def __init__(self, source: str = ""):
        self.source = source
        self._warnings: list[Warning] = []
        self._lock = threading.Lock()

    def warn(self, message: str, severity: str = "low", source: str = "") -> None:
        """记录一条警告。不中断执行。"""
        w = Warning(
            message=message,
            source=source or self.source,
            severity=severity,
        )
        with self._lock:
            self._warnings.append(w)
        log.info(f"warning: {w}")

    @property
    def warnings(self) -> list[Warning]:
        with self._lock:
            return list(self._warnings)

    @property
    def has_warnings(self) -> bool:
        return len(self._warnings) > 0

    @property
    def high_severity(self) -> list[Warning]:
        """仅返回 high severity 警告。"""
        with self._lock:
            return [w for w in self._warnings if w.severity == "high"]

    def to_strings(self) -> list[str]:
        """转为字符串列表，方便塞进 GenerateResult.warnings。"""
        with self._lock:
            return [str(w) for w in self._warnings]

    def clear(self) -> None:
        with self._lock:
            self._warnings.clear()

    def merge(self, other: "WarningCollector") -> None:
        """合并另一个收集器的警告。"""
        with self._lock:
            self._warnings.extend(other.warnings)


# ── 全局收集器 ──
_global: Optional[WarningCollector] = None
_global_lock = threading.Lock()


def get_collector() -> WarningCollector:
    """获取全局警告收集器。"""
    global _global
    with _global_lock:
        if _global is None:
            _global = WarningCollector("global")
        return _global


@contextmanager
def warning_context(source: str = ""):
    """上下文管理器，创建一个临时收集器。退出时警告保留在收集器上。"""
    wc = WarningCollector(source)
    yield wc
    if wc.has_warnings:
        log.info(f"warning_context '{source}' collected {len(wc.warnings)} warnings")
