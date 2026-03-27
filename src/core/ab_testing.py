"""A/B Testing Framework — compare model/engine performance per task type.

Track which model performs best for which task type.
Supports split mode (random assignment) and mirror mode (both run, compare).
"""

import random
import time
from dataclasses import dataclass, field


@dataclass
class ABResult:
    variant: str  # "A" or "B"
    model: str
    success: bool
    duration_ms: float
    quality_score: float = 0.0  # 0-1, higher is better


@dataclass
class Experiment:
    name: str
    model_a: str
    model_b: str
    task_type: str
    split_ratio: float = 0.5  # fraction that goes to A
    results_a: list[ABResult] = field(default_factory=list)
    results_b: list[ABResult] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def assign(self) -> str:
        """Randomly assign to variant A or B."""
        return "A" if random.random() < self.split_ratio else "B"

    def record(self, result: ABResult):
        if result.variant == "A":
            self.results_a.append(result)
        else:
            self.results_b.append(result)

    def get_stats(self) -> dict:
        def _stats(results):
            if not results:
                return {"n": 0}
            successes = sum(1 for r in results if r.success)
            avg_dur = sum(r.duration_ms for r in results) / len(results)
            avg_qual = sum(r.quality_score for r in results) / len(results) if any(r.quality_score for r in results) else 0
            return {
                "n": len(results),
                "success_rate": round(successes / len(results), 3),
                "avg_duration_ms": round(avg_dur, 1),
                "avg_quality": round(avg_qual, 3),
            }
        return {
            "name": self.name,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "a": _stats(self.results_a),
            "b": _stats(self.results_b),
            "winner": self._winner(),
        }

    def _winner(self) -> str | None:
        """Determine winner based on success rate, then quality, then speed."""
        sa = self.get_stats()["a"]
        sb = self.get_stats()["b"]
        if sa["n"] < 5 or sb["n"] < 5:
            return None  # Not enough data
        if sa["success_rate"] != sb["success_rate"]:
            return "A" if sa["success_rate"] > sb["success_rate"] else "B"
        if sa["avg_quality"] != sb["avg_quality"]:
            return "A" if sa["avg_quality"] > sb["avg_quality"] else "B"
        return "A" if sa["avg_duration_ms"] < sb["avg_duration_ms"] else "B"


class ABTestManager:
    """Manage multiple A/B experiments."""

    def __init__(self):
        self._experiments: dict[str, Experiment] = {}

    def create(self, name: str, model_a: str, model_b: str, task_type: str, split: float = 0.5) -> Experiment:
        exp = Experiment(name=name, model_a=model_a, model_b=model_b, task_type=task_type, split_ratio=split)
        self._experiments[name] = exp
        return exp

    def get(self, name: str) -> Experiment | None:
        return self._experiments.get(name)

    def get_for_task(self, task_type: str) -> Experiment | None:
        """Find active experiment for a task type."""
        for exp in self._experiments.values():
            if exp.task_type == task_type:
                return exp
        return None

    def all_stats(self) -> list[dict]:
        return [exp.get_stats() for exp in self._experiments.values()]
