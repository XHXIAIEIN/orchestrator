"""
Typed Handoff 状态机 — 任务完整生命周期。

Conitens 启发：部门间任务移交有完整生命周期，
每次状态转换有校验，非法转换被拒绝。

状态流转图：
  pending → scrutinizing → running → done
                                   → failed
                                   → gate_failed
                         → scrutiny_failed
                         → preflight_failed
  awaiting_approval → running (人工批准后)

  done → quality_review (工部→刑部)
  quality_review_failed → rework → running → done (循环)

  任何状态 → blocked (外部阻塞)
  blocked → pending (解除阻塞)

  * → escalated (人类介入)
"""
import logging
from enum import Enum

log = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    # 初始态
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"

    # 门下省审查
    SCRUTINIZING = "scrutinizing"
    SCRUTINY_FAILED = "scrutiny_failed"

    # 预检
    PREFLIGHT_FAILED = "preflight_failed"

    # 执行
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    # 质量门控
    GATE_FAILED = "gate_failed"

    # 阻塞
    BLOCKED = "blocked"

    # 人类介入
    ESCALATED = "escalated"


# 合法的状态转换
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.SCRUTINIZING, TaskStatus.RUNNING, TaskStatus.BLOCKED},
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.SCRUTINIZING, TaskStatus.BLOCKED},
    TaskStatus.SCRUTINIZING: {TaskStatus.RUNNING, TaskStatus.SCRUTINY_FAILED},
    TaskStatus.SCRUTINY_FAILED: {TaskStatus.PENDING, TaskStatus.ESCALATED},  # 可以重新提交
    TaskStatus.PREFLIGHT_FAILED: {TaskStatus.PENDING, TaskStatus.ESCALATED},
    TaskStatus.RUNNING: {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.GATE_FAILED, TaskStatus.BLOCKED},
    TaskStatus.DONE: {TaskStatus.ESCALATED},  # done 后只能人类介入改状态
    TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.ESCALATED},  # 可以重试
    TaskStatus.GATE_FAILED: {TaskStatus.PENDING, TaskStatus.ESCALATED},  # gate 失败可重试
    TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.ESCALATED},
    TaskStatus.ESCALATED: set(),  # 终态
}

# 终态集合
TERMINAL_STATES = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.GATE_FAILED,
                   TaskStatus.SCRUTINY_FAILED, TaskStatus.PREFLIGHT_FAILED, TaskStatus.ESCALATED}


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """检查状态转换是否合法。"""
    try:
        from_s = TaskStatus(from_status)
        to_s = TaskStatus(to_status)
    except ValueError:
        return True  # 未知状态不做校验（向后兼容）

    return to_s in VALID_TRANSITIONS.get(from_s, set())


def validate_transition(from_status: str, to_status: str) -> tuple[bool, str]:
    """校验状态转换，返回 (valid, reason)。"""
    if is_valid_transition(from_status, to_status):
        return True, ""

    try:
        from_s = TaskStatus(from_status)
        allowed = VALID_TRANSITIONS.get(from_s, set())
        allowed_str = ", ".join(s.value for s in allowed) if allowed else "none"
        return False, f"非法状态转换: {from_status} → {to_status}（允许: {allowed_str}）"
    except ValueError:
        return True, ""


def is_terminal(status: str) -> bool:
    """检查是否为终态。"""
    try:
        return TaskStatus(status) in TERMINAL_STATES
    except ValueError:
        return False


def get_available_transitions(status: str) -> list[str]:
    """获取当前状态可转换到的状态列表。"""
    try:
        s = TaskStatus(status)
        return [t.value for t in VALID_TRANSITIONS.get(s, set())]
    except ValueError:
        return []
