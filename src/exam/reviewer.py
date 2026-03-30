"""Coach Answer Reviewer — checks answer quality before submission.

Rules:
- Short answer detection (< min_length for dimension)
- Hedging detection for multiple choice ("A or B", "either", "depends")
- Coverage table reminder for long-form answers
- Truncation detection
"""
import re
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

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
class ReviewResult:
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def fail(self, issue: str, suggestion: str = ""):
        self.passed = False
        self.issues.append(issue)
        if suggestion:
            self.suggestions.append(suggestion)

    def warn(self, issue: str, suggestion: str = ""):
        self.issues.append(issue)
        if suggestion:
            self.suggestions.append(suggestion)


def _is_multiple_choice(prompt: str) -> bool:
    matches = _MC_PATTERN.findall(prompt)
    return len(matches) >= 3


def review_answer(question: dict, answer: str, dimension: str) -> ReviewResult:
    result = ReviewResult()
    prompt = question.get("prompt", "")
    is_mc = _is_multiple_choice(prompt)

    # Check 1: Too short
    min_len = _MIN_LENGTHS.get(dimension, 200)
    if not is_mc and len(answer) < min_len:
        result.fail("too_short", f"Answer is {len(answer)} chars, minimum for {dimension} is {min_len}")

    # Check 2: Multiple choice hedging
    if is_mc:
        for pattern in _HEDGE_PATTERNS:
            if pattern.search(answer):
                result.fail("hedging", "Multiple choice answer hedges between options — pick one")
                break
        if not re.search(r'^[A-D]\b', answer.strip()):
            if not re.search(r'\b[A-D]\)', answer[:50]):
                result.warn("no_clear_choice", "Answer doesn't start with a clear choice letter")

    # Check 3: Long-form coverage indicators
    if not is_mc and len(answer) > 2000:
        has_coverage = any(p.search(answer) for p in _COVERAGE_PATTERNS)
        if not has_coverage:
            result.warn("no_coverage_table", "Long answer has no coverage table/checklist")

    # Check 4: Truncation
    if answer.rstrip().endswith(("...", "```", "---")) and not answer.rstrip().endswith("```\n"):
        result.warn("possible_truncation", "Answer may be truncated")

    return result
