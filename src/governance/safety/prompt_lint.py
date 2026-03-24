# src/governance/safety/prompt_lint.py
"""Prompt Anti-Pattern Lint — detect common prompt quality issues.

Stolen from prompt-master's anti-pattern checklist. Scans department
SKILL.md and generated prompts for patterns known to degrade LLM output.

Anti-patterns detected:
  1. Contradictory instructions (do X ... don't do X)
  2. Vague quantifiers ("some", "a few", "maybe")
  3. Missing role/context framing
  4. Wall of text without structure (no headers, lists, or sections)
  5. Instruction overload (>2000 words of instructions)
  6. Hedging language ("try to", "if possible", "you might want to")
  7. Redundant repetition (same instruction repeated differently)
  8. Missing output format specification
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class LintIssue:
    """A single prompt anti-pattern finding."""
    rule: str          # rule identifier
    severity: str      # "warning" | "error"
    message: str
    location: str = "" # line number or section reference
    suggestion: str = ""


@dataclass
class LintReport:
    """Complete lint report for a prompt."""
    source: str        # file path or "generated"
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def clean(self) -> bool:
        return self.error_count == 0

    def format(self) -> str:
        if not self.issues:
            return f"✅ {self.source}: clean"
        lines = [f"Prompt Lint: {self.source} — {self.error_count} errors, {self.warning_count} warnings"]
        for i in self.issues:
            icon = "❌" if i.severity == "error" else "⚠"
            lines.append(f"  {icon} [{i.rule}] {i.message}")
            if i.suggestion:
                lines.append(f"    → {i.suggestion}")
        return "\n".join(lines)


# ── Lint Rules ──

def _check_vague_quantifiers(text: str) -> list[LintIssue]:
    """Detect vague language that leads to inconsistent LLM behavior."""
    vague_patterns = [
        (r'\bsome\s+\w+', "some"),
        (r'\ba few\b', "a few"),
        (r'\bmaybe\b', "maybe"),
        (r'\bperhaps\b', "perhaps"),
        (r'\bprobably\b', "probably"),
        (r'\b大概\b', "大概"),
        (r'\b可能\b', "可能"),
        (r'\b也许\b', "也许"),
    ]
    issues = []
    for pattern, word in vague_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if len(matches) >= 2:  # One occurrence is ok, repeated is a pattern
            issues.append(LintIssue(
                "vague-quantifier", "warning",
                f"Vague quantifier '{word}' used {len(matches)} times — LLM may interpret inconsistently",
                suggestion=f"Replace with specific numbers or clear criteria",
            ))
    return issues


def _check_hedging(text: str) -> list[LintIssue]:
    """Detect hedging language that weakens instructions."""
    hedges = [
        r'\btry to\b', r'\bif possible\b', r'\byou might want to\b',
        r'\byou could\b', r'\bconsider\b(?:\s+\w+){0,2}\s*\b',
        r'\b尽量\b', r'\b如果可以的话\b', r'\b你可以考虑\b',
    ]
    count = 0
    for pattern in hedges:
        count += len(re.findall(pattern, text, re.IGNORECASE))

    if count >= 3:
        return [LintIssue(
            "hedging", "warning",
            f"Hedging language detected {count} times — weakens directive authority",
            suggestion="Use direct imperatives instead of suggestions",
        )]
    return []


def _check_wall_of_text(text: str) -> list[LintIssue]:
    """Detect unstructured text walls."""
    lines = text.split("\n")
    # Check for long stretches without any structure markers
    consecutive_plain = 0
    max_plain = 0
    for line in lines:
        stripped = line.strip()
        is_structured = (
            stripped.startswith("#") or
            stripped.startswith("-") or
            stripped.startswith("*") or
            stripped.startswith("|") or
            re.match(r'^\d+\.', stripped) or
            not stripped  # blank lines are structure
        )
        if is_structured:
            max_plain = max(max_plain, consecutive_plain)
            consecutive_plain = 0
        else:
            consecutive_plain += 1
    max_plain = max(max_plain, consecutive_plain)

    issues = []
    if max_plain > 20:
        issues.append(LintIssue(
            "wall-of-text", "error",
            f"{max_plain} consecutive lines without headers, lists, or breaks",
            suggestion="Break into sections with ## headers and bullet points",
        ))
    return issues


def _check_instruction_overload(text: str) -> list[LintIssue]:
    """Detect prompts that are too long to be effective."""
    word_count = len(text.split())
    issues = []
    if word_count > 3000:
        issues.append(LintIssue(
            "overload", "error",
            f"Prompt is {word_count} words — likely exceeds effective instruction density",
            suggestion="Prioritize top 10-15 rules. Move examples to separate files.",
        ))
    elif word_count > 2000:
        issues.append(LintIssue(
            "overload", "warning",
            f"Prompt is {word_count} words — approaching instruction fatigue threshold",
            suggestion="Consider splitting into core rules + reference appendix",
        ))
    return issues


def _check_missing_role(text: str) -> list[LintIssue]:
    """Check if prompt establishes agent role/identity."""
    first_500 = text[:500].lower()
    role_signals = ["你是", "you are", "你的角色", "your role", "作为", "as a",
                    "## 身份", "## identity", "## role"]
    has_role = any(s in first_500 for s in role_signals)

    if not has_role and len(text) > 500:
        return [LintIssue(
            "missing-role", "warning",
            "No role/identity framing in first 500 chars",
            suggestion="Start with '你是...' or '## 身份' to ground the agent",
        )]
    return []


def _check_missing_output_format(text: str) -> list[LintIssue]:
    """Check if prompt specifies expected output format."""
    format_signals = ["output format", "输出格式", "返回格式", "response format",
                      "```json", "```yaml", "VERDICT:", "FORMAT:"]
    has_format = any(s in text.lower() for s in format_signals)

    if not has_format and len(text) > 300:
        return [LintIssue(
            "missing-format", "warning",
            "No output format specification detected",
            suggestion="Add expected output structure (JSON schema, example, or format block)",
        )]
    return []


def _check_contradictions(text: str) -> list[LintIssue]:
    """Simple heuristic for contradictory instructions."""
    # Look for "do X" ... "don't do X" patterns
    dos = set(re.findall(r'(?:必须|always|一定要)\s*(\w{2,})', text, re.IGNORECASE))
    donts = set(re.findall(r'(?:不要|never|禁止|don\'t)\s*(\w{2,})', text, re.IGNORECASE))
    conflicts = dos & donts

    issues = []
    for word in conflicts:
        issues.append(LintIssue(
            "contradiction", "error",
            f"Potential contradiction: both 'must {word}' and 'don't {word}' found",
            suggestion="Clarify which rule takes precedence and under what conditions",
        ))
    return issues


# ── Public API ──

ALL_CHECKS = [
    _check_vague_quantifiers,
    _check_hedging,
    _check_wall_of_text,
    _check_instruction_overload,
    _check_missing_role,
    _check_missing_output_format,
    _check_contradictions,
]


def lint_prompt(text: str, source: str = "prompt") -> LintReport:
    """Run all lint checks on a prompt text.

    Args:
        text: The prompt text to analyze
        source: Label for the report (e.g., file path)

    Returns:
        LintReport with all findings
    """
    report = LintReport(source=source)
    for check_fn in ALL_CHECKS:
        issues = check_fn(text)
        report.issues.extend(issues)
    return report


def lint_department(department: str, repo_root: str = "") -> LintReport:
    """Lint a department's SKILL.md prompt file."""
    if not repo_root:
        root = Path(__file__).resolve().parent
        while root != root.parent and not ((root / "departments").is_dir() and (root / "src").is_dir()):
            root = root.parent
        repo_root = str(root)

    skill_path = Path(repo_root) / "departments" / department / "SKILL.md"
    if not skill_path.exists():
        return LintReport(source=str(skill_path), issues=[
            LintIssue("missing-file", "error", f"SKILL.md not found for {department}")
        ])

    text = skill_path.read_text(encoding="utf-8")
    return lint_prompt(text, source=str(skill_path))


def lint_all_departments(repo_root: str = "") -> dict[str, LintReport]:
    """Lint all department SKILL.md files. Returns {dept_name: LintReport}."""
    if not repo_root:
        root = Path(__file__).resolve().parent
        while root != root.parent and not ((root / "departments").is_dir() and (root / "src").is_dir()):
            root = root.parent
        repo_root = str(root)

    dept_root = Path(repo_root) / "departments"
    reports = {}
    for dept_dir in sorted(dept_root.iterdir()):
        if dept_dir.is_dir() and not dept_dir.name.startswith((".", "_", "shared")):
            reports[dept_dir.name] = lint_department(dept_dir.name, repo_root)
    return reports
