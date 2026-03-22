"""
AgentSemaphore — 分级并发控制。

Lucentia 启发：按部门类型不同并发上限，全局上限兜底。

当前 Governor 用 MAX_CONCURRENT=3 全局限制。
AgentSemaphore 升级为按部门类型分级：
  - MUTATE 部门（engineering/operations）：最多 2 个并行
  - READ 部门（protocol/security/quality/personnel）：最多 4 个并行
  - 全局上限：5
"""
import logging
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SemaphoreConfig:
    """并发配置。"""
    global_max: int = 5
    mutate_max: int = 2    # 写操作部门
    read_max: int = 4      # 只读部门


MUTATE_DEPARTMENTS = {"engineering", "operations"}
READ_DEPARTMENTS = {"protocol", "security", "quality", "personnel"}


class AgentSemaphore:
    """分级并发信号量。"""

    def __init__(self, config: SemaphoreConfig = None):
        self.config = config or SemaphoreConfig()
        self._lock = threading.Lock()
        self._running: dict[str, set[int]] = {}  # dept → set of task_ids

    def try_acquire(self, department: str, task_id: int) -> tuple[bool, str]:
        """尝试获取执行槽位。返回 (acquired, reason)。"""
        with self._lock:
            # 全局上限
            total = sum(len(tasks) for tasks in self._running.values())
            if total >= self.config.global_max:
                return False, f"全局并发上限 {self.config.global_max}"

            # 部门级上限
            dept_tasks = self._running.get(department, set())
            if department in MUTATE_DEPARTMENTS:
                mutate_total = sum(
                    len(self._running.get(d, set())) for d in MUTATE_DEPARTMENTS
                )
                if mutate_total >= self.config.mutate_max:
                    return False, f"MUTATE 部门并发上限 {self.config.mutate_max}"
            elif department in READ_DEPARTMENTS:
                read_total = sum(
                    len(self._running.get(d, set())) for d in READ_DEPARTMENTS
                )
                if read_total >= self.config.read_max:
                    return False, f"READ 部门并发上限 {self.config.read_max}"

            # 获取槽位
            if department not in self._running:
                self._running[department] = set()
            self._running[department].add(task_id)
            log.info(f"semaphore: acquired slot for {department}:#{task_id} "
                     f"(total={total + 1})")
            return True, ""

    def release(self, department: str, task_id: int):
        """释放执行槽位。"""
        with self._lock:
            if department in self._running:
                self._running[department].discard(task_id)
                if not self._running[department]:
                    del self._running[department]
            log.debug(f"semaphore: released slot for {department}:#{task_id}")

    def get_status(self) -> dict:
        """获取当前并发状态。"""
        with self._lock:
            return {
                "global_used": sum(len(t) for t in self._running.values()),
                "global_max": self.config.global_max,
                "by_department": {
                    dept: list(tasks) for dept, tasks in self._running.items()
                },
            }
