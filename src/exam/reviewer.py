"""Coach Answer Reviewer — checks answer quality before submission.

Rules:
- Short answer detection (< min_length for dimension)
- Hedging detection for multiple choice ("A or B", "either", "depends")
- Coverage table reminder for long-form answers
- Truncation detection

Gate semantics (entrix Round 15):
- HARD: blocks submission (fail() calls)
- SOFT: degrades weighted score (warn() calls)
- ADVISORY: report only (advisory() calls)
"""
import re
import logging
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class ReviewGate(Enum):
    """Gate level for individual review issues."""
    HARD = "hard"       # blocks submission
    SOFT = "soft"       # degrades score
    ADVISORY = "advisory"  # report only

_MC_PATTERN = re.compile(r'[A-D]\)\s')

_HEDGE_PATTERNS = [
    re.compile(r'\b(?:either\s+[A-D]\s+or\s+[A-D])\b', re.IGNORECASE),
    re.compile(r'\b(?:could be\s+[A-D]\s+or\s+[A-D])\b', re.IGNORECASE),
    re.compile(r'\b(?:both\s+[A-D]\s+and\s+[A-D]\s+(?:are|could|might))\b', re.IGNORECASE),
]

_COVERAGE_PATTERNS = [
    re.compile(r'\|.*\|.*\|'),
    re.compile(r'(?:requirement|req)\s*#?\d', re.IGNORECASE),
    re.compile(r'coverage', re.IGNORECASE),
    re.compile(r'✓|✅|PASS', re.IGNORECASE),
]

# LRN-011: API truncates answers silently above this threshold (prac-8e03f361)
_ANSWER_WARN_CHARS = 2500
_ANSWER_DANGER_CHARS = 4000

_MIN_LENGTHS = {
    "eq": 1000,
    "execution": 500,
    "tooling": 300,
    "reflection": 400,
    "understanding": 400,
    "reasoning": 200,
    "retrieval": 200,
    "memory": 200,
}


@dataclass
class ReviewIssue:
    """A single review finding with gate semantics."""
    code: str
    message: str
    gate: ReviewGate = ReviewGate.SOFT


@dataclass
class ReviewResult:
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    findings: list[ReviewIssue] = field(default_factory=list)

    def fail(self, issue: str, suggestion: str = ""):
        """HARD gate — blocks submission."""
        self.passed = False
        self.issues.append(issue)
        self.findings.append(ReviewIssue(code=issue, message=suggestion, gate=ReviewGate.HARD))
        if suggestion:
            self.suggestions.append(suggestion)

    def warn(self, issue: str, suggestion: str = ""):
        """SOFT gate — degrades score but doesn't block."""
        self.issues.append(issue)
        self.findings.append(ReviewIssue(code=issue, message=suggestion, gate=ReviewGate.SOFT))
        if suggestion:
            self.suggestions.append(suggestion)

    def advisory(self, issue: str, suggestion: str = ""):
        """ADVISORY gate — report only, no impact."""
        self.findings.append(ReviewIssue(code=issue, message=suggestion, gate=ReviewGate.ADVISORY))

    @property
    def hard_count(self) -> int:
        return sum(1 for f in self.findings if f.gate == ReviewGate.HARD)

    @property
    def soft_count(self) -> int:
        return sum(1 for f in self.findings if f.gate == ReviewGate.SOFT)

    @property
    def advisory_count(self) -> int:
        return sum(1 for f in self.findings if f.gate == ReviewGate.ADVISORY)


def _is_multiple_choice(prompt: str) -> bool:
    matches = _MC_PATTERN.findall(prompt)
    return len(matches) >= 3


def review_answer(question: dict, answer: str, dimension: str) -> ReviewResult:
    result = ReviewResult()
    prompt = question.get("prompt", "")
    is_mc = _is_multiple_choice(prompt)

    # Check 0: Too long — API truncation risk (LRN-011)
    if len(answer) > _ANSWER_DANGER_CHARS:
        result.fail("too_long", f"Answer is {len(answer)} chars — WILL be truncated (limit ~{_ANSWER_DANGER_CHARS}). Compress.")
    elif len(answer) > _ANSWER_WARN_CHARS:
        result.warn("near_truncation", f"Answer is {len(answer)} chars — approaching truncation zone ({_ANSWER_WARN_CHARS})")

    # Check 1: Too short
    min_len = _MIN_LENGTHS.get(dimension, 200)
    if not is_mc and len(answer) < min_len:
        result.fail("too_short", f"Answer is {len(answer)} chars, minimum for {dimension} is {min_len}")

    # Check 2: Multiple choice hedging + format safety
    if is_mc:
        for pattern in _HEDGE_PATTERNS:
            if pattern.search(answer):
                result.fail("hedging", "Multiple choice answer hedges between options — pick one")
                break
        if not re.search(r'^[A-D]\b', answer.strip()):
            if not re.search(r'\b[A-D]\)', answer[:50]):
                result.warn("no_clear_choice", "Answer doesn't start with a clear choice letter")
        # LRN-012: Bare letter on first line can be misread by grading parser
        first_line = answer.strip().split("\n")[0].strip()
        if len(first_line) == 1 and first_line in "ABCD":
            result.warn("bare_mc_letter", f"Bare '{first_line}' on first line — use '{first_line})' to avoid parser ambiguity")

    # Check 3: Long-form coverage indicators
    if not is_mc and len(answer) > 2000:
        has_coverage = any(p.search(answer) for p in _COVERAGE_PATTERNS)
        if not has_coverage:
            result.warn("no_coverage_table", "Long answer has no coverage table/checklist")

    # Check 4: Truncation
    if answer.rstrip().endswith(("...", "```", "---")) and not answer.rstrip().endswith("```\n"):
        result.warn("possible_truncation", "Answer may be truncated")

    return result
