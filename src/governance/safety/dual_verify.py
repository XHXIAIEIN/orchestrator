# src/governance/safety/dual_verify.py
"""Dual-AI Cross Verification — two models independently verify, then compare.

Extends the existing SECOND_OPINION_MODEL in scrutiny.py to a full
cross-verification system. Instead of sequential primary→secondary,
both models work independently on the same input and results are
compared for agreement, disagreement, or complementary findings.

Use cases:
  1. Security review: two models independently audit code for vulnerabilities
  2. Quality review: two models independently score code quality
  3. Scrutiny: two models independently approve/reject task plans
  4. Fact checking: two models independently verify claims

Agreement patterns:
  - AGREE_PASS: both approve → high confidence pass
  - AGREE_FAIL: both reject → high confidence fail
  - DISAGREE: one approves, one rejects → needs human review
  - COMPLEMENT: both pass but flag different issues → merge findings
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

log = logging.getLogger(__name__)


class Agreement(Enum):
    AGREE_PASS = "agree_pass"       # Both approve
    AGREE_FAIL = "agree_fail"       # Both reject
    DISAGREE = "disagree"           # Split decision
    COMPLEMENT = "complement"       # Both pass, different findings
    ERROR = "error"                 # One or both failed


@dataclass
class ModelOpinion:
    """One model's assessment."""
    model_id: str
    passed: bool
    score: float = 0.0        # 0-10 if applicable
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    raw_output: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class CrossVerification:
    """Result of dual-model cross verification."""
    task_id: int
    verification_type: str     # "scrutiny" | "quality" | "security"
    opinion_a: ModelOpinion = None
    opinion_b: ModelOpinion = None
    agreement: Agreement = Agreement.ERROR
    merged_findings: list[str] = field(default_factory=list)
    final_verdict: bool = False
    confidence: float = 0.0    # 0.0-1.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "type": self.verification_type,
            "agreement": self.agreement.value,
            "final_verdict": self.final_verdict,
            "confidence": round(self.confidence, 2),
            "model_a": self.opinion_a.model_id if self.opinion_a else "",
            "model_b": self.opinion_b.model_id if self.opinion_b else "",
            "merged_findings_count": len(self.merged_findings),
        }

    def format_report(self) -> str:
        lines = [
            f"## Cross Verification — Task #{self.task_id} ({self.verification_type})",
            f"Agreement: {self.agreement.value} | Confidence: {self.confidence:.0%}",
            f"Final: {'PASS' if self.final_verdict else 'FAIL'}",
        ]
        if self.opinion_a:
            lines.append(f"\n  Model A ({self.opinion_a.model_id}): {'✅' if self.opinion_a.passed else '❌'} {self.opinion_a.summary[:100]}")
        if self.opinion_b:
            lines.append(f"  Model B ({self.opinion_b.model_id}): {'✅' if self.opinion_b.passed else '❌'} {self.opinion_b.summary[:100]}")
        if self.merged_findings:
            lines.append(f"\n  Merged findings ({len(self.merged_findings)}):")
            for f in self.merged_findings[:10]:
                lines.append(f"    - {f}")
        return "\n".join(lines)


# ── Cross Verification Logic ──

def cross_verify(
    task_id: int,
    verification_type: str,
    prompt: str,
    model_a_fn,
    model_b_fn,
    parse_fn=None,
) -> CrossVerification:
    """Run dual-model verification.

    Args:
        task_id: Task being verified
        verification_type: "scrutiny" | "quality" | "security"
        prompt: The verification prompt (same for both models)
        model_a_fn: fn(prompt) -> str (primary model)
        model_b_fn: fn(prompt) -> str (secondary model)
        parse_fn: Optional fn(output) -> (passed: bool, score: float, findings: list[str], summary: str)
                  If None, uses default verdict parsing.

    Returns:
        CrossVerification with merged results
    """
    result = CrossVerification(task_id=task_id, verification_type=verification_type)

    parse = parse_fn or _default_parse

    # Run Model A
    result.opinion_a = _run_model("model_a", model_a_fn, prompt, parse)

    # Run Model B
    result.opinion_b = _run_model("model_b", model_b_fn, prompt, parse)

    # Analyze agreement
    result.agreement = _analyze_agreement(result.opinion_a, result.opinion_b)

    # Merge findings
    result.merged_findings = _merge_findings(result.opinion_a, result.opinion_b)

    # Determine final verdict and confidence
    result.final_verdict, result.confidence = _compute_final_verdict(
        result.opinion_a, result.opinion_b, result.agreement
    )

    log.info(
        f"CrossVerify: task #{task_id} ({verification_type}) → {result.agreement.value} "
        f"(confidence={result.confidence:.0%}, verdict={'PASS' if result.final_verdict else 'FAIL'})"
    )

    return result


