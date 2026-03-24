"""
事件即学习信号 — SubtaskOutcome 记录 planned vs actual。

swarm-tools 启发：每个任务记录计划做什么 vs 实际做了什么，
差异反馈给策略选择。

同时实现 Notebook Pattern（claude-swarm）：
  agent context 不是 truth，文件系统才是。
  每个任务的 outcome 持久化到文件，context compaction 后可恢复。
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_OUTCOME_DIR = _REPO_ROOT / "tmp" / "outcomes"


@dataclass
class PlannedAction:
    """计划中的动作。"""
    description: str
    files: list[str] = field(default_factory=list)
    expected_result: str = ""


@dataclass
class ActualOutcome:
    """实际执行结果。"""
    description: str
    files_changed: list[str] = field(default_factory=list)
    status: str = ""  # done/failed/partial
    unexpected: list[str] = field(default_factory=list)  # 计划外的事


@dataclass
class SubtaskOutcome:
    """计划 vs 实际的对比记录。"""
    task_id: int
    department: str
    planned: PlannedAction
    actual: ActualOutcome
    deviation_score: float = 0.0  # 0=完全匹配, 1=完全偏离
    lessons: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.deviation_score == 0:
            self.deviation_score = self._compute_deviation()

    def _compute_deviation(self) -> float:
        """计算计划与实际的偏离度。"""
        score = 0.0

        # 文件差异
        planned_files = set(self.planned.files)
        actual_files = set(self.actual.files_changed)
        if planned_files or actual_files:
            union = planned_files | actual_files
            intersection = planned_files & actual_files
            score += (1 - len(intersection) / len(union)) * 0.5 if union else 0

        # 状态
        if self.actual.status != "done":
            score += 0.3

        # 计划外动作
        if self.actual.unexpected:
            score += min(0.2, len(self.actual.unexpected) * 0.05)

        return min(1.0, score)


def record_outcome(task: dict, output: str, department: str) -> SubtaskOutcome:
    """从任务数据和输出构建 outcome 记录。"""
    import re
    spec = task.get("spec", {})

    # Planned
    planned = PlannedAction(
        description=task.get("action", ""),
        expected_result=spec.get("expected", ""),
    )

    # Actual
    file_patterns = re.findall(
        r'(?:src|departments|SOUL|dashboard|tests|data|docs)/[\w/.-]+\.\w+',
        output
    )
    actual = ActualOutcome(
        description=output[:200] if output else "",
        files_changed=list(set(file_patterns))[:20],
        status=task.get("status", "unknown"),
    )

    # 检测计划外动作
    unexpected_patterns = [
        (r'(?:also|另外|顺便)\s+(.+?)(?:\.|$)', "额外改动"),
        (r'(?:noticed|发现|注意到)\s+(.+?)(?:\.|$)', "意外发现"),
    ]
    for pattern, label in unexpected_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for m in matches:
            actual.unexpected.append(f"{label}: {m[:60]}")

    outcome = SubtaskOutcome(
        task_id=task.get("id", 0),
        department=department,
        planned=planned,
        actual=actual,
    )

    # 持久化到文件（Notebook Pattern）
    _persist_outcome(outcome)

    return outcome


def _persist_outcome(outcome: SubtaskOutcome):
    """持久化 outcome 到文件系统。"""
    _OUTCOME_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUTCOME_DIR / f"task-{outcome.task_id}.json"
    try:
        path.write_text(
            json.dumps(asdict(outcome), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning(f"outcome_tracker: failed to persist: {e}")


def load_outcome(task_id: int) -> dict:
    """从文件系统恢复 outcome（Notebook Pattern）。"""
    path = _OUTCOME_DIR / f"task-{task_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_deviation_stats(n: int = 20) -> dict:
    """获取最近 N 个 outcome 的偏离统计。"""
    if not _OUTCOME_DIR.exists():
        return {"total": 0, "avg_deviation": 0, "high_deviation": 0}

    outcomes = []
    for f in sorted(_OUTCOME_DIR.glob("task-*.json"), reverse=True)[:n]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            outcomes.append(data)
        except Exception:
            continue

    if not outcomes:
        return {"total": 0, "avg_deviation": 0, "high_deviation": 0}

    deviations = [o.get("deviation_score", 0) for o in outcomes]
    return {
        "total": len(outcomes),
        "avg_deviation": round(sum(deviations) / len(deviations), 3),
        "high_deviation": sum(1 for d in deviations if d > 0.5),
        "by_department": _group_by_dept(outcomes),
    }


def _group_by_dept(outcomes: list[dict]) -> dict:
    by_dept = {}
    for o in outcomes:
        dept = o.get("department", "unknown")
        by_dept.setdefault(dept, []).append(o.get("deviation_score", 0))
    return {
        dept: round(sum(scores) / len(scores), 3)
        for dept, scores in by_dept.items()
    }
