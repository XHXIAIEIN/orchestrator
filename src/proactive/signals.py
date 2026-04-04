"""Proactive push engine — Signal dataclass + SignalDetector framework."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.proactive import config as cfg

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class Signal:
    """A proactive signal emitted by a detector.

    Fields
    ------
    id          : Unique signal-type identifier, e.g. "S1", "S2".
    tier        : Routing tier — "A" (critical), "B" (important), "C" (informational).
    title       : Short human-readable title for the notification.
    severity    : Severity string — "critical", "high", "medium", "low".
    data        : Arbitrary payload dict with detector-specific details.
    detected_at : Timestamp when the signal was generated (UTC).
    """

    id: str
    tier: str
    title: str
    severity: str
    data: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Detector framework ────────────────────────────────────────────────────────

class SignalDetector:
    """Run all detectors against the EventsDB, aggregate resulting Signals."""

    def __init__(self, db) -> None:
        self.db = db
        self._detectors = [
            self._check_collector_failures,    # S1
            self._check_container_health,      # S2
            self._check_db_size,               # S3
            self._check_governor_failures,     # S4
            self._check_project_silence,       # S5
            self._check_late_night_activity,   # S6
            self._check_repeated_patterns,     # S7  placeholder
            self._check_batch_completion,      # S8  placeholder
            self._check_steal_progress,        # S9
            self._check_defer_overdue,         # S10 placeholder
            self._check_github_activity,       # S11 placeholder
            self._check_dependency_vulns,      # S12 placeholder
        ]

    # ── public API ────────────────────────────────────────────────────────────

    def detect_all(self) -> list[Signal]:
        results: list[Signal] = []
        for detector in self._detectors:
            try:
                outcome = detector()
                if outcome is None:
                    continue
                if isinstance(outcome, list):
                    results.extend(outcome)
                else:
                    results.append(outcome)
            except Exception:
                log.exception("Detector %s raised an uncaught exception", detector.__name__)
        return results

    # ── S1: collector failures ────────────────────────────────────────────────

    def _check_collector_failures(self) -> Optional[Signal]:
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT level FROM logs WHERE source='collector' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()

        streak = 0
        for row in rows:
            if row["level"].upper() == "ERROR":
                streak += 1
            else:
                break

        if streak >= cfg.COLLECTOR_FAIL_STREAK:
            return Signal(
                id="S1",
                tier="A",
                title="采集器连续报错",
                severity="high",
                data={"streak": streak},
            )
        return None

    # ── S2: container health ──────────────────────────────────────────────────

    def _check_container_health(self) -> Optional[Signal]:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        unhealthy: list[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            name, status = parts
            # Only care about orchestrator-related containers
            if "orchestrator" not in name.lower():
                continue
            status_lower = status.lower()
            if "restarting" in status_lower or "exited" in status_lower:
                unhealthy.append(f"{name}: {status}")

        if unhealthy:
            return Signal(
                id="S2",
                tier="A",
                title="容器异常",
                severity="high",
                data={"unhealthy": unhealthy},
            )
        return None

    # ── S3: DB size ───────────────────────────────────────────────────────────

    def _check_db_size(self) -> Optional[Signal]:
        db_path = Path(self.db.db_path)
        if not db_path.exists():
            return None
        size_mb = db_path.stat().st_size / (1024 * 1024)
        if size_mb > cfg.DB_SIZE_WARN_MB:
            return Signal(
                id="S3",
                tier="B",
                title="数据库体积过大",
                severity="medium",
                data={"size_mb": round(size_mb, 2), "threshold_mb": cfg.DB_SIZE_WARN_MB},
            )
        return None

    # ── S4: governor failures ─────────────────────────────────────────────────

    def _check_governor_failures(self) -> Optional[Signal]:
        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT status, action FROM tasks ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

        streak = 0
        last_summary: str = ""
        for row in rows:
            if row["status"] == "failed":
                streak += 1
                if streak == 1:
                    last_summary = row["action"]
            else:
                break

        if streak >= cfg.GOVERNOR_FAIL_STREAK:
            return Signal(
                id="S4",
                tier="A",
                title="Governor 连续任务失败",
                severity="high",
                data={"streak": streak, "last_summary": last_summary},
            )
        return None

    # ── S5: project silence ───────────────────────────────────────────────────

    def _check_project_silence(self) -> Optional[list[Signal]]:
        cutoff_ts = datetime.now(timezone.utc).timestamp() - cfg.PROJECT_SILENCE_DAYS * 86400
        cutoff_str = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()

        with self.db._connect() as conn:
            # All repos seen ever
            all_repos = conn.execute(
                "SELECT DISTINCT json_extract(metadata, '$.repo') AS repo "
                "FROM events WHERE source='codebase' AND repo IS NOT NULL"
            ).fetchall()

            # Repos with recent activity
            active_repos = conn.execute(
                "SELECT DISTINCT json_extract(metadata, '$.repo') AS repo "
                "FROM events WHERE source='codebase' AND occurred_at >= ? AND repo IS NOT NULL",
                (cutoff_str,),
            ).fetchall()

        active_set = {r["repo"] for r in active_repos}
        silent_repos = [r["repo"] for r in all_repos if r["repo"] not in active_set]

        if not silent_repos:
            return None

        return [
            Signal(
                id="S5",
                tier="B",
                title=f"项目沉默：{repo}",
                severity="low",
                data={"repo": repo, "silence_days": cfg.PROJECT_SILENCE_DAYS},
            )
            for repo in silent_repos
        ]

    # ── S6: late-night activity ───────────────────────────────────────────────

    def _check_late_night_activity(self) -> Optional[Signal]:
        cutoff_ts = datetime.now(timezone.utc).timestamp() - 86400
        cutoff_str = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()

        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT occurred_at FROM events "
                "WHERE source='codebase' AND occurred_at >= ?",
                (cutoff_str,),
            ).fetchall()

        late_commits = 0
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
                # Convert to UTC+8
                local_hour = (ts.hour + 8) % 24
                if cfg.LATE_NIGHT_HOUR_START <= local_hour < cfg.LATE_NIGHT_HOUR_END:
                    late_commits += 1
            except (ValueError, AttributeError):
                continue

        if late_commits >= cfg.LATE_NIGHT_MIN_COMMITS:
            return Signal(
                id="S6",
                tier="C",
                title="深夜高频提交",
                severity="low",
                data={
                    "late_commits": late_commits,
                    "window": f"{cfg.LATE_NIGHT_HOUR_START}:00-{cfg.LATE_NIGHT_HOUR_END}:00 CST",
                },
            )
        return None

    # ── S7: repeated patterns (placeholder) ──────────────────────────────────

    def _check_repeated_patterns(self) -> Optional[Signal]:
        return None

    # ── S8: batch completion (placeholder) ───────────────────────────────────

    def _check_batch_completion(self) -> Optional[Signal]:
        return None

    # ── S9: steal progress ────────────────────────────────────────────────────

    def _check_steal_progress(self) -> Optional[Signal]:
        branch_result = subprocess.run(
            ["git", "-C", str(BASE_DIR), "branch", "--list", "steal/*"],
            capture_output=True, text=True, timeout=10,
        )
        if branch_result.returncode != 0:
            return None

        branches = [
            b.strip().lstrip("* ")
            for b in branch_result.stdout.splitlines()
            if b.strip()
        ]
        if not branches:
            return None

        active_branches: list[str] = []
        for branch in branches:
            log_result = subprocess.run(
                [
                    "git", "-C", str(BASE_DIR), "log", branch,
                    "--oneline", "--since=24 hours ago",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if log_result.returncode == 0 and log_result.stdout.strip():
                active_branches.append(branch)

        if active_branches:
            return Signal(
                id="S9",
                tier="C",
                title="偷师分支有新进展",
                severity="low",
                data={"active_branches": active_branches},
            )
        return None

    # ── S10: DEFER overdue (placeholder) ─────────────────────────────────────

    def _check_defer_overdue(self) -> Optional[Signal]:
        return None

    # ── S11: GitHub activity (placeholder) ───────────────────────────────────

    def _check_github_activity(self) -> Optional[Signal]:
        return None

    # ── S12: dependency vulns (placeholder) ──────────────────────────────────

    def _check_dependency_vulns(self) -> Optional[Signal]:
        return None
