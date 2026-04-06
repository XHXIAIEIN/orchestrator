"""
Production Sampler — success capture + department health tracking.

Two jobs:
  1. Sample successful tasks for eval corpus (currently only failures captured)
  2. Aggregate department health for degradation detection

Runs inside Governor's post-task evaluation via EvalHarness.

Health persistence: data/department_health/<dept>.jsonl (append-only).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

HEALTH_DIR = Path(__file__).parent.parent.parent.parent / "data" / "department_health"

# Alert thresholds
ALERT_DELTA = -0.5       # rolling_mean < baseline - 0.5 → alert
CRITICAL_DELTA = -1.0    # rolling_mean < baseline - 1.0 → critical


@dataclass
class DepartmentHealth:
    """Health snapshot for one department."""
    department: str
    rolling_mean: float        # last N task scores
    baseline: float            # established baseline
    delta: float               # rolling_mean - baseline
    sample_count: int
    alert: bool                # True if delta < ALERT_DELTA
    critical: bool = False     # True if delta < CRITICAL_DELTA
    weak_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "rolling_mean": round(self.rolling_mean, 3),
            "baseline": round(self.baseline, 3),
            "delta": round(self.delta, 3),
            "sample_count": self.sample_count,
            "alert": self.alert,
            "critical": self.critical,
            "weak_criteria": self.weak_criteria,
        }


@dataclass
class _ScoreRecord:
    """Internal: one recorded score with optional criteria breakdown."""
    score: float
    criteria: dict  # criterion_name → score
    timestamp: str


class ProductionSampler:
    """Production sampling and department health tracking."""

    def __init__(
        self,
        sample_rate: float = 0.05,
        window: int = 20,
        health_dir: Path | None = None,
    ):
        self.sample_rate = sample_rate    # 5% of successful tasks
        self.window = window              # rolling window size
        self._health_dir = health_dir or HEALTH_DIR
        self._scores: dict[str, list[_ScoreRecord]] = defaultdict(list)
        self._baselines: dict[str, float] = {}
        self._consecutive_alerts: dict[str, int] = defaultdict(int)
        self._loaded: set[str] = set()

    def should_sample(self, task_id: int) -> bool:
        """Deterministic sampling based on task_id hash."""
        return (hash(task_id) % 100) < (self.sample_rate * 100)

    def record_score(
        self,
        department: str,
        score: float,
        criteria_scores: dict | None = None,
    ):
        """Record a task score for department health tracking."""
        self._ensure_loaded(department)
        record = _ScoreRecord(
            score=score,
            criteria=criteria_scores or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._scores[department].append(record)

        # Persist to disk
        self._persist_score(department, record)

        # Trim to 2x window (keep some history but don't grow unbounded)
        max_keep = self.window * 2
        if len(self._scores[department]) > max_keep:
            self._scores[department] = self._scores[department][-max_keep:]

    def set_baseline(self, department: str, score: float):
        """Set or update the baseline for a department."""
        self._baselines[department] = score
        # Persist baseline
        baseline_file = self._health_dir / f"{department}_baseline.json"
        self._health_dir.mkdir(parents=True, exist_ok=True)
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump({"baseline": score, "set_at": datetime.now(timezone.utc).isoformat()}, f)

    def get_health(self, department: str) -> DepartmentHealth:
        """Get current health status for a department."""
        self._ensure_loaded(department)
        records = self._scores.get(department, [])
        recent = records[-self.window:] if records else []

        if not recent:
            return DepartmentHealth(
                department=department,
                rolling_mean=0.0,
                baseline=self._baselines.get(department, 0.0),
                delta=0.0,
                sample_count=0,
                alert=False,
            )

        rolling_mean = sum(r.score for r in recent) / len(recent)
        baseline = self._baselines.get(department, rolling_mean)

        # Auto-set baseline from first window of data if not explicitly set
        if department not in self._baselines and len(records) >= self.window:
            baseline = sum(r.score for r in records[:self.window]) / self.window
            self._baselines[department] = baseline

        delta = rolling_mean - baseline

        # Weak criteria: find criteria consistently scoring low
        weak_criteria = self._find_weak_criteria(recent)

        alert = delta < ALERT_DELTA
        critical = delta < CRITICAL_DELTA

        # Track consecutive alerts
        if alert:
            self._consecutive_alerts[department] += 1
        else:
            self._consecutive_alerts[department] = 0

        return DepartmentHealth(
            department=department,
            rolling_mean=rolling_mean,
            baseline=baseline,
            delta=delta,
            sample_count=len(recent),
            alert=alert,
            critical=critical,
            weak_criteria=weak_criteria,
        )

    def get_all_health(self) -> dict[str, DepartmentHealth]:
        """Health status across all tracked departments."""
        return {dept: self.get_health(dept) for dept in self._scores}

    def consecutive_alerts(self, department: str) -> int:
        """Number of consecutive health alerts for a department."""
        return self._consecutive_alerts.get(department, 0)

    # ── Internal ─────────────────────────────────────────────

    def _find_weak_criteria(self, records: list[_ScoreRecord]) -> list[str]:
        """Find criteria consistently scoring below 0.5 in recent records."""
        if not records:
            return []

        criteria_scores: dict[str, list[float]] = defaultdict(list)
        for r in records:
            for name, score in r.criteria.items():
                if isinstance(score, (int, float)):
                    criteria_scores[name].append(score)

        weak = []
        for name, scores in criteria_scores.items():
            if scores and (sum(scores) / len(scores)) < 0.5:
                weak.append(name)

        return sorted(weak)

    def _ensure_loaded(self, department: str):
        """Lazy-load persisted scores and baseline for a department."""
        if department in self._loaded:
            return
        self._loaded.add(department)

        self._health_dir.mkdir(parents=True, exist_ok=True)

        # Load baseline
        baseline_file = self._health_dir / f"{department}_baseline.json"
        if baseline_file.exists():
            try:
                with open(baseline_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._baselines[department] = data.get("baseline", 0.0)
            except Exception as e:
                log.debug(f"sampler: failed to load baseline for {department}: {e}")

        # Load recent scores
        scores_file = self._health_dir / f"{department}.jsonl"
        if scores_file.exists():
            try:
                records = []
                with open(scores_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        d = json.loads(line)
                        records.append(_ScoreRecord(
                            score=d.get("score", 0.0),
                            criteria=d.get("criteria", {}),
                            timestamp=d.get("timestamp", ""),
                        ))
                # Keep only last 2x window
                max_keep = self.window * 2
                self._scores[department] = records[-max_keep:]
            except Exception as e:
                log.debug(f"sampler: failed to load scores for {department}: {e}")

    def _persist_score(self, department: str, record: _ScoreRecord):
        """Append score record to disk."""
        self._health_dir.mkdir(parents=True, exist_ok=True)
        scores_file = self._health_dir / f"{department}.jsonl"
        try:
            with open(scores_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "score": record.score,
                    "criteria": record.criteria,
                    "timestamp": record.timestamp,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            log.debug(f"sampler: failed to persist score for {department}: {e}")
