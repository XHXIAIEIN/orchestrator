"""
确定性优先解析 — 能用规则解决的冲突不发给 LLM。

SoulFlow 启发：确定性可解的冲突不发给 LLM，只有真正的分歧才升级。

同时包含 LLM 不可用时的确定性 fallback（Lumina OS 启发）。

分层解析：
  1. 规则引擎（确定性）→ 有规则匹配就直接返回
  2. 模板 fallback → LLM 不可用时的预定义响应
  3. LLM 调用 → 只有真正需要智能判断时才调用
"""
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


# ── 确定性规则 ──

def resolve_deterministic(event_type: str, context: dict) -> Optional[dict]:
    """尝试用确定性规则解决。返回 None 表示需要 LLM。"""

    # 重复任务冲突 → 保留优先级高的
    if event_type == "conflict.duplicate_task":
        tasks = context.get("tasks", [])
        if len(tasks) == 2:
            priorities = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_tasks = sorted(tasks, key=lambda t: priorities.get(t.get("priority", "medium"), 2))
            return {
                "action": "keep_higher_priority",
                "keep": sorted_tasks[0].get("id"),
                "drop": sorted_tasks[1].get("id"),
                "reason": "保留优先级更高的任务",
            }

    # 部门冲突 → 按权限等级决定
    if event_type == "conflict.department_overlap":
        depts = context.get("departments", [])
        # MUTATE 部门优先于 READ 部门
        mutate = [d for d in depts if d in ("engineering", "operations")]
        if mutate:
            return {
                "action": "assign_to",
                "department": mutate[0],
                "reason": "MUTATE 权限的部门优先",
            }

    # 文件冲突 → 先到先得
    if event_type == "conflict.file_lock":
        return {
            "action": "queue",
            "reason": "文件已被其他任务占用，排队等待",
        }

    # Gate 失败 → 确定性处理
    if event_type == "gate.no_secrets_failed":
        return {
            "action": "block",
            "reason": "检测到密钥文件，自动阻止提交",
        }

    return None


# ── 确定性 Fallback 模板 ──
# LLM 不可用时的预定义响应

FALLBACK_TEMPLATES: dict[str, dict] = {
    "task.scrutiny": {
        "verdict": "APPROVE",
        "reason": "LLM 不可用，按默认策略放行（低风险任务）",
        "condition": lambda spec: spec.get("department") in ("protocol", "personnel"),
    },
    "task.scrutiny_high_risk": {
        "verdict": "REJECT",
        "reason": "LLM 不可用，高风险任务默认拒绝",
        "condition": lambda spec: spec.get("department") in ("engineering", "operations"),
    },
    "task.review": {
        "verdict": "PASS",
        "reason": "LLM 不可用，跳过自动审查",
    },
}


def get_deterministic_fallback(task_type: str, spec: dict = None) -> Optional[dict]:
    """LLM 不可用时的确定性 fallback。"""
    for key, template in FALLBACK_TEMPLATES.items():
        if key in task_type:
            condition = template.get("condition")
            if condition and spec and not condition(spec):
                continue
            return {k: v for k, v in template.items() if k != "condition"}

    return None
