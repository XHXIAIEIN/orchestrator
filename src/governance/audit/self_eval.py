"""
Agent 自我评测闭环 — 把 Clawvard 考试结果灌进 learnings DB。

数据流:
  Clawvard 分数 → fitness rules 评估 → Gate/Tier 语义判定
                → DB learnings 表 (error entry_type)
                → DB learnings 表 (learning entry_type)
  出现 ≥3 次 → promoter 自动烧进 boot.md → 下次对话行为改变

Entrix patterns (Round 15):
  - Markdown-as-Code: rules in docs/fitness/*.md
  - Gate: HARD/SOFT/ADVISORY three-level semantics
  - Tier: FAST/NORMAL/DEEP progressive execution
  - Evidence Gap: code changed without tests → auto-escalate
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.governance.audit.fitness import (
    FitnessRule,
    FitnessVerdict,
    Gate,
    Tier,
    evaluate_rules,
    load_fitness_rules,
)
from src.governance.audit.learnings import append_error, append_learning
from src.governance.audit.promoter import scan_and_promote

log = logging.getLogger(__name__)

# Default fitness directory
_DEFAULT_FITNESS_DIR = "docs/fitness"


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
    verdict: FitnessVerdict | None = None


def ingest_exam(
    result: ExamResult,
    db,
    boot_path: str = ".claude/boot.md",
    fitness_dir: str = _DEFAULT_FITNESS_DIR,
    run_tier: Tier = Tier.NORMAL,
    changed_files: list[str] | None = None,
    test_files_changed: list[str] | None = None,
) -> SelfEvalOutcome:
    """
    把一次 Clawvard 考试结果灌进 learnings DB。

    1. 加载 fitness rules (docs/fitness/*.md)
    2. 按 Gate/Tier 语义评估每个维度
    3. HARD/SOFT fail → DB error + learning entries
    4. ADVISORY fail → 仅日志，不记录
    5. 达到晋升阈值 → 自动写 boot.md
    """
    rules = load_fitness_rules(fitness_dir)
    verdict = evaluate_rules(
        rules,
        result.dimensions,
        run_tier=run_tier,
        changed_files=changed_files,
        test_files_changed=test_files_changed,
    )

    errors_recorded = []
    learnings_recorded = []

    for rv in verdict.results:
        if rv.status in ("pass", "waived"):
            continue

        rule = rules.get(rv.dimension)
        if not rule:
            continue

        # ADVISORY gate: log only, no DB writes
        if rule.gate == Gate.ADVISORY:
            if rv.status == "fail":
                log.info("fitness advisory [%s]: %s (score=%s)", rv.dimension, rv.message, rv.score)
            continue

        # HARD or SOFT gate: record errors and learnings
        if rv.status in ("fail", "warn"):
            append_error(
                pattern_key=rule.pattern_key,
                summary=rule.error_summary or rv.message,
                detail=f"exam={result.exam_id} score={rv.score}/100 gate={rule.gate.value}. {rule.detail}",
                area="agent-self",
                db=db,
            )
            errors_recorded.append(f"{rv.dimension}={rv.score}")

            if rule.learning_summary:
                append_learning(
                    pattern_key=f"{rule.pattern_key}-fix",
                    summary=rule.learning_summary,
                    detail=f"Derived from {rv.dimension} score {rv.score}/100 in {result.exam_id}",
                    area="agent-self",
                    db=db,
                )
                learnings_recorded.append(rv.dimension)

    # Evidence gap logging
    if verdict.evidence_gaps:
        log.warning("fitness: evidence gaps detected — %s", verdict.evidence_gaps)
        for gap_file in verdict.evidence_gaps[:5]:
            append_error(
                pattern_key="evidence-gap",
                summary=f"Source changed without test evidence: {gap_file}",
                detail=f"File {gap_file} modified but no corresponding test file changed",
                area="agent-self",
                db=db,
            )

    # Check promotions
    promoted = scan_and_promote(db, boot_path, threshold=3)

    return SelfEvalOutcome(
        errors_recorded=errors_recorded,
        learnings_recorded=learnings_recorded,
        promoted=promoted,
        verdict=verdict,
    )


def ingest_all_exams(
    results: list[ExamResult],
    db,
    boot_path: str = ".claude/boot.md",
    fitness_dir: str = _DEFAULT_FITNESS_DIR,
    run_tier: Tier = Tier.NORMAL,
) -> SelfEvalOutcome:
    """灌入多次考试结果，最后统一检查晋升。"""
    all_errors = []
    all_learnings = []
    all_promoted = []
    last_verdict = None

    for r in results:
        outcome = ingest_exam(
            r, db=db, boot_path=boot_path,
            fitness_dir=fitness_dir, run_tier=run_tier,
        )
        all_errors.extend(outcome.errors_recorded)
        all_learnings.extend(outcome.learnings_recorded)
        all_promoted.extend(outcome.promoted)
        last_verdict = outcome.verdict

    return SelfEvalOutcome(
        errors_recorded=all_errors,
        learnings_recorded=all_learnings,
        promoted=all_promoted,
        verdict=last_verdict,
    )