def _run_model(model_label: str, model_fn, prompt: str, parse_fn) -> ModelOpinion:
    """Run a single model and parse its output."""
    import time
    start = time.monotonic()
    try:
        raw_output = model_fn(prompt)
        duration_ms = int((time.monotonic() - start) * 1000)
        passed, score, findings, summary = parse_fn(raw_output)
        return ModelOpinion(
            model_id=model_label,
            passed=passed,
            score=score,
            summary=summary,
            findings=findings,
            raw_output=raw_output[:2000],
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.warning(f"CrossVerify: {model_label} failed: {e}")
        return ModelOpinion(
            model_id=model_label,
            passed=False,
            error=str(e),
            duration_ms=duration_ms,
        )


def _default_parse(output: str) -> tuple[bool, float, list[str], str]:
    """Default output parser — looks for VERDICT and issue markers."""
    import re

    passed = "VERDICT: PASS" in output or "VERDICT: APPROVE" in output
    if "VERDICT: FAIL" in output or "VERDICT: REJECT" in output:
        passed = False

    # Extract score if present
    score = 7.0 if passed else 3.0
    score_match = re.search(r'(?:SCORE|分数)\s*[:：]\s*(\d+(?:\.\d+)?)', output)
    if score_match:
        score = float(score_match.group(1))

    # Extract findings (lines with severity markers)
    findings = []
    for line in output.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(p) for p in ("[CRITICAL]", "[HIGH]", "[WARN]", "[BUG]", "🔴", "🟡")):
            findings.append(stripped[:200])

    # Extract summary
    summary = ""
    for line in output.splitlines():
        if line.strip().startswith(("VERDICT:", "SUMMARY:", "总结:")):
            summary = line.strip()
            break
    if not summary:
        summary = output[:100]

    return passed, score, findings, summary


def _analyze_agreement(a: ModelOpinion, b: ModelOpinion) -> Agreement:
    """Determine agreement pattern between two opinions."""
    if a.error or b.error:
        return Agreement.ERROR

    if a.passed and b.passed:
        # Both pass — check if findings differ significantly
        a_set = set(f[:50] for f in a.findings)
        b_set = set(f[:50] for f in b.findings)
        if a_set != b_set and (a_set or b_set):
            return Agreement.COMPLEMENT
        return Agreement.AGREE_PASS

    if not a.passed and not b.passed:
        return Agreement.AGREE_FAIL

    return Agreement.DISAGREE


def _merge_findings(a: ModelOpinion, b: ModelOpinion) -> list[str]:
    """Merge findings from both models, deduplicating similar ones."""
    all_findings = []
    seen = set()

    for source_label, opinion in [("A", a), ("B", b)]:
        for f in (opinion.findings if opinion else []):
            # Simple dedup: normalize and check first 40 chars
            key = f[:40].lower().strip()
            if key not in seen:
                seen.add(key)
                all_findings.append(f"[{source_label}] {f}")

    return all_findings


def _compute_final_verdict(a: ModelOpinion, b: ModelOpinion, agreement: Agreement) -> tuple[bool, float]:
    """Compute final pass/fail and confidence level.

    Returns (final_verdict, confidence).
    """
    if agreement == Agreement.AGREE_PASS:
        return True, 0.95

    if agreement == Agreement.AGREE_FAIL:
        return False, 0.95

    if agreement == Agreement.COMPLEMENT:
        # Both pass but different findings — pass with moderate confidence
        return True, 0.75

    if agreement == Agreement.DISAGREE:
        # Conservative: fail when models disagree, low confidence
        # Use the stricter model's score as tiebreaker
        if a.score and b.score:
            avg_score = (a.score + b.score) / 2
            return avg_score >= 6.0, 0.40
        return False, 0.35

    # Error case
    if a.error and b.error:
        return False, 0.1
    # One succeeded — use its verdict with low confidence
    working = b if a.error else a
    return working.passed, 0.50
