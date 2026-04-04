"""
Epochs + ScoreReducer (R38 — stolen from Inspect AI / promptfoo).

Run the same eval sample N times (epochs), aggregate via reducer to reduce
stochastic variance. Observed 35-point score variance in single-run Clawvard.

Reducers:
  - mean:     arithmetic mean of N runs
  - mode:     most frequent verdict (robust to outliers)
  - max:      optimistic — best of N
  - pass_at_k: P(at least 1 pass in N) — for difficulty calibration

Usage:
    runner = EpochRunner(epochs=3, reducer="mode")
    result = await runner.run(eval_fn, sample)
    # EpochResult with individual_scores + reduced_score + variance
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Any

log = logging.getLogger(__name__)


class ScoreReducer(str, Enum):
    """Aggregation strategy for multi-epoch scores."""
    MEAN = "mean"
    MODE = "mode"
    MAX = "max"
    PASS_AT_K = "pass_at_k"


@dataclass
class EpochResult:
    """Result of running N epochs of an eval sample."""
    scores: list[float]
    reduced: float
    reducer: str
    variance: float
    epoch_count: int

    def to_dict(self) -> dict:
        return {
            "scores": [round(s, 4) for s in self.scores],
            "reduced": round(self.reduced, 4),
            "reducer": self.reducer,
            "variance": round(self.variance, 6),
            "epoch_count": self.epoch_count,
        }


def reduce_scores(scores: list[float], reducer: ScoreReducer) -> float:
    """Reduce a list of scores to a single value using the given strategy.

    Args:
        scores: list of 0.0-1.0 scores from individual epochs.
        reducer: aggregation strategy.

    Returns:
        Single reduced score (0.0-1.0).
    """
    if not scores:
        return 0.0

    if reducer == ScoreReducer.MEAN:
        return sum(scores) / len(scores)

    if reducer == ScoreReducer.MODE:
        # Round to 2 decimal places before counting to handle float noise
        rounded = [round(s, 2) for s in scores]
        counter = Counter(rounded)
        # Most common; ties broken by highest score
        most_common = sorted(counter.items(), key=lambda x: (-x[1], -x[0]))
        return most_common[0][0]

    if reducer == ScoreReducer.MAX:
        return max(scores)

    if reducer == ScoreReducer.PASS_AT_K:
        # P(at least 1 pass in N) — score >= 0.8 counts as pass
        passes = sum(1 for s in scores if s >= 0.8)
        return 1.0 if passes > 0 else 0.0

    # Fallback
    return sum(scores) / len(scores)


class EpochRunner:
    """Run an eval function multiple times and aggregate results.

    Args:
        epochs: number of times to run each sample (default 3).
        reducer: aggregation strategy name or ScoreReducer enum (default "mode").
    """

    def __init__(self, epochs: int = 3, reducer: str | ScoreReducer = "mode"):
        self.epochs = max(1, epochs)
        if isinstance(reducer, str):
            self.reducer = ScoreReducer(reducer)
        else:
            self.reducer = reducer

    async def run(
        self,
        eval_fn: Callable[[Any], Any],
        sample: Any,
    ) -> EpochResult:
        """Run eval_fn on sample N times and aggregate.

        Args:
            eval_fn: async callable (sample) -> float, returns 0.0-1.0 score.
            sample: the eval sample to pass to eval_fn.

        Returns:
            EpochResult with individual scores, reduced score, and variance.
        """
        scores: list[float] = []

        for epoch in range(self.epochs):
            try:
                score = await eval_fn(sample)
                scores.append(float(score))
            except Exception as e:
                log.warning(f"epoch {epoch + 1}/{self.epochs} failed: {e}")
                scores.append(0.0)

        reduced = reduce_scores(scores, self.reducer)
        mean = sum(scores) / len(scores) if scores else 0.0
        variance = sum((s - mean) ** 2 for s in scores) / len(scores) if scores else 0.0

        result = EpochResult(
            scores=scores,
            reduced=reduced,
            reducer=self.reducer.value,
            variance=variance,
            epoch_count=len(scores),
        )

        log.info(
            f"epochs: {self.epochs}x run → reduced={reduced:.3f} "
            f"(var={variance:.4f}, reducer={self.reducer.value})"
        )
        return result
