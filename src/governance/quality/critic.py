# src/governance/quality/critic.py
"""Critic — structured quality scoring interface.

Stolen from OpenHands' Critic auto-scoring pattern. Replaces free-text
quality review output with structured, multi-dimension scoring.

Dimensions:
  - correctness:   Does the code do what was asked? (0-10)
  - completeness:  Are all requirements addressed? (0-10)
  - style:         Code quality, naming, structure (0-10)
  - security:      No vulnerabilities introduced? (0-10)
  - performance:   Efficient? No obvious bottlenecks? (0-10)

The Critic can score from:
  1. Parsed eval_loop output (existing EVAL results)
  2. Raw LLM review text (extracts scores from structured format)
  3. Direct dict input (API/test usage)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DIMENSIONS = ("correctness", "completeness", "style", "security", "performance")

# Weights for composite scoring
DIMENSION_WEIGHTS = {
    "correctness": 0.30,
    "completeness": 0.25,
    "style": 0.15,
    "security": 0.20,
    "performance": 0.10,
}


@dataclass
class DimensionScore:
    """Single dimension score."""
    name: str
    score: int       # 0-10
    max_score: int = 10
    note: str = ""   # brief justification


@dataclass
class CriticVerdict:
    """Complete structured quality verdict."""
    task_id: int
    dimensions: list[DimensionScore] = field(default_factory=list)
    summary: str = ""
    raw_output: str = ""

    @property
    def composite(self) -> float:
        """Weighted composite score, 0-10."""
        if not self.dimensions:
            return 0.0
        total_w = 0.0
        total_s = 0.0
        for d in self.dimensions:
            w = DIMENSION_WEIGHTS.get(d.name, 0.15)
            total_w += w
            total_s += d.score * w
        return round(total_s / total_w, 1) if total_w > 0 else 0.0

    @property
    def passed(self) -> bool:
        """Pass if composite >= 6 and no dimension is critically low (< 3)."""
        if self.composite < 6.0:
            return False
        return not any(d.score < 3 for d in self.dimensions)

    @property
    def critical_dimensions(self) -> list[DimensionScore]:
        """Dimensions scoring below 4 — need attention."""
        return [d for d in self.dimensions if d.score < 4]

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "composite": self.composite,
            "passed": self.passed,
            "dimensions": {d.name: {"score": d.score, "note": d.note} for d in self.dimensions},
            "critical_dimensions": [d.name for d in self.critical_dimensions],
            "summary": self.summary,
        }

    def format_report(self) -> str:
        """Human-readable report for logging/display."""
        lines = [
            f"## Critic 评分 — Task #{self.task_id}",
            f"综合: {self.composite}/10 ({'PASS' if self.passed else 'FAIL'})",
            "",
        ]
        for d in self.dimensions:
            bar = "█" * d.score + "░" * (10 - d.score)
            flag = " ⚠" if d.score < 4 else ""
            lines.append(f"  {d.name:14s} [{bar}] {d.score:2d}/10{flag}")
            if d.note:
                lines.append(f"  {'':14s}   └ {d.note}")
        if self.summary:
            lines.append(f"\n{self.summary}")
        return "\n".join(lines)


# ── Scoring from different sources ──

def score_from_eval(eval_result, task_id: int = 0) -> CriticVerdict:
    """Convert an EvalResult (from eval_loop) into a CriticVerdict.

    Maps issue severity counts to dimension scores.
    """
    critical = eval_result.critical_count
    high = eval_result.high_count
    total_issues = len(eval_result.issues)

    # Derive scores from issue analysis
    correctness = max(0, 10 - critical * 4 - high * 2)
    completeness = max(0, 10 - critical * 3 - high * 1)

    # Style: count LOW issues
    low_count = sum(1 for i in eval_result.issues if i.severity.value <= 1)
    style_score = max(0, 10 - low_count)

    # Security: check for security-related issues
    sec_issues = sum(
        1 for i in eval_result.issues
        if any(kw in i.description.lower() for kw in ("security", "injection", "xss", "密钥", "secret", "vulnerability"))
    )
    security = max(0, 10 - sec_issues * 3)

    # Performance: check for performance-related issues
    perf_issues = sum(
        1 for i in eval_result.issues
        if any(kw in i.description.lower() for kw in ("performance", "slow", "n+1", "性能", "内存", "memory"))
    )
    performance = max(0, 10 - perf_issues * 2)

    return CriticVerdict(
        task_id=task_id,
        dimensions=[
            DimensionScore("correctness", min(10, correctness)),
            DimensionScore("completeness", min(10, completeness)),
            DimensionScore("style", min(10, style_score)),
            DimensionScore("security", min(10, security)),
            DimensionScore("performance", min(10, performance)),
        ],
        summary=eval_result.summary,
        raw_output=eval_result.raw_output,
    )


def score_from_text(text: str, task_id: int = 0) -> CriticVerdict:
    """Parse structured scores from LLM review text.

    Expected format in text:
        CORRECTNESS: 8/10 — reason
        COMPLETENESS: 7/10 — reason
        ...
    """
    dimensions = []
    for dim_name in DIMENSIONS:
        pattern = rf'{dim_name}\s*[:：]\s*(\d+)\s*/\s*10(?:\s*[—\-]\s*(.+))?'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            score = min(10, max(0, int(match.group(1))))
            note = (match.group(2) or "").strip()
            dimensions.append(DimensionScore(dim_name, score, note=note))
        else:
            dimensions.append(DimensionScore(dim_name, 5, note="未从文本中解析到"))

    # Extract summary
    summary = ""
    for line in text.splitlines():
        if line.strip().startswith(("VERDICT:", "SUMMARY:", "总结:")):
            summary = line.strip()
            break

    return CriticVerdict(
        task_id=task_id,
        dimensions=dimensions,
        summary=summary or text[:200],
        raw_output=text,
    )


def score_from_dict(data: dict, task_id: int = 0) -> CriticVerdict:
    """Create verdict from a pre-structured dict.

    Expected format:
        {"correctness": 8, "completeness": 7, "style": 9, "security": 8, "performance": 7}
    """
    dimensions = []
    for dim_name in DIMENSIONS:
        score = data.get(dim_name, 5)
        score = min(10, max(0, int(score)))
        dimensions.append(DimensionScore(dim_name, score))

    return CriticVerdict(task_id=task_id, dimensions=dimensions)
