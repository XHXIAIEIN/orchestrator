"""Skill red-flag checker — 16-point static audit for SKILL.md files.

Ported from ClawHub skill-vetter (Round 14 P2): pure regex-driven,
no LLM dependency. Each check returns a RiskLevel and a human-readable hint.

Checks 15-16 added from Claudeception steal (Round 36c):
  15. WEAK_DESCRIPTION — description-as-retrieval-key quality
  16. QUALITY_GATE_SPECIFICITY — Reusable/Non-trivial/Specific/Verified heuristic
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# ── Risk levels ─────────────────────────────────────────────────

class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Red flag dataclass ──────────────────────────────────────────

@dataclass(frozen=True)
class RedFlag:
    code: str
    message: str
    risk: RiskLevel
    line_hint: str


# ── Individual checkers ─────────────────────────────────────────
# Each returns a list of RedFlag (empty = pass).

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions"
    r"|disregard\s+(all\s+)?(prior|above|previous)"
    r"|you\s+are\s+now\s+a"
    r"|system\s*:\s*you\s+are"
    r"|jailbreak"
    r"|DAN\s+mode"
    r"|do\s+anything\s+now)",
    re.IGNORECASE,
)

_SECRET_PATTERNS = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}"
    r"|api[_-]?key\s*[:=]\s*['\"][^'\"]{8,}"
    r"|token\s*[:=]\s*['\"][^'\"]{8,}"
    r"|password\s*[:=]\s*['\"][^'\"]{4,}"
    r"|AKIA[0-9A-Z]{16}"  # AWS access key
    r"|ghp_[a-zA-Z0-9]{36}"  # GitHub PAT
    r"|Bearer\s+[a-zA-Z0-9._\-]{20,})",
    re.IGNORECASE,
)

_EXTERNAL_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)[^\s\)\"'>]+")

_DANGEROUS_PERMS = re.compile(
    r"\b(git\s+push|deploy|rm\s+-rf|drop\s+table|delete\s+database"
    r"|format\s+disk|shutdown|reboot|curl\s+.*\|\s*sh"
    r"|wget\s+.*\|\s*sh)\b",
    re.IGNORECASE,
)

_SELF_MODIFY = re.compile(
    r"(modify\s+(your(self)?|this)\s+(prompt|instruction|skill)"
    r"|rewrite\s+(your|this)\s+(prompt|instruction|skill)"
    r"|update\s+(your|this)\s+(prompt|instruction|skill)"
    r"|self[_-]?modif"
    r"|overwrite\s+(your|this)\s+(prompt|system))",
    re.IGNORECASE,
)

_HALLUCINATION_ENCOURAGE = re.compile(
    r"\b(be\s+creative|use\s+your\s+imagination|imagine\s+freely"
    r"|make\s+up|invent\s+details|feel\s+free\s+to\s+fabricate"
    r"|don'?t\s+worry\s+about\s+(accuracy|facts))\b",
    re.IGNORECASE,
)


def _find_line(content: str, match: re.Match) -> str:
    """Return the line number + snippet where a regex matched."""
    start = match.start()
    line_num = content[:start].count("\n") + 1
    line_text = content.splitlines()[line_num - 1].strip()
    snippet = line_text[:80] + ("..." if len(line_text) > 80 else "")
    return f"L{line_num}: {snippet}"


def _check_prompt_injection(content: str) -> list[RedFlag]:
    flags = []
    for m in _INJECTION_PATTERNS.finditer(content):
        flags.append(RedFlag(
            code="PROMPT_INJECTION",
            message=f"Prompt injection pattern detected: '{m.group()}'",
            risk=RiskLevel.CRITICAL,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_unbounded_tools(content: str) -> list[RedFlag]:
    # SKILL.md frontmatter should have a tools: [...] declaration
    has_tools_field = re.search(r"^tools\s*:", content, re.MULTILINE)
    all_tools = re.search(r"tools\s*:\s*\[?\s*\*\s*\]?", content, re.IGNORECASE)
    if all_tools:
        return [RedFlag(
            code="UNBOUNDED_TOOLS",
            message="Tool list is wildcard (*) — allows all tools",
            risk=RiskLevel.HIGH,
            line_hint="frontmatter tools field",
        )]
    if not has_tools_field:
        return [RedFlag(
            code="UNBOUNDED_TOOLS",
            message="No tools field declared — implicitly unbounded",
            risk=RiskLevel.HIGH,
            line_hint="missing tools: in frontmatter",
        )]
    return []


def _check_no_authority_ceiling(content: str) -> list[RedFlag]:
    authority_keywords = re.compile(
        r"\b(DO\s+NOT|must\s+not|never|forbidden|prohibited|scope|boundary|ceiling"
        r"|not\s+allowed|restricted|off[_-]?limits|permission\s+denied)\b",
        re.IGNORECASE,
    )
    if not authority_keywords.search(content):
        return [RedFlag(
            code="NO_AUTHORITY_CEILING",
            message="No authority boundary or restriction language found",
            risk=RiskLevel.HIGH,
            line_hint="(entire document)",
        )]
    return []


def _check_secrets_in_prompt(content: str) -> list[RedFlag]:
    flags = []
    for m in _SECRET_PATTERNS.finditer(content):
        flags.append(RedFlag(
            code="SECRETS_IN_PROMPT",
            message=f"Possible secret/credential: '{m.group()[:30]}...'",
            risk=RiskLevel.CRITICAL,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_excessive_permissions(content: str) -> list[RedFlag]:
    flags = []
    for m in _DANGEROUS_PERMS.finditer(content):
        flags.append(RedFlag(
            code="EXCESSIVE_PERMISSIONS",
            message=f"Dangerous permission declared: '{m.group()}'",
            risk=RiskLevel.HIGH,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_no_output_format(content: str) -> list[RedFlag]:
    output_keywords = re.compile(
        r"\b(output|format|response\s+format|result|return|```)\b",
        re.IGNORECASE,
    )
    if not output_keywords.search(content):
        return [RedFlag(
            code="NO_OUTPUT_FORMAT",
            message="No output format specification found",
            risk=RiskLevel.MEDIUM,
            line_hint="(entire document)",
        )]
    return []


def _check_vague_objective(content: str) -> list[RedFlag]:
    # Strip frontmatter, look at the first heading or description
    body = re.sub(r"^---.*?---", "", content, flags=re.DOTALL).strip()
    # First non-heading paragraph
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    if paragraphs:
        first_para = paragraphs[0]
        if len(first_para) < 50:
            return [RedFlag(
                code="VAGUE_OBJECTIVE",
                message=f"Objective too short ({len(first_para)} chars): '{first_para[:60]}'",
                risk=RiskLevel.MEDIUM,
                line_hint="first paragraph after frontmatter",
            )]
    else:
        return [RedFlag(
            code="VAGUE_OBJECTIVE",
            message="No objective paragraph found",
            risk=RiskLevel.MEDIUM,
            line_hint="(entire document)",
        )]
    return []


def _check_missing_constraints(content: str) -> list[RedFlag]:
    constraint_keywords = re.compile(
        r"\b(constraint|limit|restrict|must|shall|require|rule|DO\s+NOT)\b",
        re.IGNORECASE,
    )
    if not constraint_keywords.search(content):
        return [RedFlag(
            code="MISSING_CONSTRAINTS",
            message="No constraint or rule language found",
            risk=RiskLevel.MEDIUM,
            line_hint="(entire document)",
        )]
    return []


def _check_external_url(content: str) -> list[RedFlag]:
    flags = []
    for m in _EXTERNAL_URL.finditer(content):
        flags.append(RedFlag(
            code="EXTERNAL_URL",
            message=f"External URL found: '{m.group()[:60]}'",
            risk=RiskLevel.HIGH,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_recursive_self_modify(content: str) -> list[RedFlag]:
    flags = []
    for m in _SELF_MODIFY.finditer(content):
        flags.append(RedFlag(
            code="RECURSIVE_SELF_MODIFY",
            message=f"Self-modification instruction: '{m.group()}'",
            risk=RiskLevel.HIGH,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_no_error_handling(content: str) -> list[RedFlag]:
    error_keywords = re.compile(
        r"\b(error|fail|exception|fallback|retry|edge\s+case|FAILED)\b",
        re.IGNORECASE,
    )
    if not error_keywords.search(content):
        return [RedFlag(
            code="NO_ERROR_HANDLING",
            message="No error/failure handling mentioned",
            risk=RiskLevel.LOW,
            line_hint="(entire document)",
        )]
    return []


def _check_oversized(content: str) -> list[RedFlag]:
    if len(content) > 5000:
        return [RedFlag(
            code="OVERSIZED",
            message=f"Skill prompt is {len(content)} chars (limit: 5000)",
            risk=RiskLevel.MEDIUM,
            line_hint=f"total length: {len(content)}",
        )]
    return []


def _check_hallucination_risk(content: str) -> list[RedFlag]:
    flags = []
    for m in _HALLUCINATION_ENCOURAGE.finditer(content):
        flags.append(RedFlag(
            code="HALLUCINATION_RISK",
            message=f"Hallucination-encouraging language: '{m.group()}'",
            risk=RiskLevel.MEDIUM,
            line_hint=_find_line(content, m),
        ))
    return flags


def _check_missing_identity(content: str) -> list[RedFlag]:
    identity_keywords = re.compile(
        r"\b(department|role|identity|you\s+are|persona|name\s*:)\b",
        re.IGNORECASE,
    )
    if not identity_keywords.search(content):
        return [RedFlag(
            code="MISSING_IDENTITY",
            message="No department or role identity declared",
            risk=RiskLevel.LOW,
            line_hint="(entire document)",
        )]
    return []


def _check_weak_description(content: str) -> list[RedFlag]:
    """Check if the frontmatter description is too short or lacks trigger conditions.

    A good description includes: specific trigger words, use-when scenarios,
    and NOT-for exclusions. Source: Claudeception (Round 36c steal).
    """
    desc_match = re.search(
        r"^description\s*:\s*[\"']?(.*?)(?:[\"']?\s*$|\n---)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not desc_match:
        return [RedFlag(
            code="WEAK_DESCRIPTION",
            message="No description field in frontmatter — skill will never be discovered",
            risk=RiskLevel.HIGH,
            line_hint="frontmatter",
        )]
    desc = desc_match.group(1).strip().strip("\"'")
    flags: list[RedFlag] = []
    # Too short
    if len(desc) < 40:
        flags.append(RedFlag(
            code="WEAK_DESCRIPTION",
            message=f"Description too short ({len(desc)} chars) — aim for 80+ with trigger words",
            risk=RiskLevel.MEDIUM,
            line_hint=f"description: {desc[:60]}",
        ))
    # No trigger conditions
    trigger_patterns = re.compile(
        r"\b(use\s+when|trigger|NOT\s+for|when\s+to\s+use|examples?\s*:)\b",
        re.IGNORECASE,
    )
    if not trigger_patterns.search(desc):
        flags.append(RedFlag(
            code="WEAK_DESCRIPTION",
            message="Description lacks trigger conditions (Use when: / NOT for:)",
            risk=RiskLevel.MEDIUM,
            line_hint=f"description: {desc[:60]}...",
        ))
    return flags


def _check_quality_gate(content: str) -> list[RedFlag]:
    """Check the 4-point quality gate: Reusable, Non-trivial, Specific, Verified.

    This is a heuristic check — it looks for signals that suggest the skill
    may fail one or more quality criteria. Source: Claudeception (Round 36c).
    """
    body = re.sub(r"^---.*?---", "", content, flags=re.DOTALL).strip()
    flags: list[RedFlag] = []
    # Specificity check: does the body contain concrete triggers (error messages, commands, filenames)?
    concrete_patterns = re.compile(
        r"(`[^`]+`"         # inline code
        r"|```"             # code blocks
        r"|\berror\b"       # error mentions
        r"|\bcommand\b"     # command references
        r"|step\s+\d+)",    # numbered steps
        re.IGNORECASE,
    )
    if not concrete_patterns.search(body):
        flags.append(RedFlag(
            code="QUALITY_GATE_SPECIFICITY",
            message="No concrete examples (code, errors, steps) — may be too abstract to be actionable",
            risk=RiskLevel.LOW,
            line_hint="(body content)",
        ))
    return flags


# ── All 16 checkers in order ───────────────────────────────────

_ALL_CHECKS = [
    _check_prompt_injection,       # 1
    _check_unbounded_tools,        # 2
    _check_no_authority_ceiling,   # 3
    _check_secrets_in_prompt,      # 4
    _check_excessive_permissions,  # 5
    _check_no_output_format,       # 6
    _check_vague_objective,        # 7
    _check_missing_constraints,    # 8
    _check_external_url,           # 9
    _check_recursive_self_modify,  # 10
    _check_no_error_handling,      # 11
    _check_oversized,              # 12
    _check_hallucination_risk,     # 13
    _check_missing_identity,       # 14
    _check_weak_description,       # 15  (Round 36c: description-as-retrieval-key)
    _check_quality_gate,           # 16  (Round 36c: Claudeception 4-point gate)
]


# ── Public API ──────────────────────────────────────────────────

def vet_skill(content: str) -> list[RedFlag]:
    """Run all 14 red-flag checks on a SKILL.md content string."""
    flags: list[RedFlag] = []
    for checker in _ALL_CHECKS:
        flags.extend(checker(content))
    return flags


def vet_all_departments(departments_dir: str = "departments") -> dict[str, list[RedFlag]]:
    """Scan all departments/<name>/SKILL.md and return per-department flags."""
    results: dict[str, list[RedFlag]] = {}
    dept_path = Path(departments_dir)
    if not dept_path.is_dir():
        return results
    for skill_file in sorted(dept_path.glob("*/SKILL.md")):
        dept_name = skill_file.parent.name
        content = skill_file.read_text(encoding="utf-8")
        results[dept_name] = vet_skill(content)
    return results


def risk_summary(flags: list[RedFlag]) -> dict:
    """Summarize flag counts by risk level."""
    counts = {level.value: 0 for level in RiskLevel}
    for f in flags:
        counts[f.risk.value] += 1
    counts["total"] = len(flags)
    return counts
