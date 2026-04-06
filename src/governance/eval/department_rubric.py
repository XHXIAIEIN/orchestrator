"""
Per-Department Rubric Definitions — Prompt Eval Closed Loop.

Each department gets a scoring rubric tailored to its mission.
Weights reflect what matters most for that role's output quality.

Source: department SKILL.md scope definitions + exam.md scoring anchors.

Usage:
    rubric = get_department_rubric("engineering")
    # Returns list[RubricCriterion] with department-specific weights
"""
from __future__ import annotations

from src.governance.eval.scoring import RubricCriterion


DEPARTMENT_RUBRICS: dict[str, list[RubricCriterion]] = {
    "engineering": [
        RubricCriterion(
            name="correctness", weight=0.35,
            description="Code correctly implements the requirements",
            satisfied="All requirements met, code runs without errors, edge cases handled",
            partial="Core functionality works but missing edge cases or minor bugs",
            not_satisfied="Fundamental errors, wrong approach, code doesn't run",
        ),
        RubricCriterion(
            name="completeness", weight=0.25,
            description="All aspects of the task are addressed",
            satisfied="Every requirement addressed with coverage table, tests included",
            partial="Most requirements addressed, some gaps in coverage",
            not_satisfied="Major requirements missing, truncated output",
        ),
        RubricCriterion(
            name="safety", weight=0.20,
            description="No security vulnerabilities or data safety issues",
            satisfied="No injection risks, proper validation, no hardcoded secrets",
            partial="Minor safety concerns that don't affect production",
            not_satisfied="Clear security vulnerabilities, injection risks",
        ),
        RubricCriterion(
            name="surgical_focus", weight=0.20,
            description="Changes stay within task scope, no unnecessary modifications",
            satisfied="Every changed line traces to the request, adjacent code untouched",
            partial="Mostly focused but includes minor unrelated cleanups",
            not_satisfied="Significant scope creep, unrelated refactoring, style changes",
        ),
    ],
    "quality": [
        RubricCriterion(
            name="finding_accuracy", weight=0.30,
            description="Identified issues are real problems, not false positives",
            satisfied="All flagged issues are genuine, with specific evidence",
            partial="Most findings are real, 1-2 false positives",
            not_satisfied="Many false positives, fabricated issues",
        ),
        RubricCriterion(
            name="severity_calibration", weight=0.25,
            description="Issue severity ratings match actual impact",
            satisfied="Critical/high/medium/low ratings accurately reflect risk",
            partial="Mostly calibrated, some over- or under-rating",
            not_satisfied="Consistently miscalibrated severity levels",
        ),
        RubricCriterion(
            name="coverage", weight=0.25,
            description="Review covers all important aspects of the code",
            satisfied="Logic, security, performance, style all checked",
            partial="Some areas reviewed thoroughly, others missed",
            not_satisfied="Superficial review missing major categories",
        ),
        RubricCriterion(
            name="anti_sycophancy", weight=0.20,
            description="Honest assessment, not just praise",
            satisfied="Reports real issues even if uncomfortable, doesn't inflate quality",
            partial="Mostly honest but softens some findings unnecessarily",
            not_satisfied="Rubber-stamps everything, avoids negative feedback",
        ),
    ],
    "operations": [
        RubricCriterion(
            name="diagnosis_accuracy", weight=0.35,
            description="Correctly identifies the root cause of operational issues",
            satisfied="Pinpoints exact root cause with evidence from logs/metrics",
            partial="Identifies general area but not precise root cause",
            not_satisfied="Wrong diagnosis, misreads symptoms",
        ),
        RubricCriterion(
            name="fix_safety", weight=0.30,
            description="Fixes don't introduce new problems or data loss",
            satisfied="Fix is targeted, reversible, with rollback plan",
            partial="Fix works but lacks rollback consideration",
            not_satisfied="Fix causes side effects or risks data loss",
        ),
        RubricCriterion(
            name="completeness", weight=0.20,
            description="All affected systems checked and addressed",
            satisfied="Full impact analysis, all dependencies considered",
            partial="Main issue fixed but related impacts not checked",
            not_satisfied="Partial fix that leaves related issues unresolved",
        ),
        RubricCriterion(
            name="rollback_awareness", weight=0.15,
            description="Considers rollback strategy and data preservation",
            satisfied="Explicit rollback plan, backups taken before changes",
            partial="Mentions rollback but no concrete plan",
            not_satisfied="No rollback consideration, destructive changes",
        ),
    ],
    "personnel": [
        RubricCriterion(
            name="metric_accuracy", weight=0.30,
            description="Numbers and statistics are correct and well-sourced",
            satisfied="All metrics verified against data, sources cited",
            partial="Mostly accurate with minor calculation errors",
            not_satisfied="Fabricated or significantly wrong metrics",
        ),
        RubricCriterion(
            name="trend_identification", weight=0.25,
            description="Identifies meaningful patterns and trends",
            satisfied="Catches significant trends with supporting data",
            partial="Notes obvious trends but misses subtle patterns",
            not_satisfied="Misses important trends or reports noise as signal",
        ),
        RubricCriterion(
            name="anomaly_detection", weight=0.25,
            description="Flags unusual data points and investigates them",
            satisfied="Catches real anomalies with plausible explanations",
            partial="Notes some anomalies but doesn't investigate",
            not_satisfied="Misses obvious anomalies or flags normal variation",
        ),
        RubricCriterion(
            name="actionability", weight=0.20,
            description="Provides concrete, actionable recommendations",
            satisfied="Clear next steps with specific implementation guidance",
            partial="Some actionable items but vague on specifics",
            not_satisfied="No practical guidance, purely descriptive",
        ),
    ],
    "protocol": [
        RubricCriterion(
            name="coverage", weight=0.30,
            description="All relevant communication aspects addressed",
            satisfied="Complete coverage of context, intent, and nuance",
            partial="Main points covered but some context missing",
            not_satisfied="Major aspects of the communication missed",
        ),
        RubricCriterion(
            name="accuracy", weight=0.30,
            description="Interpretation and translation fidelity",
            satisfied="Faithful to original meaning, no distortion",
            partial="Mostly accurate with minor interpretation shifts",
            not_satisfied="Significant meaning distortion or misinterpretation",
        ),
        RubricCriterion(
            name="prioritization", weight=0.20,
            description="Important items surfaced first, noise filtered",
            satisfied="Critical items lead, low-priority items deprioritized",
            partial="Reasonable ordering but some priority inversions",
            not_satisfied="Important items buried, noise dominates",
        ),
        RubricCriterion(
            name="false_positive_rate", weight=0.20,
            description="Flagged items are genuinely important",
            satisfied="Every flagged item deserves attention",
            partial="Most flags are relevant, some unnecessary",
            not_satisfied="Many false alarms, cry-wolf pattern",
        ),
    ],
    "security": [
        RubricCriterion(
            name="detection_accuracy", weight=0.35,
            description="Security issues found are real threats",
            satisfied="All detections are genuine vulnerabilities with proof",
            partial="Most detections valid, 1-2 false positives",
            not_satisfied="Many false positives or missed critical vulnerabilities",
        ),
        RubricCriterion(
            name="false_positive_rate", weight=0.25,
            description="Low rate of false security alerts",
            satisfied="Zero or near-zero false positives",
            partial="Occasional false positives but manageable",
            not_satisfied="High false positive rate undermining trust",
        ),
        RubricCriterion(
            name="severity_calibration", weight=0.25,
            description="Threat severity ratings match actual risk",
            satisfied="CVSS-aligned severity, considers exploitability context",
            partial="Mostly calibrated with minor over/under-rating",
            not_satisfied="Severity ratings detached from actual risk",
        ),
        RubricCriterion(
            name="remediation_quality", weight=0.15,
            description="Fix recommendations are specific and effective",
            satisfied="Concrete fix with code example, considers side effects",
            partial="General fix direction without specifics",
            not_satisfied="No remediation guidance or impractical suggestions",
        ),
    ],
}


def get_department_rubric(department: str) -> list[RubricCriterion]:
    """Get the scoring rubric for a specific department.

    Falls back to the generic 'code' rubric from scoring.py if
    the department isn't in DEPARTMENT_RUBRICS.
    """
    rubric = DEPARTMENT_RUBRICS.get(department)
    if rubric:
        return rubric

    # Fallback to generic
    from src.governance.eval.scoring import get_rubric_for_task
    return get_rubric_for_task("code")
