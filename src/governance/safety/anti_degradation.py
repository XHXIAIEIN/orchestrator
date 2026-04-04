# src/governance/safety/anti_degradation.py
"""Anti-Degradation Protocol — Pre-modification scoring gate.

Source: ClawHub proactive-agent + evolver + self-improving (Round 14)

Problem: Self-improving agents degrade over time. Each modification *feels*
like an optimization, but without quantified cost/benefit analysis the system
drifts toward complexity with no measurable gain.

Solution: Before any self-modification executes, score it against four
weighted dimensions. If the total score is below the gate threshold, the
modification is rejected before it can cause harm.

Scoring formula:
    frequency      × 3   (how often does the target pattern occur?)
    failure_reduction × 3 (does this fix a measured failure mode?)
    burden_reduction × 2  (does this remove manual steps or reduce tokens?)
    token_efficiency × 2  (does this use fewer tokens for the same result?)

    Gate: weighted_score < 50 → REJECT

Forbidden actions (always rejected regardless of score):
    - Adding complexity to "appear smarter"
    - Changes that cannot be verified by eval
    - Decisions justified solely by "intuition"

Integrates with:
    - experiment.py → provides the keep/discard loop AFTER execution
    - This module is the gate BEFORE execution
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

# Dimension weights
WEIGHTS = {
    "frequency": 3,
    "failure_reduction": 3,
    "burden_reduction": 2,
    "token_efficiency": 2,
}

# Gate threshold (0-100 scale)
GATE_THRESHOLD = 50

# Forbidden justification patterns (auto-reject)
FORBIDDEN_JUSTIFICATIONS = [
    "intuition",
    "feels right",
    "should be better",
    "looks cleaner",
    "more elegant",
    "best practice",  # without specific evidence
    "just in case",
    "might be useful",
]


@dataclass
class ModificationProposal:
    """A proposed self-modification to be evaluated.

    All scores are 0-10 where:
        0 = no impact
        5 = moderate impact
        10 = maximum impact
    """
    name: str
    description: str
    justification: str

    # Scores (0-10)
    frequency: float = 0.0          # How often does the target pattern occur?
    failure_reduction: float = 0.0  # Does this fix a measured failure?
    burden_reduction: float = 0.0   # Does this remove manual work / tokens?
    token_efficiency: float = 0.0   # Fewer tokens for same result?

    # Verification
    can_be_verified: bool = True    # Is there an eval that can measure impact?
    has_baseline: bool = True       # Do we have a baseline score to compare?


@dataclass
class GateDecision:
    """Result of the anti-degradation gate evaluation."""
    action: Literal["approve", "reject"]
    score: float
    threshold: float
    reason: str
    dimension_scores: dict[str, float]

    @property
    def approved(self) -> bool:
        return self.action == "approve"


def evaluate_proposal(proposal: ModificationProposal) -> GateDecision:
    """Evaluate a modification proposal against the anti-degradation gate.

    Returns a GateDecision with approve/reject and detailed reasoning.
    """
    # Check forbidden justifications first
    justification_lower = proposal.justification.lower()
    for forbidden in FORBIDDEN_JUSTIFICATIONS:
        if forbidden in justification_lower:
            return GateDecision(
                action="reject",
                score=0.0,
                threshold=GATE_THRESHOLD,
                reason=f"Forbidden justification: '{forbidden}'. "
                       f"Provide measurable evidence instead.",
                dimension_scores={},
            )

    # Check verification requirements
    if not proposal.can_be_verified:
        return GateDecision(
            action="reject",
            score=0.0,
            threshold=GATE_THRESHOLD,
            reason="Modification cannot be verified by eval. "
                   "Only verifiable changes are allowed.",
            dimension_scores={},
        )

    if not proposal.has_baseline:
        return GateDecision(
            action="reject",
            score=0.0,
            threshold=GATE_THRESHOLD,
            reason="No baseline score available. "
                   "Run eval to establish baseline before proposing changes.",
            dimension_scores={},
        )

    # Calculate weighted score
    dimension_scores = {}
    weighted_total = 0.0
    max_possible = 0.0

    for dim_name, weight in WEIGHTS.items():
        raw = getattr(proposal, dim_name, 0.0)
        raw = max(0.0, min(10.0, raw))  # Clamp to 0-10
        weighted = raw * weight
        dimension_scores[dim_name] = weighted
        weighted_total += weighted
        max_possible += 10.0 * weight

    # Normalize to 0-100 scale
    score = (weighted_total / max_possible) * 100 if max_possible > 0 else 0.0

    if score < GATE_THRESHOLD:
        return GateDecision(
            action="reject",
            score=round(score, 1),
            threshold=GATE_THRESHOLD,
            reason=f"Score {score:.1f} below threshold {GATE_THRESHOLD}. "
                   f"Modification does not justify its cost.",
            dimension_scores=dimension_scores,
        )

    return GateDecision(
        action="approve",
        score=round(score, 1),
        threshold=GATE_THRESHOLD,
        reason=f"Score {score:.1f} meets threshold {GATE_THRESHOLD}. "
               f"Proceed with eval baseline comparison.",
        dimension_scores=dimension_scores,
    )


def quick_check(name: str, justification: str, *,
                frequency: float = 0, failure_reduction: float = 0,
                burden_reduction: float = 0, token_efficiency: float = 0,
                can_verify: bool = True, has_baseline: bool = True) -> bool:
    """Convenience function: returns True if the modification should proceed.

    Usage:
        if anti_degradation.quick_check(
            "shorten_system_prompt",
            "System prompt uses 2000 tokens but eval shows same score at 1200",
            token_efficiency=8,
            burden_reduction=6,
        ):
            # proceed with modification
    """
    proposal = ModificationProposal(
        name=name,
        description=name,
        justification=justification,
        frequency=frequency,
        failure_reduction=failure_reduction,
        burden_reduction=burden_reduction,
        token_efficiency=token_efficiency,
        can_be_verified=can_verify,
        has_baseline=has_baseline,
    )
    decision = evaluate_proposal(proposal)
    if not decision.approved:
        log.info(f"anti_degradation: REJECTED '{name}' — {decision.reason}")
    return decision.approved
