"""
Novelty Policy — 阻止 agent 重试已失败路径。

SoulFlow 启发：除非有新信息，否则不重试相同的失败方案。

检查方式：
  1. 新任务和最近的失败任务做相似度比较
  2. 相似度 > 0.8 且无新信息 → 拒绝或标记
  3. 有新信息（新 context、新 observation） → 放行

集成点：Governor._dispatch_task 的 preflight 阶段。
"""
import logging
from difflib import SequenceMatcher

log = logging.getLogger(__name__)


def check_novelty(new_action: str, new_spec: dict,
                   recent_failures: list[dict],
                   similarity_threshold: float = 0.8) -> tuple[bool, str]:
    """检查新任务是否与最近的失败任务过于相似。

    Args:
        new_action: 新任务的 action
        new_spec: 新任务的 spec
        recent_failures: 最近失败的任务列表
        similarity_threshold: 相似度阈值

    Returns:
        (novel, reason): novel=True 表示允许执行
    """
    if not recent_failures:
        return True, ""

    new_text = _task_fingerprint(new_action, new_spec)

    for failed in recent_failures:
        failed_action = failed.get("action", "")
        failed_spec = failed.get("spec", {})
        if isinstance(failed_spec, str):
            import json
            try:
                failed_spec = json.loads(failed_spec)
            except (json.JSONDecodeError, TypeError):
                failed_spec = {}

        failed_text = _task_fingerprint(failed_action, failed_spec)

        similarity = SequenceMatcher(None, new_text, failed_text).ratio()

        if similarity >= similarity_threshold:
            # 检查是否有新信息
            new_observation = new_spec.get("observation", "")
            failed_observation = failed_spec.get("observation", "")

            if new_observation and new_observation != failed_observation:
                log.info(f"novelty: similar to failed task #{failed.get('id')}, "
                         f"but has new observation. Allowing.")
                return True, f"与失败任务 #{failed.get('id')} 相似（{similarity:.0%}），但有新信息"

            new_context = new_spec.get("rework_count", 0)
            if new_context > 0:
                # 返工任务有新的刑部反馈，视为新信息
                return True, "返工任务，含刑部反馈"

            log.warning(f"novelty: task too similar to failed #{failed.get('id')} "
                        f"(similarity={similarity:.0%}), no new info")
            return False, (
                f"与最近失败的任务 #{failed.get('id')} 相似度 {similarity:.0%}，"
                f"且无新信息。请提供新的 observation 或修改方案后重试。"
            )

    return True, ""


def _task_fingerprint(action: str, spec: dict) -> str:
    """生成任务的文本指纹，用于相似度比较。"""
    parts = [
        action,
        spec.get("department", ""),
        spec.get("problem", ""),
        spec.get("summary", ""),
        spec.get("expected", ""),
    ]
    return " ".join(p for p in parts if p).lower()


def get_recent_failures(db, department: str, n: int = 5) -> list[dict]:
    """从 DB 获取部门最近的失败任务。"""
    try:
        tasks = db.get_tasks(limit=50)
        failures = [
            t for t in tasks
            if t.get("status") in ("failed", "gate_failed", "scrutiny_failed")
            and (isinstance(t.get("spec"), dict) and t["spec"].get("department") == department
                 or department == "")
        ]
        return failures[:n]
    except Exception:
        return []
