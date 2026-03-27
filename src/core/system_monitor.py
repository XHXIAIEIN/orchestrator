"""
SystemMonitor — 背压控制，偷自 Firecrawl system-monitor.ts。

执行任务前检查系统资源（CPU / RAM），高负载时延迟执行而非硬塞。
连续拒绝次数超阈值 → 标记为 stalled，上报告警。

用法:
    monitor = SystemMonitor()
    if monitor.can_accept():
        execute_task()
    else:
        log.warning("system overloaded, delaying task")
"""
import logging
import os
import platform

log = logging.getLogger(__name__)

# 阈值可通过环境变量覆盖
MAX_CPU_PERCENT = float(os.environ.get("MONITOR_MAX_CPU", "85"))
MAX_RAM_PERCENT = float(os.environ.get("MONITOR_MAX_RAM", "90"))
STALL_THRESHOLD = int(os.environ.get("MONITOR_STALL_THRESHOLD", "25"))


class SystemMonitor:
    """轻量系统资源监控器。"""

    def __init__(self):
        self._reject_streak = 0
        self._stalled = False
        self._psutil = _try_import_psutil()

    @property
    def stalled(self) -> bool:
        """连续拒绝次数超阈值，视为系统卡死。"""
        return self._stalled

    def can_accept(self) -> bool:
        """检查系统是否有余力接受新任务。"""
        if self._psutil is None:
            # psutil 不可用时不阻塞
            return True

        try:
            cpu = self._psutil.cpu_percent(interval=0.5)
            ram = self._psutil.virtual_memory().percent
        except Exception:
            return True

        if cpu > MAX_CPU_PERCENT or ram > MAX_RAM_PERCENT:
            self._reject_streak += 1
            if self._reject_streak >= STALL_THRESHOLD and not self._stalled:
                self._stalled = True
                log.error(f"SystemMonitor: STALLED — {self._reject_streak} consecutive rejections "
                          f"(cpu={cpu:.0f}%, ram={ram:.0f}%)")
            else:
                log.info(f"SystemMonitor: overloaded (cpu={cpu:.0f}%, ram={ram:.0f}%, "
                         f"streak={self._reject_streak})")
            return False

        # 恢复
        if self._reject_streak > 0:
            log.info(f"SystemMonitor: recovered after {self._reject_streak} rejections "
                     f"(cpu={cpu:.0f}%, ram={ram:.0f}%)")
        self._reject_streak = 0
        self._stalled = False
        return True

    def snapshot(self) -> dict:
        """当前系统快照，方便日志 / 调试。"""
        if self._psutil is None:
            return {"available": False}
        try:
            return {
                "cpu_percent": self._psutil.cpu_percent(interval=0.1),
                "ram_percent": self._psutil.virtual_memory().percent,
                "ram_available_gb": round(self._psutil.virtual_memory().available / (1024**3), 1),
                "reject_streak": self._reject_streak,
                "stalled": self._stalled,
            }
        except Exception:
            return {"available": False}


def _try_import_psutil():
    """尝试导入 psutil，不可用时返回 None（不阻塞启动）。"""
    try:
        import psutil
        return psutil
    except ImportError:
        log.info("SystemMonitor: psutil not installed, backpressure disabled")
        return None


# 模块级单例
_monitor = None

def get_monitor() -> SystemMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor()
    return _monitor
