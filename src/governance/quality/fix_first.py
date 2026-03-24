# src/governance/quality/fix_first.py
"""Fix-First Review — classify review findings as AUTO_FIX vs ASK.

evolution-v2 referenced gstack's /review pattern: instead of just
PASS/FAIL, classify each finding into:
  - AUTO_FIX: agent can fix this autonomously (style, formatting, simple bugs)
  - ASK: needs human decision (architecture, trade-offs, unclear requirements)
  - SKIP: informational only, no action needed

This plugs into eval_loop.py's EvalResult to add actionability classification.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class FixAction(Enum):
    AUTO_FIX = "auto_fix"    # Agent can fix without asking
    ASK = "ask"              # Needs human decision
    SKIP = "skip"            # No action needed


@dataclass
class ClassifiedFinding:
    """An eval finding with fix classification."""
    description: str
    severity: str           # from EvalIssue
    action: FixAction
    reason: str = ""        # why this classification
    estimated_effort: str = ""  # "trivial" | "small" | "medium" | "large"


@dataclass
class FixFirstReport:
    """Fix-First classification of all findings from a review."""
    task_id: int
    findings: list[ClassifiedFinding]

    @property
    def auto_fixable(self) -> list[ClassifiedFinding]:
        return [f for f in self.findings if f.action == FixAction.AUTO_FIX]

    @property
    def needs_human(self) -> list[ClassifiedFinding]:
        return [f for f in self.findings if f.action == FixAction.ASK]

    @property
    def skippable(self) -> list[ClassifiedFinding]:
        return [f for f in self.findings if f.action == FixAction.SKIP]

    @property
    def can_auto_resolve(self) -> bool:
        """True if ALL actionable findings are auto-fixable (no human needed)."""
        actionable = [f for f in self.findings if f.action != FixAction.SKIP]
        return all(f.action == FixAction.AUTO_FIX for f in actionable) if actionable else True

    def format(self) -> str:
        lines = [f"Fix-First Report — Task #{self.task_id}"]
        if self.auto_fixable:
            lines.append(f"\n🔧 AUTO_FIX ({len(self.auto_fixable)}):")
            for f in self.auto_fixable:
                lines.append(f"  - [{f.severity}] {f.description[:80]} ({f.estimated_effort})")
        if self.needs_human:
            lines.append(f"\n❓ ASK ({len(self.needs_human)}):")
            for f in self.needs_human:
                lines.append(f"  - [{f.severity}] {f.description[:80]}")
                if f.reason:
                    lines.append(f"    Reason: {f.reason}")
        if self.skippable:
            lines.append(f"\n⏭ SKIP ({len(self.skippable)})")
        lines.append(f"\nAuto-resolvable: {'YES' if self.can_auto_resolve else 'NO — needs human'}")
        return "\n".join(lines)


# ── Classification Rules ──

# Patterns that agents can always fix autonomously
AUTO_FIX_PATTERNS = [
    # Style issues
    (r"(?:naming|命名|变量名|函数名)", "style fix"),
    (r"(?:import|导入)\s+(?:order|顺序|unused|未使用)", "import cleanup"),
    (r"(?:whitespace|空格|缩进|indent|format|格式)", "formatting"),
    (r"(?:typo|拼写|spelling)", "typo fix"),
    (r"(?:missing\s+type|类型注解|type\s*hint|annotation)", "type annotation"),
    (r"(?:unused\s+variable|未使用的变量|dead\s*code)", "dead code removal"),
    (r"(?:docstring|文档字符串|注释)", "documentation"),
    (r"(?:lint|pylint|flake8|ruff)", "linter fix"),
    # Simple logic fixes
    (r"(?:off.by.one|差一|boundary)", "boundary fix"),
    (r"(?:missing\s+return|缺少\s*return)", "missing return"),
    (r"(?:missing\s+break|缺少\s*break)", "missing break"),
    (r"(?:null\s*check|空值检查|None\s*check)", "null safety"),
]

# Patterns that need human judgment
ASK_PATTERNS = [
    (r"(?:architecture|架构|设计)", "architectural decision"),
    (r"(?:trade.?off|权衡|取舍)", "trade-off decision"),
    (r"(?:requirement|需求|unclear|不明确)", "unclear requirement"),
    (r"(?:breaking\s*change|破坏性|backward)", "backward compatibility"),
    (r"(?:performance\s+vs|性能\s*vs)", "performance trade-off"),
    (r"(?:security\s+model|安全模型|auth)", "security model decision"),
    (r"(?:schema\s*change|schema\s*migration|数据库迁移)", "schema decision"),
    (r"(?:api\s*design|接口设计)", "API design decision"),
    (r"(?:delete|删除|remove\s+feature)", "feature removal decision"),
]

# Patterns that are informational only
SKIP_PATTERNS = [
    (r"(?:^info|^note|^提示|^注意|^fyi)", "informational"),
    (r"(?:consider|建议考虑|you might)", "suggestion only"),
    (r"(?:nit|nitpick|小问题)", "nitpick"),
]


def classify_finding(description: str, severity: str) -> ClassifiedFinding:
    """Classify a single review finding into AUTO_FIX / ASK / SKIP."""
    desc_lower = description.lower()

    # INFO severity is always SKIP
    if severity.lower() in ("info", "low"):
        for pattern, reason in SKIP_PATTERNS:
            if re.search(pattern, desc_lower, re.IGNORECASE):
                return ClassifiedFinding(description, severity, FixAction.SKIP, reason, "trivial")
        # Low severity that matches auto-fix is still auto-fixable
        for pattern, reason in AUTO_FIX_PATTERNS:
            if re.search(pattern, desc_lower, re.IGNORECASE):
                return ClassifiedFinding(description, severity, FixAction.AUTO_FIX, reason, "trivial")
        return ClassifiedFinding(description, severity, FixAction.SKIP, "low severity", "trivial")

    # Check ASK patterns first (higher priority for CRITICAL/HIGH)
    if severity.lower() in ("critical", "high"):
        for pattern, reason in ASK_PATTERNS:
            if re.search(pattern, desc_lower, re.IGNORECASE):
                return ClassifiedFinding(description, severity, FixAction.ASK, reason, "medium")

    # Check AUTO_FIX patterns
    for pattern, reason in AUTO_FIX_PATTERNS:
        if re.search(pattern, desc_lower, re.IGNORECASE):
            effort = "trivial" if severity.lower() in ("low", "info") else "small"
            return ClassifiedFinding(description, severity, FixAction.AUTO_FIX, reason, effort)

    # CRITICAL with no pattern match → ASK (conservative)
    if severity.lower() == "critical":
        return ClassifiedFinding(description, severity, FixAction.ASK, "critical severity, no auto-fix pattern", "large")

    # HIGH with no pattern match → AUTO_FIX (agent should try)
    if severity.lower() == "high":
        return ClassifiedFinding(description, severity, FixAction.AUTO_FIX, "high severity, agent should attempt", "medium")

    # Default
    return ClassifiedFinding(description, severity, FixAction.AUTO_FIX, "default", "small")


def classify_eval_result(eval_result, task_id: int = 0) -> FixFirstReport:
    """Classify all findings from an EvalResult into Fix-First categories.

    Args:
        eval_result: EvalResult from eval_loop.py
        task_id: Task ID for the report

    Returns:
        FixFirstReport with classified findings
    """
    findings = []
    for issue in eval_result.issues:
        severity_name = issue.severity.name if hasattr(issue.severity, "name") else str(issue.severity)
        classified = classify_finding(issue.description, severity_name)
        findings.append(classified)

    report = FixFirstReport(task_id=task_id, findings=findings)

    if report.findings:
        log.info(
            f"FixFirst: task #{task_id} — "
            f"{len(report.auto_fixable)} auto-fix, "
            f"{len(report.needs_human)} ask, "
            f"{len(report.skippable)} skip"
        )

    return report
