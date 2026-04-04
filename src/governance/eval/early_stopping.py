"""
EarlyStopping Protocol (R38 — stolen from Inspect AI).

Per-category early stopping: if agent scores 3 consecutive correct in a
category, skip remaining samples for that category. Saves tokens on
categories the agent has clearly mastered.

Bi-directional: schedule-time (decide what to run) + complete-time (report back).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class CategoryTracker:
    """Tracks consecutive correct answers for one eval category."""
    category: str
    consecutive_correct: int = 0
    total: int = 0
    stopped: bool = False
    stop_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "consecutive_correct": self.consecutive_correct,
            "total": self.total,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
        }


class EarlyStoppingPolicy:
    """Per-category adaptive stopping for eval runs.

    Stops evaluating a category once the agent demonstrates consistent mastery
    (N consecutive correct answers), saving tokens on categories that don't
    need further testing.

    Args:
        consecutive_threshold: number of consecutive correct answers to trigger stop.
        min_samples: minimum samples that must be evaluated before stopping is allowed.
    """

    def __init__(self, consecutive_threshold: int = 3, min_samples: int = 2):
        self.consecutive_threshold = max(1, consecutive_threshold)
        self.min_samples = max(1, min_samples)
        self._trackers: dict[str, CategoryTracker] = {}

    def _get_tracker(self, category: str) -> CategoryTracker:
        """Get or create tracker for a category."""
        if category not in self._trackers:
            self._trackers[category] = CategoryTracker(category=category)
        return self._trackers[category]

    def should_skip(self, category: str) -> bool:
        """Check if a category has been stopped (mastered).

        Returns True if the category should be skipped.
        """
        tracker = self._trackers.get(category)
        if tracker is None:
            return False
        return tracker.stopped

    def report(self, category: str, score: float, pass_threshold: float = 0.8) -> None:
        """Report a score for a category and update tracking state.

        Args:
            category: the eval category name.
            score: the score (0.0-1.0) for this sample.
            pass_threshold: score >= this value counts as correct.
        """
        tracker = self._get_tracker(category)

        if tracker.stopped:
            log.debug(f"early_stopping: ignoring report for stopped category '{category}'")
            return

        tracker.total += 1

        if score >= pass_threshold:
            tracker.consecutive_correct += 1
        else:
            tracker.consecutive_correct = 0

        # Check stop condition
        if (
            tracker.consecutive_correct >= self.consecutive_threshold
            and tracker.total >= self.min_samples
        ):
            tracker.stopped = True
            tracker.stop_reason = (
                f"{tracker.consecutive_correct} consecutive correct "
                f"(threshold={self.consecutive_threshold}) after {tracker.total} samples"
            )
            log.info(
                f"early_stopping: category '{category}' stopped — {tracker.stop_reason}"
            )

    def summary(self) -> dict[str, CategoryTracker]:
        """Return all category trackers."""
        return dict(self._trackers)

    def tokens_saved_estimate(self, avg_tokens_per_sample: int = 5000) -> int:
        """Estimate total tokens saved by early stopping.

        Counts the number of samples that were skipped (stopped categories
        that could have had more samples), multiplied by average tokens per sample.
        This is a rough lower-bound: we don't know how many more samples
        would have been scheduled, so we report savings based on the
        consecutive_threshold (samples we *didn't* need beyond the stop point).
        """
        saved = 0
        for tracker in self._trackers.values():
            if tracker.stopped:
                # At minimum, we saved 1 sample per stopped category
                # (the one that would have come next)
                saved += avg_tokens_per_sample
        return saved

    def stats(self) -> dict:
        """Summary statistics."""
        trackers = list(self._trackers.values())
        stopped = [t for t in trackers if t.stopped]
        return {
            "total_categories": len(trackers),
            "stopped_categories": len(stopped),
            "active_categories": len(trackers) - len(stopped),
            "stopped_names": [t.category for t in stopped],
            "total_samples_evaluated": sum(t.total for t in trackers),
            "tokens_saved_estimate": self.tokens_saved_estimate(),
        }
