"""
Fact Confidence Ranking (R29 — stolen from bytedance/deer-flow).

Sort facts/memories by confidence descending before injection into system prompt.
Token budget enforcement: stop injecting when budget exhausted.
High-frequency, high-confidence facts get priority.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RankedFact:
    """A fact with computed confidence and estimated token cost."""
    content: str
    confidence: float       # 0.0–1.0
    source: str
    token_estimate: int     # chars // 4 approximation


def compute_confidence(
    apply_count: int = 0,
    recurrence: int = 0,
    days_since_access: int = 999,
) -> float:
    """Compute confidence score from usage signals.

    Formula:
        min(1.0, (apply_count * 0.15) + (recurrence * 0.2)
                  + max(0, (30 - days_since_access) / 30 * 0.3))
    """
    score = (
        apply_count * 0.15
        + recurrence * 0.2
        + max(0.0, (30 - days_since_access) / 30 * 0.3)
    )
    return max(0.0, min(1.0, score))


def rank_and_budget(
    facts: list[RankedFact],
    token_budget: int = 2000,
) -> list[RankedFact]:
    """Sort facts by confidence descending, include until token budget exhausted.

    Returns the included subset, still sorted by confidence.
    """
    sorted_facts = sorted(facts, key=lambda f: f.confidence, reverse=True)
    result: list[RankedFact] = []
    total_tokens = 0

    for fact in sorted_facts:
        if total_tokens + fact.token_estimate > token_budget:
            break
        result.append(fact)
        total_tokens += fact.token_estimate

    log.debug("confidence_ranker: included %d/%d facts (%d tokens used of %d budget)",
              len(result), len(facts), total_tokens, token_budget)
    return result
