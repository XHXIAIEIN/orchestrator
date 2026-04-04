"""
Regression Detection with Bootstrap Confidence Intervals (R38 — stolen from Braintrust).

Quantitative regression alerts: bootstrap 10,000 samples to build CI for
score difference. If CI doesn't contain 0 → statistically significant change.

Replaces qualitative trend analysis with statistical rigor.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


@dataclass
class BootstrapResult:
    """Result of a bootstrap regression test."""
    mean_diff: float
    ci_lower: float
    ci_upper: float
    significant: bool
    p_value_approx: float
    n_bootstrap: int
    direction: Literal["improved", "regressed", "stable"]

    def to_dict(self) -> dict:
        return {
            "mean_diff": round(self.mean_diff, 4),
            "ci_lower": round(self.ci_lower, 4),
            "ci_upper": round(self.ci_upper, 4),
            "significant": self.significant,
            "p_value_approx": round(self.p_value_approx, 4),
            "n_bootstrap": self.n_bootstrap,
            "direction": self.direction,
        }


def _mean(values: list[float]) -> float:
    """Arithmetic mean without numpy."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _resample(data: list[float], rng: random.Random) -> list[float]:
    """Resample with replacement."""
    n = len(data)
    return [data[rng.randrange(n)] for _ in range(n)]


def bootstrap_regression(
    before: list[float],
    after: list[float],
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> BootstrapResult:
    """Bootstrap test for score regression between two sets of scores.

    Computes the distribution of (mean_after - mean_before) via resampling.
    Positive mean_diff = improvement, negative = regression.

    Args:
        before: scores from the baseline run.
        after: scores from the new run.
        n_bootstrap: number of bootstrap resamples (default 10,000).
        confidence: confidence level for the interval (default 0.95).
        seed: optional random seed for reproducibility.

    Returns:
        BootstrapResult with CI, significance, direction, and approximate p-value.
    """
    if not before or not after:
        log.warning("bootstrap_regression: empty score list(s), returning stable")
        return BootstrapResult(
            mean_diff=0.0, ci_lower=0.0, ci_upper=0.0,
            significant=False, p_value_approx=1.0,
            n_bootstrap=0, direction="stable",
        )

    rng = random.Random(seed)
    diffs: list[float] = []

    for _ in range(n_bootstrap):
        b_sample = _resample(before, rng)
        a_sample = _resample(after, rng)
        diffs.append(_mean(a_sample) - _mean(b_sample))

    diffs.sort()

    # Percentile CI
    alpha = 1.0 - confidence
    lo_idx = int(alpha / 2 * n_bootstrap)
    hi_idx = int((1.0 - alpha / 2) * n_bootstrap) - 1
    lo_idx = max(0, min(lo_idx, n_bootstrap - 1))
    hi_idx = max(0, min(hi_idx, n_bootstrap - 1))

    ci_lower = diffs[lo_idx]
    ci_upper = diffs[hi_idx]
    mean_diff = _mean(diffs)

    # Significant if CI doesn't contain 0
    significant = not (ci_lower <= 0.0 <= ci_upper)

    # Approximate p-value: fraction of diffs on "wrong side" of 0
    if mean_diff >= 0:
        # If improvement, p = fraction of diffs <= 0
        p_value = sum(1 for d in diffs if d <= 0) / n_bootstrap
    else:
        # If regression, p = fraction of diffs >= 0
        p_value = sum(1 for d in diffs if d >= 0) / n_bootstrap

    # Direction
    if significant and mean_diff > 0:
        direction = "improved"
    elif significant and mean_diff < 0:
        direction = "regressed"
    else:
        direction = "stable"

    result = BootstrapResult(
        mean_diff=mean_diff,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        significant=significant,
        p_value_approx=p_value,
        n_bootstrap=n_bootstrap,
        direction=direction,
    )

    log.info(
        f"regression: {direction} (diff={mean_diff:+.4f}, "
        f"CI=[{ci_lower:.4f}, {ci_upper:.4f}], p≈{p_value:.4f})"
    )
    return result


def check_regression(
    experiment_history: list[dict],
    lookback: int = 5,
) -> list[BootstrapResult]:
    """Compare the latest experiment against previous entries.

    Args:
        experiment_history: list of {"name": str, "scores": list[float]}
            in chronological order. Each entry is one experiment run.
        lookback: how many previous entries to compare against (default 5).

    Returns:
        List of BootstrapResult, one per comparison (most recent first).
        Empty list if fewer than 2 entries.
    """
    if len(experiment_history) < 2:
        return []

    latest = experiment_history[-1]
    after_scores = latest.get("scores", [])
    if not after_scores:
        return []

    # Compare against each of the lookback entries
    results: list[BootstrapResult] = []
    start_idx = max(0, len(experiment_history) - 1 - lookback)

    for i in range(len(experiment_history) - 2, start_idx - 1, -1):
        entry = experiment_history[i]
        before_scores = entry.get("scores", [])
        if not before_scores:
            continue

        result = bootstrap_regression(before_scores, after_scores)
        results.append(result)

        if result.significant:
            log.info(
                f"regression check: {latest.get('name', '?')} vs {entry.get('name', '?')} "
                f"→ {result.direction} (p≈{result.p_value_approx:.4f})"
            )

    return results
