"""
Agent 自我评测闭环 — 把 Clawvard 考试结果灌进 learnings 管线。

数据流:
  Clawvard 分数 → 识别弱项 → 写入 .learnings/ERRORS.md (Pattern-Key)
                            → 写入 .learnings/LEARNINGS.md (改进策略)
  出现 ≥3 次 → promoter 自动烧进 boot.md → 下次对话行为改变

这是 Orchestrator 对着自己用自诊断系统的关键一环。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.governance.audit.learnings import append_error, append_learning
from src.governance.audit.promoter import scan_and_promote

# 维度 → 弱项模式描述 + 行为矫正规则
DIMENSION_RULES: dict[str, dict] = {
    "execution": {
        "pattern_key": "agent-exec-ceiling",
        "error_summary": "Agent execution score capped at 80 — code output lacks edge-case coverage and tests",
        "learning_summary": "After writing code, STOP and add boundary tests before submitting — do not rely on momentum",
        "detail": "Clawvard execution dimension consistently scores 80/100. Root cause: code implementations are functional but miss edge cases, error paths, and test coverage. The agent writes in one continuous flow without pausing to verify completeness.",
        "threshold": 85,
    },
    "reflection": {
        "pattern_key": "agent-performative-reflection",
        "error_summary": "Agent reflection declining — acknowledges problems but does not modify behavior (performative reflection)",
        "learning_summary": "When expressing uncertainty, WIDEN the interval and COMMIT to the wider range — saying 'might be too narrow' without changing is worse than not reflecting",
        "detail": "Clawvard reflection dimension dropped 100→90→65 across 3 exams. The agent recognizes overconfidence but does not actually adjust confidence intervals. This 'performative reflection' scores worse than no reflection because the evaluator detects knowledge-action gap.",
        "threshold": 85,
    },
    "understanding": {
        "pattern_key": "agent-understanding-variance",
        "error_summary": "Agent understanding score unstable (90-95) — open-ended analysis quality varies",
        "learning_summary": "For analysis tasks, structure response as: constraints first, then tradeoffs, then recommendation — prevents rambling",
        "detail": "Understanding dimension fluctuates between 90-95. Open-ended questions (competitive analysis, metric interpretation) get variable depth depending on answer length and structure.",
        "threshold": 90,
    },
    "tooling": {
        "pattern_key": "agent-tooling-variance",
        "error_summary": "Agent tooling score unstable (80-95) — tool selection reasoning sometimes shallow",
        "learning_summary": "When recommending tools, explicitly state WHY alternatives are worse — not just why the pick is good",
        "detail": "Tooling dimension swings between 80-95 across exams. The agent sometimes gives correct tool recommendations without sufficiently explaining tradeoffs of alternatives.",
        "threshold": 90,
    },
}

# 不需要矫正的维度（稳定高分）
STABLE_DIMENSIONS = {"retrieval", "reasoning", "eq", "memory"}


@dataclass
class ExamResult:
    exam_id: str
    dimensions: dict[str, float]  # dimension_name → score (0-100)
    grade: str
    percentile: int


@dataclass
class SelfEvalOutcome:
    errors_recorded: list[str]
    learnings_recorded: list[str]
    promoted: list[str]


def ingest_exam(
    result: ExamResult,
    learnings_dir: str = ".learnings",
    boot_path: str = ".claude/boot.md",
) -> SelfEvalOutcome:
    """
    把一次 Clawvard 考试结果灌进 learnings 管线。

    1. 低于阈值的维度 → 写 ERRORS.md (Pattern-Key 计数 +1)
    2. 对应改进策略 → 写 LEARNINGS.md
    3. 达到晋升阈值 → 自动写 boot.md
    """
    errors_path = str(Path(learnings_dir) / "ERRORS.md")
    learnings_path = str(Path(learnings_dir) / "LEARNINGS.md")

    errors_recorded = []
    learnings_recorded = []

    for dim, score in result.dimensions.items():
        if dim in STABLE_DIMENSIONS:
            continue

        rule = DIMENSION_RULES.get(dim)
        if not rule:
            continue

        if score < rule["threshold"]:
            # 记录错误模式
            append_error(
                pattern_key=rule["pattern_key"],
                summary=rule["error_summary"],
                detail=f"exam={result.exam_id} score={score}/100. {rule['detail']}",
                area="agent-self",
                file_path=errors_path,
            )
            errors_recorded.append(f"{dim}={score}")

            # 记录改进策略
            append_learning(
                pattern_key=f"{rule['pattern_key']}-fix",
                summary=rule["learning_summary"],
                detail=f"Derived from {dim} score {score}/100 in {result.exam_id}",
                area="agent-self",
                file_path=learnings_path,
            )
            learnings_recorded.append(dim)

    # 检查是否有达到晋升阈值的 pattern
    promoted_errors = scan_and_promote(errors_path, boot_path, threshold=3)
    promoted_learnings = scan_and_promote(learnings_path, boot_path, threshold=3)

    return SelfEvalOutcome(
        errors_recorded=errors_recorded,
        learnings_recorded=learnings_recorded,
        promoted=promoted_errors + promoted_learnings,
    )


def ingest_all_exams(
    results: list[ExamResult],
    learnings_dir: str = ".learnings",
    boot_path: str = ".claude/boot.md",
) -> SelfEvalOutcome:
    """灌入多次考试结果，最后统一检查晋升。"""
    all_errors = []
    all_learnings = []
    all_promoted = []

    for r in results:
        outcome = ingest_exam(r, learnings_dir, boot_path)
        all_errors.extend(outcome.errors_recorded)
        all_learnings.extend(outcome.learnings_recorded)
        all_promoted.extend(outcome.promoted)

    return SelfEvalOutcome(
        errors_recorded=all_errors,
        learnings_recorded=all_learnings,
        promoted=all_promoted,
    )
