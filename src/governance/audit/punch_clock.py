"""
Punch-in/Punch-out — 多 agent 并行时的区域声明。

organvm 启发：agent "打卡"声明操作区域，TTL 自动过期。

用途：
  - 防止两个 agent 同时修改同一文件
  - TTL 自动过期（agent 挂了也不会永久锁定）
  - 与 AgentSemaphore 互补：semaphore 控制数量，punch_clock 控制区域

同时实现 Atomic Task Checkout（Paperclip）：
  - checkout 时检查是否冲突，409 放弃
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DEFAULT_TTL_S = 600  # 默认 10 分钟 TTL


@dataclass
class PunchRecord:
    """打卡记录。"""
    task_id: int
    agent_id: str
    files: list[str]          # 声明操作的文件列表
    department: str
    punched_in_at: float      # time.time()
    ttl_s: int = DEFAULT_TTL_S

    @property
    def expired(self) -> bool:
        return time.time() - self.punched_in_at > self.ttl_s


class PunchClock:
    """打卡系统。"""

    def __init__(self):
        self._records: dict[int, PunchRecord] = {}  # task_id → record
        self._lock = threading.Lock()

    def punch_in(self, task_id: int, agent_id: str, files: list[str],
                  department: str, ttl_s: int = DEFAULT_TTL_S) -> tuple[bool, str]:
        """打卡进入。检查文件是否被其他 agent 占用。

        Returns: (success, conflict_reason)
        """
        with self._lock:
            self._cleanup_expired()

            # 检查文件冲突
            for other_id, record in self._records.items():
                if other_id == task_id:
                    continue
                overlap = set(files) & set(record.files)
                if overlap:
                    return False, (
                        f"文件冲突：{', '.join(overlap)} 被任务 #{other_id} "
                        f"({record.department}) 占用"
                    )

            # 打卡
            self._records[task_id] = PunchRecord(
                task_id=task_id,
                agent_id=agent_id,
                files=files,
                department=department,
                punched_in_at=time.time(),
                ttl_s=ttl_s,
            )
            log.info(f"punch_clock: task #{task_id} punched in, "
                     f"files={files[:3]}, ttl={ttl_s}s")
            return True, ""

    def punch_out(self, task_id: int):
        """打卡离开。"""
        with self._lock:
            if task_id in self._records:
                del self._records[task_id]
                log.debug(f"punch_clock: task #{task_id} punched out")

    def checkout(self, task_id: int, files: list[str],
                  department: str) -> tuple[bool, str]:
        """Atomic Task Checkout — 尝试获取文件独占权。

        等价于 POST /checkout + 409 冲突放弃。
        """
        return self.punch_in(task_id, f"agent-{task_id}", files, department)

    def get_active_records(self) -> list[dict]:
        """获取所有活跃的打卡记录。"""
        with self._lock:
            self._cleanup_expired()
            return [
                {
                    "task_id": r.task_id,
                    "agent_id": r.agent_id,
                    "files": r.files,
                    "department": r.department,
                    "age_s": int(time.time() - r.punched_in_at),
                    "ttl_s": r.ttl_s,
                }
                for r in self._records.values()
            ]

    def is_file_locked(self, file_path: str) -> tuple[bool, int]:
        """检查文件是否被锁定。返回 (locked, by_task_id)。"""
        with self._lock:
            self._cleanup_expired()
            for task_id, record in self._records.items():
                if file_path in record.files:
                    return True, task_id
            return False, 0

    def _cleanup_expired(self):
        """清理过期的打卡记录（在锁内调用）。"""
        expired = [tid for tid, r in self._records.items() if r.expired]
        for tid in expired:
            log.info(f"punch_clock: task #{tid} TTL expired, auto punch-out")
            del self._records[tid]


# 全局单例
_clock = PunchClock()


def get_punch_clock() -> PunchClock:
    return _clock
