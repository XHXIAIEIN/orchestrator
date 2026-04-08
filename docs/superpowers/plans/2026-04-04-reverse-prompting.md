# Reverse Prompting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TG bot proactive — detect system events, user behavior patterns, and project status, then push messages through existing Telegram chat without user prompting.

**Architecture:** New `src/proactive/` module with 3 components: SignalDetector (scans data sources), ThrottleGate (rate-limits/silences), MessageGenerator (templates or LLM). Scheduler calls `ProactiveEngine.scan_cycle()` every 5 minutes. Outputs go through existing `ChannelRegistry.broadcast()`.

**Tech Stack:** Python 3.11, SQLite (EventsDB mixin), APScheduler, Claude Haiku (via llm_router), existing ChannelRegistry/TG bot.

**Spec:** `docs/superpowers/specs/2026-04-04-reverse-prompting-design.md`

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/proactive/__init__.py` | Package init, public API |
| `src/proactive/config.py` | All configurable constants (thresholds, cooldowns, time windows) |
| `src/proactive/signals.py` | Signal dataclass + SignalDetector with 12 detector methods |
| `src/proactive/throttle.py` | ThrottleGate — 4-layer filter (time window, rate cap, cooldown, quiet mode) |
| `src/proactive/messages.py` | MessageGenerator — template for Tier A/D, LLM for Tier B/C |
| `src/proactive/engine.py` | ProactiveEngine — scan_cycle orchestrator |
| `src/storage/_proactive_mixin.py` | DB mixin for proactive_log table CRUD |
| `tests/proactive/test_signals.py` | Signal detector unit tests |
| `tests/proactive/test_throttle.py` | ThrottleGate unit tests |
| `tests/proactive/test_messages.py` | MessageGenerator unit tests |
| `tests/proactive/test_engine.py` | ProactiveEngine integration tests |
| `tests/proactive/__init__.py` | Test package init |

### Modified files
| File | Change |
|------|--------|
| `src/storage/_schema.py` | Add `proactive_log` table DDL + index |
| `src/storage/events_db.py` | Add `ProactiveMixin` to class inheritance |
| `src/scheduler.py` | Add proactive scan job (5min interval) |
| `src/channels/chat/commands.py` | Add `/quiet`, `/loud`, `/proactive` commands |

---

## Task 1: Proactive Config Module

**Files:**
- Create: `src/proactive/__init__.py`
- Create: `src/proactive/config.py`

- [ ] **Step 1: Create package init**

```python
# src/proactive/__init__.py
"""Proactive push engine — makes the TG bot speak first."""
```

- [ ] **Step 2: Create config module with all constants**

```python
# src/proactive/config.py
"""Proactive engine configuration — all tunable knobs in one place."""
import os

def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))

# ── Scan cycle ──
SCAN_INTERVAL_MINUTES = _int("PROACTIVE_SCAN_INTERVAL", 5)

# ── Time window (hour range, 24h format) ──
ACTIVE_HOUR_START = _int("PROACTIVE_HOUR_START", 10)
ACTIVE_HOUR_END = _int("PROACTIVE_HOUR_END", 23)

# ── Rate cap ──
MAX_PER_HOUR = _int("PROACTIVE_MAX_PER_HOUR", 5)

# ── Per-signal cooldown (seconds) ──
COOLDOWNS: dict[str, int] = {
    "S1": 21600,    # 6h  — collector failures
    "S2": 3600,     # 1h  — container health
    "S3": 86400,    # 24h — DB size
    "S4": 10800,    # 3h  — governor failures
    "S5": 604800,   # 7d  — project silence
    "S6": 86400,    # 24h — late night activity
    "S7": 604800,   # 7d  — repeated patterns
    "S8": 0,        # per batch — batch completion
    "S9": 0,        # per round — steal progress
    "S10": 1209600, # 14d — DEFER overdue
    "S11": 3600,    # 1h  — GitHub activity
    "S12": 86400,   # 24h — dependency vulns
}

# ── Signal thresholds ──
COLLECTOR_FAIL_STREAK = _int("PROACTIVE_COLLECTOR_FAIL_STREAK", 3)
GOVERNOR_FAIL_STREAK = _int("PROACTIVE_GOVERNOR_FAIL_STREAK", 3)
DB_SIZE_WARN_MB = _int("PROACTIVE_DB_SIZE_WARN_MB", 50)
DB_GROWTH_WARN_MB = _int("PROACTIVE_DB_GROWTH_WARN_MB", 5)
PROJECT_SILENCE_DAYS = _int("PROACTIVE_PROJECT_SILENCE_DAYS", 5)
LATE_NIGHT_HOUR_START = _int("PROACTIVE_LATE_NIGHT_START", 1)
LATE_NIGHT_HOUR_END = _int("PROACTIVE_LATE_NIGHT_END", 5)
LATE_NIGHT_MIN_COMMITS = _int("PROACTIVE_LATE_NIGHT_MIN_COMMITS", 2)
REPEAT_PATTERN_THRESHOLD = _int("PROACTIVE_REPEAT_THRESHOLD", 3)

# ── LLM generation cap per scan ──
MAX_LLM_PER_SCAN = _int("PROACTIVE_MAX_LLM_PER_SCAN", 2)
```

- [ ] **Step 3: Verify module imports**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -c "from src.proactive.config import COOLDOWNS; print(len(COOLDOWNS))"`
Expected: `12`

- [ ] **Step 4: Commit**

```bash
git add src/proactive/__init__.py src/proactive/config.py
git commit -m "feat(proactive): config module — all tunable knobs for signal detection and throttling"
```

---

## Task 2: Signal Dataclass + Detector Framework

**Files:**
- Create: `src/proactive/signals.py`
- Create: `tests/proactive/__init__.py`
- Create: `tests/proactive/test_signals.py`

- [ ] **Step 1: Write failing test for Signal dataclass and detect_all framework**

```python
# tests/proactive/__init__.py
# (empty)
```

```python
# tests/proactive/test_signals.py
"""Tests for proactive signal detection."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from src.proactive.signals import Signal, SignalDetector


class TestSignalDataclass:
    def test_signal_fields(self):
        s = Signal(
            id="S1", tier="A", title="Test signal",
            severity="warning", data={"key": "val"},
        )
        assert s.id == "S1"
        assert s.tier == "A"
        assert s.severity == "warning"
        assert isinstance(s.detected_at, datetime)

    def test_signal_default_detected_at(self):
        s = Signal(id="S1", tier="A", title="t", severity="info", data={})
        assert (datetime.now(timezone.utc) - s.detected_at).total_seconds() < 2


class TestSignalDetector:
    def test_detect_all_returns_list(self):
        db = MagicMock()
        detector = SignalDetector(db)
        result = detector.detect_all()
        assert isinstance(result, list)

    def test_detect_all_catches_detector_errors(self):
        """Individual detector failures don't crash detect_all."""
        db = MagicMock()
        detector = SignalDetector(db)
        # Monkey-patch one detector to raise
        def _boom():
            raise RuntimeError("boom")
        original = detector._detectors[0]
        detector._detectors[0] = _boom
        result = detector.detect_all()
        assert isinstance(result, list)  # Should not raise
        detector._detectors[0] = original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_signals.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.proactive.signals'`

- [ ] **Step 3: Write Signal dataclass and SignalDetector framework**

```python
# src/proactive/signals.py
"""Signal detection — scans data sources for proactive push triggers."""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.proactive import config as cfg

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass
class Signal:
    """A detected event worth potentially pushing to the user."""
    id: str              # "S1" ~ "S12"
    tier: str            # "A" | "B" | "C" | "D"
    title: str           # Human-readable title
    severity: str        # "critical" | "warning" | "info"
    data: dict           # Context data carried by the signal
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SignalDetector:
    """Scans all data sources and returns currently active signals."""

    def __init__(self, db):
        self.db = db
        self._detectors = [
            self._check_collector_failures,    # S1
            self._check_container_health,      # S2
            self._check_db_size,               # S3
            self._check_governor_failures,     # S4
            self._check_project_silence,       # S5
            self._check_late_night_activity,   # S6
            self._check_repeated_patterns,     # S7
            self._check_batch_completion,      # S8
            self._check_steal_progress,        # S9
            self._check_defer_overdue,         # S10
            self._check_github_activity,       # S11
            self._check_dependency_vulns,      # S12
        ]

    def detect_all(self) -> list[Signal]:
        """Run all detectors, return list of active signals."""
        signals: list[Signal] = []
        for fn in self._detectors:
            try:
                result = fn()
                if result:
                    if isinstance(result, list):
                        signals.extend(result)
                    else:
                        signals.append(result)
            except Exception as e:
                log.warning(f"proactive: detector {fn.__name__} failed: {e}")
        return signals

    # ── Tier A: System alerts ──

    def _check_collector_failures(self) -> Optional[Signal]:
        """S1: Collector consecutive failures (from logs table, source='collector')."""
        try:
            with self.db._connect() as conn:
                # Recent collector log entries (INFO = success, ERROR = failure)
                rows = conn.execute(
                    "SELECT level, message FROM logs "
                    "WHERE source = 'collector' "
                    "ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
        except Exception:
            return None

        if not rows:
            return None

        # Count consecutive ERRORs from most recent
        streak = 0
        last_error = ""
        for row in rows:
            if row["level"] == "ERROR":
                streak += 1
                if streak == 1:
                    last_error = (row["message"] or "unknown")[:200]
            else:
                break

        if streak >= cfg.COLLECTOR_FAIL_STREAK:
            return Signal(
                id="S1", tier="A", title="采集器连��失败",
                severity="warning",
                data={"collector": "collector", "count": streak, "error": last_error},
            )
        return None

    def _check_container_health(self) -> Optional[Signal]:
        """S2: Docker container not running or restarting."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            name, status = parts
            if "orchestrator" in name.lower():
                if "restarting" in status.lower() or "exited" in status.lower():
                    return Signal(
                        id="S2", tier="A", title="容器异常",
                        severity="critical",
                        data={"name": name, "status": status},
                    )
        return None

    def _check_db_size(self) -> Optional[Signal]:
        """S3: DB file size warning."""
        db_path = Path(self.db.db_path)
        if not db_path.exists():
            return None
        size_mb = db_path.stat().st_size / (1024 * 1024)

        # Check growth: compare with 24h ago log entry
        delta_mb = 0.0
        try:
            with self.db._connect() as conn:
                row = conn.execute(
                    "SELECT message FROM logs WHERE source = 'health' "
                    "AND message LIKE '%DB%MB%' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if row:
                    import re
                    m = re.search(r'([\d.]+)MB', row["message"] or "")
                    if m:
                        old_mb = float(m.group(1))
                        delta_mb = size_mb - old_mb
        except Exception:
            pass

        if size_mb > cfg.DB_SIZE_WARN_MB or delta_mb > cfg.DB_GROWTH_WARN_MB:
            return Signal(
                id="S3", tier="A", title="DB 膨胀",
                severity="warning" if size_mb <= 100 else "critical",
                data={"size_mb": round(size_mb, 1), "delta_mb": round(delta_mb, 1)},
            )
        return None

    def _check_governor_failures(self) -> Optional[Signal]:
        """S4: Governor consecutive task failures."""
        try:
            with self.db._connect() as conn:
                rows = conn.execute(
                    "SELECT status, action FROM tasks "
                    "ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
        except Exception:
            return None

        streak = 0
        last_summary = ""
        for row in rows:
            if row["status"] == "failed":
                streak += 1
                if streak == 1:
                    last_summary = (row["action"] or "")[:80]
            else:
                break

        if streak >= cfg.GOVERNOR_FAIL_STREAK:
            return Signal(
                id="S4", tier="A", title="Governor 连续失败",
                severity="warning",
                data={"count": streak, "last_summary": last_summary},
            )
        return None

    # ── Tier B: User behavior ──

    def _check_project_silence(self) -> Optional[list[Signal]]:
        """S5: Projects with no recent commits."""
        signals = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.PROJECT_SILENCE_DAYS)
        try:
            with self.db._connect() as conn:
                # Get projects from codebase collector events
                rows = conn.execute(
                    "SELECT DISTINCT json_extract(metadata, '$.repo') as repo "
                    "FROM events WHERE source = 'codebase' AND occurred_at > ? "
                    "GROUP BY repo",
                    ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),),
                ).fetchall()

                for row in rows:
                    repo = row["repo"]
                    if not repo:
                        continue
                    latest = conn.execute(
                        "SELECT occurred_at, title FROM events "
                        "WHERE source = 'codebase' AND json_extract(metadata, '$.repo') = ? "
                        "ORDER BY occurred_at DESC LIMIT 1",
                        (repo,),
                    ).fetchone()
                    if latest:
                        last_at = datetime.fromisoformat(latest["occurred_at"])
                        if last_at.tzinfo is None:
                            last_at = last_at.replace(tzinfo=timezone.utc)
                        if last_at < cutoff:
                            days_ago = (datetime.now(timezone.utc) - last_at).days
                            signals.append(Signal(
                                id="S5", tier="B", title="项目沉寂",
                                severity="info",
                                data={
                                    "repo": repo,
                                    "days_silent": days_ago,
                                    "last_commit": (latest["title"] or "")[:80],
                                },
                            ))
        except Exception as e:
            log.warning(f"proactive: S5 project silence check failed: {e}")
        return signals or None

    def _check_late_night_activity(self) -> Optional[Signal]:
        """S6: Late-night commit activity."""
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            with self.db._connect() as conn:
                rows = conn.execute(
                    "SELECT occurred_at, title, json_extract(metadata, '$.repo') as repo "
                    "FROM events WHERE source = 'codebase' AND occurred_at > ?",
                    (cutoff,),
                ).fetchall()
        except Exception:
            return None

        late_commits = []
        for row in rows:
            try:
                dt = datetime.fromisoformat(row["occurred_at"])
                # Convert to local time (CST = UTC+8)
                local_hour = (dt.hour + 8) % 24
                if cfg.LATE_NIGHT_HOUR_START <= local_hour < cfg.LATE_NIGHT_HOUR_END:
                    late_commits.append({
                        "title": (row["title"] or "")[:60],
                        "repo": row["repo"] or "unknown",
                        "hour": local_hour,
                    })
            except Exception:
                continue

        if len(late_commits) >= cfg.LATE_NIGHT_MIN_COMMITS:
            repos = list({c["repo"] for c in late_commits})
            return Signal(
                id="S6", tier="B", title="深夜活跃",
                severity="info",
                data={
                    "commit_count": len(late_commits),
                    "repos": repos,
                    "commits": late_commits[:5],
                },
            )
        return None

    def _check_repeated_patterns(self) -> Optional[Signal]:
        """S7: Repeated similar requests in chat."""
        # Placeholder — requires chat_messages analysis, implemented in Phase 1b
        return None

    # ── Tier C: Project progress ──

    def _check_batch_completion(self) -> Optional[Signal]:
        """S8: Batch of cron tasks completed."""
        # Placeholder — requires agent_cron integration, implemented in Phase 1b
        return None

    def _check_steal_progress(self) -> Optional[Signal]:
        """S9: New commits on steal/* branches."""
        try:
            result = subprocess.run(
                ["git", "-C", str(BASE_DIR), "branch", "--list", "steal/*"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        for branch in result.stdout.strip().split("\n"):
            branch = branch.strip().lstrip("* ")
            if not branch:
                continue
            try:
                log_result = subprocess.run(
                    ["git", "-C", str(BASE_DIR), "log", branch,
                     "--oneline", "--since=24 hours ago"],
                    capture_output=True, text=True, timeout=10,
                )
                commits = [l for l in log_result.stdout.strip().split("\n") if l.strip()]
                if commits:
                    return Signal(
                        id="S9", tier="C", title="偷师进展",
                        severity="info",
                        data={
                            "branch": branch,
                            "commit_count": len(commits),
                            "commits": [c[:72] for c in commits[:5]],
                        },
                    )
            except Exception:
                continue
        return None

    def _check_defer_overdue(self) -> Optional[Signal]:
        """S10: DEFER items with no recent activity."""
        # Placeholder — requires ROADMAP.md parsing, implemented in Phase 1b
        return None

    # ── Tier D: External signals ──

    def _check_github_activity(self) -> Optional[Signal]:
        """S11: GitHub repo events (stars, issues, PRs)."""
        # Placeholder — requires GitHub API integration, implemented in Phase 1c
        return None

    def _check_dependency_vulns(self) -> Optional[Signal]:
        """S12: Dependency security vulnerabilities."""
        # Placeholder — requires pip audit integration, implemented in Phase 1c
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_signals.py -v 2>&1 | tail -15`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/signals.py tests/proactive/__init__.py tests/proactive/test_signals.py
git commit -m "feat(proactive): Signal dataclass + SignalDetector with S1-S6/S9 detectors"
```

---

## Task 3: ThrottleGate

**Files:**
- Create: `src/proactive/throttle.py`
- Create: `tests/proactive/test_throttle.py`

- [ ] **Step 1: Write failing tests for ThrottleGate**

```python
# tests/proactive/test_throttle.py
"""Tests for proactive throttle gate."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from src.proactive.signals import Signal
from src.proactive.throttle import ThrottleGate


def _make_signal(id="S1", tier="A", severity="warning"):
    return Signal(id=id, tier=tier, title="test", severity=severity, data={})


class TestThrottleGate:
    def test_allows_first_signal(self):
        gate = ThrottleGate()
        assert gate.should_send(_make_signal()) is True

    def test_critical_tier_a_always_passes(self):
        """Critical Tier A signals bypass all limits."""
        gate = ThrottleGate()
        gate._quiet_mode = True  # Even in quiet mode
        s = _make_signal(tier="A", severity="critical")
        assert gate.should_send(s) is True

    def test_quiet_mode_blocks(self):
        gate = ThrottleGate()
        gate._quiet_mode = True
        s = _make_signal(tier="B", severity="info")
        assert gate.should_send(s) is False

    def test_outside_active_hours_queues(self):
        gate = ThrottleGate()
        with patch("src.proactive.throttle._now_local_hour", return_value=3):
            s = _make_signal(tier="B", severity="info")
            assert gate.should_send(s) is False
            assert len(gate._queued) == 1

    def test_rate_limit(self):
        gate = ThrottleGate()
        # Send MAX_PER_HOUR signals
        from src.proactive.config import MAX_PER_HOUR
        for i in range(MAX_PER_HOUR):
            s = _make_signal(id=f"S{i+1}", tier="B", severity="info")
            gate.record_sent(s)
        # Next one should be blocked
        s = _make_signal(id="S99", tier="B", severity="info")
        assert gate.should_send(s) is False

    def test_cooldown_blocks_duplicate(self):
        gate = ThrottleGate()
        s = _make_signal(id="S1")
        gate.record_sent(s)
        # Same signal again should be in cooldown
        assert gate.should_send(_make_signal(id="S1")) is False

    def test_toggle_quiet(self):
        gate = ThrottleGate()
        gate.set_quiet(True)
        assert gate._quiet_mode is True
        gate.set_quiet(False)
        assert gate._quiet_mode is False

    def test_drain_queued(self):
        gate = ThrottleGate()
        s = _make_signal(tier="B", severity="info")
        gate._queued.append(s)
        drained = gate.drain_queued()
        assert len(drained) == 1
        assert len(gate._queued) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_throttle.py -v 2>&1 | head -15`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write ThrottleGate implementation**

```python
# src/proactive/throttle.py
"""Throttle gate — 4-layer filter before pushing a proactive message."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.proactive import config as cfg
from src.proactive.signals import Signal

log = logging.getLogger(__name__)


def _now_local_hour() -> int:
    """Current hour in CST (UTC+8). Patchable for testing."""
    return (datetime.now(timezone.utc).hour + 8) % 24


class ThrottleGate:
    """4-layer filter: time window → rate cap → cooldown → quiet mode.

    Critical Tier-A signals bypass everything.
    """

    def __init__(self):
        self._quiet_mode: bool = False
        self._enabled: bool = True
        self._sent_log: list[tuple[str, datetime]] = []  # (signal_id, sent_at)
        self._queued: list[Signal] = []

    def should_send(self, signal: Signal) -> bool:
        """Decide whether this signal should be pushed now."""
        # Layer 0: hard off switch
        if not self._enabled:
            return False

        # Layer 0.5: critical Tier-A bypasses everything
        if signal.tier == "A" and signal.severity == "critical":
            return True

        # Layer 1: quiet mode
        if self._quiet_mode:
            return False

        # Layer 2: time window
        hour = _now_local_hour()
        if not (cfg.ACTIVE_HOUR_START <= hour < cfg.ACTIVE_HOUR_END):
            self._queued.append(signal)
            return False

        # Layer 3: rate cap
        now = datetime.now(timezone.utc)
        recent = sum(
            1 for _, t in self._sent_log
            if (now - t).total_seconds() < 3600
        )
        if recent >= cfg.MAX_PER_HOUR:
            self._queued.append(signal)
            return False

        # Layer 4: cooldown
        cooldown_sec = cfg.COOLDOWNS.get(signal.id, 3600)
        if cooldown_sec > 0:
            for sid, t in reversed(self._sent_log):
                if sid == signal.id:
                    if (now - t).total_seconds() < cooldown_sec:
                        return False
                    break  # Only check most recent send of this signal

        return True

    def record_sent(self, signal: Signal):
        """Record that a signal was sent (for rate/cooldown tracking)."""
        self._sent_log.append((signal.id, datetime.now(timezone.utc)))
        # Prune old entries (>48h)
        cutoff = datetime.now(timezone.utc)
        self._sent_log = [
            (sid, t) for sid, t in self._sent_log
            if (cutoff - t).total_seconds() < 172800
        ]

    def set_quiet(self, quiet: bool):
        """Toggle quiet mode (from /quiet and /loud commands)."""
        self._quiet_mode = quiet
        log.info(f"proactive: quiet mode {'ON' if quiet else 'OFF'}")

    def set_enabled(self, enabled: bool):
        """Toggle engine entirely (from /proactive on|off)."""
        self._enabled = enabled
        log.info(f"proactive: engine {'ON' if enabled else 'OFF'}")

    def drain_queued(self) -> list[Signal]:
        """Return and clear queued signals (for daily report absorption)."""
        queued = list(self._queued)
        self._queued.clear()
        return queued

    @property
    def is_quiet(self) -> bool:
        return self._quiet_mode

    @property
    def is_enabled(self) -> bool:
        return self._enabled
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_throttle.py -v 2>&1 | tail -15`
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/throttle.py tests/proactive/test_throttle.py
git commit -m "feat(proactive): ThrottleGate — 4-layer filter with quiet mode and queue"
```

---

## Task 4: MessageGenerator

**Files:**
- Create: `src/proactive/messages.py`
- Create: `tests/proactive/test_messages.py`

- [ ] **Step 1: Write failing tests for MessageGenerator**

```python
# tests/proactive/test_messages.py
"""Tests for proactive message generation."""
import pytest
from unittest.mock import MagicMock

from src.proactive.signals import Signal
from src.proactive.messages import MessageGenerator


def _make_signal(id="S1", tier="A", severity="warning", data=None):
    return Signal(
        id=id, tier=tier, title="Test",
        severity=severity, data=data or {},
    )


class TestMessageGenerator:
    def test_tier_a_uses_template(self):
        gen = MessageGenerator(llm_router=None)
        s = _make_signal(
            id="S1", tier="A",
            data={"collector": "github", "count": 3, "error": "timeout"},
        )
        msg = gen.generate(s)
        assert "github" in msg
        assert "3" in msg
        assert "timeout" in msg

    def test_tier_d_uses_template(self):
        gen = MessageGenerator(llm_router=None)
        s = _make_signal(
            id="S11", tier="D",
            data={"repo": "my-repo", "event_type": "star", "title": "New star"},
        )
        msg = gen.generate(s)
        assert "my-repo" in msg

    def test_tier_b_calls_llm(self):
        router = MagicMock()
        router.generate.return_value = "LLM generated message"
        gen = MessageGenerator(llm_router=router)
        s = _make_signal(id="S5", tier="B", data={"repo": "test", "days_silent": 7})
        msg = gen.generate(s)
        assert msg == "LLM generated message"
        router.generate.assert_called_once()

    def test_tier_b_fallback_on_llm_failure(self):
        router = MagicMock()
        router.generate.side_effect = Exception("API error")
        gen = MessageGenerator(llm_router=router)
        s = _make_signal(
            id="S5", tier="B", title="项目沉寂",
            data={"repo": "test", "days_silent": 7, "last_commit": "fix bug"},
        )
        msg = gen.generate(s)
        # Should fallback to plain data dump, not raise
        assert "项目沉寂" in msg
        assert "test" in msg

    def test_all_tier_a_templates_have_required_keys(self):
        gen = MessageGenerator(llm_router=None)
        # S1
        msg = gen.generate(_make_signal(id="S1", tier="A", data={
            "collector": "x", "count": 1, "error": "e",
        }))
        assert msg  # Non-empty
        # S2
        msg = gen.generate(_make_signal(id="S2", tier="A", data={
            "name": "c", "status": "exited",
        }))
        assert msg
        # S3
        msg = gen.generate(_make_signal(id="S3", tier="A", data={
            "size_mb": 55, "delta_mb": 3,
        }))
        assert msg
        # S4
        msg = gen.generate(_make_signal(id="S4", tier="A", data={
            "count": 3, "last_summary": "s",
        }))
        assert msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_messages.py -v 2>&1 | head -15`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write MessageGenerator implementation**

```python
# src/proactive/messages.py
"""Message generation — templates for Tier A/D, LLM for Tier B/C."""
from __future__ import annotations

import json
import logging
from typing import Optional

from src.proactive.signals import Signal

log = logging.getLogger(__name__)

# ── Tier A/D templates (zero-cost, zero-latency) ──
TEMPLATES: dict[str, str] = {
    "S1":  "⚠️ **{collector}** 连续失败 {count} 次\n最后错误：`{error}`",
    "S2":  "🔴 容器 **{name}** 状态异常：{status}",
    "S3":  "📦 events.db 已达 **{size_mb}MB**（日增 {delta_mb}MB）",
    "S4":  "❌ Governor 连续 **{count}** 个任务失败\n最近：{last_summary}",
    "S11": "⭐ **{repo}** — {event_type}: {title}",
    "S12": "🛡️ **{package}** 发现 {severity} 漏洞：{cve_id}",
}

_LLM_SYSTEM = (
    "你是 Orchestrator，用户的 AI 管家和损友。"
    "根据以下观察生成一条简短的主动推送消息。"
    "要求：1) 说人话，带点损友味 2) 包含具体数据 "
    "3) 如果有建议就给，没有就不硬凑 4) 一条消息，不超过 200 字"
)


class MessageGenerator:
    """Generate push message from a Signal. Template for A/D, LLM for B/C."""

    def __init__(self, llm_router):
        self._router = llm_router

    def generate(self, signal: Signal) -> str:
        if signal.tier in ("A", "D"):
            return self._from_template(signal)
        else:
            return self._from_llm(signal)

    def _from_template(self, signal: Signal) -> str:
        tpl = TEMPLATES.get(signal.id)
        if not tpl:
            return f"📣 {signal.title}: {json.dumps(signal.data, ensure_ascii=False)}"
        try:
            return tpl.format(**signal.data)
        except KeyError as e:
            log.warning(f"proactive: template key missing for {signal.id}: {e}")
            return f"📣 {signal.title}: {json.dumps(signal.data, ensure_ascii=False)}"

    def _from_llm(self, signal: Signal) -> str:
        """Tier B/C: rule-triggered + LLM-generated. Falls back to plain text."""
        if not self._router:
            return self._fallback(signal)

        prompt = (
            f"{_LLM_SYSTEM}\n\n"
            f"信号类型：{signal.title}\n"
            f"数据：{json.dumps(signal.data, ensure_ascii=False)}\n"
            f"生成一条推送消息。"
        )
        try:
            return self._router.generate(
                prompt=prompt,
                task_type="chat",
                max_tokens=256,
                temperature=0.6,
            )
        except Exception as e:
            log.warning(f"proactive: LLM generation failed for {signal.id}: {e}")
            return self._fallback(signal)

    def _fallback(self, signal: Signal) -> str:
        """Plain-text fallback when LLM is unavailable."""
        data_str = ", ".join(f"{k}={v}" for k, v in signal.data.items())
        return f"📣 **{signal.title}**: {data_str}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_messages.py -v 2>&1 | tail -15`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/messages.py tests/proactive/test_messages.py
git commit -m "feat(proactive): MessageGenerator — template + LLM with fallback"
```

---

## Task 5: Proactive DB Mixin + Schema

**Files:**
- Create: `src/storage/_proactive_mixin.py`
- Modify: `src/storage/_schema.py`
- Modify: `src/storage/events_db.py`

- [ ] **Step 1: Write failing test for ProactiveMixin**

```python
# tests/proactive/test_db.py
"""Tests for proactive DB mixin."""
import pytest
import sqlite3
import tempfile
import os

from src.storage.events_db import EventsDB


class TestProactiveMixin:
    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test_events.db")
        return EventsDB(db_path)

    def test_log_proactive_sent(self, db):
        row_id = db.log_proactive(
            signal_id="S1", tier="A", severity="warning",
            data={"collector": "github"}, message="test msg", action="sent",
        )
        assert row_id > 0

    def test_log_proactive_throttled(self, db):
        row_id = db.log_proactive(
            signal_id="S2", tier="A", severity="critical",
            data={}, message=None, action="throttled", reason="cooldown",
        )
        assert row_id > 0

    def test_recent_proactive_logs(self, db):
        db.log_proactive("S1", "A", "warning", {}, "msg1", "sent")
        db.log_proactive("S2", "A", "critical", {}, "msg2", "sent")
        logs = db.recent_proactive_logs(limit=10)
        assert len(logs) == 2
        assert logs[0]["signal_id"] == "S2"  # Most recent first

    def test_proactive_log_table_exists(self, db):
        with db._connect() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "proactive_log" in tables
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_db.py -v 2>&1 | head -15`
Expected: FAIL — `AttributeError: 'EventsDB' has no attribute 'log_proactive'`

- [ ] **Step 3: Add proactive_log table to schema**

In `src/storage/_schema.py`, append this DDL block after the last `CREATE TABLE` statement (before any trailing `"""` or similar):

```python
# Append to TABLE_DDL string:

CREATE TABLE IF NOT EXISTS proactive_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   TEXT NOT NULL,
    tier        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    data        TEXT,
    message     TEXT,
    action      TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proactive_signal ON proactive_log(signal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_proactive_action ON proactive_log(action, created_at);
```

- [ ] **Step 4: Create ProactiveMixin**

```python
# src/storage/_proactive_mixin.py
"""Proactive log DB mixin — CRUD for proactive push history."""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class ProactiveMixin:
    """Mixed into EventsDB. Provides proactive_log table operations."""

    def log_proactive(
        self,
        signal_id: str,
        tier: str,
        severity: str,
        data: dict,
        message: str | None,
        action: str,
        reason: str = "",
    ) -> int:
        """Record a proactive signal detection (sent, throttled, or queued)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO proactive_log "
                "(signal_id, tier, severity, data, message, action, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (signal_id, tier, severity, json.dumps(data, ensure_ascii=False),
                 message, action, reason, now),
            )
            return cur.lastrowid

    def recent_proactive_logs(self, limit: int = 20) -> list[dict]:
        """Fetch recent proactive log entries."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proactive_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def proactive_log_stats(self, hours: int = 24) -> dict:
        """Aggregate stats for recent proactive activity."""
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff = (cutoff - timedelta(hours=hours)).isoformat()
        with self._connect() as conn:
            sent = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE action = 'sent' AND created_at > ?",
                (cutoff,),
            ).fetchone()[0]
            throttled = conn.execute(
                "SELECT COUNT(*) FROM proactive_log WHERE action = 'throttled' AND created_at > ?",
                (cutoff,),
            ).fetchone()[0]
        return {"sent": sent, "throttled": throttled, "period_hours": hours}
```

- [ ] **Step 5: Wire ProactiveMixin into EventsDB**

In `src/storage/events_db.py`, add the import and mixin:

```python
# Add import:
from src.storage._proactive_mixin import ProactiveMixin

# Add to class inheritance:
class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin, SessionsMixin, WakeMixin, ContextMixin, GrowthMixin, ProactiveMixin):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_db.py -v 2>&1 | tail -15`
Expected: 4 tests PASS

- [ ] **Step 7: Verify no existing tests broken**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/ -x -q 2>&1 | tail -10`
Expected: All existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add src/storage/_proactive_mixin.py src/storage/_schema.py src/storage/events_db.py tests/proactive/test_db.py
git commit -m "feat(proactive): proactive_log table + ProactiveMixin for push history"
```

---

## Task 6: ProactiveEngine — Main Loop

**Files:**
- Create: `src/proactive/engine.py`
- Create: `tests/proactive/test_engine.py`

- [ ] **Step 1: Write failing test for ProactiveEngine**

```python
# tests/proactive/test_engine.py
"""Tests for ProactiveEngine main loop."""
import pytest
from unittest.mock import MagicMock, patch

from src.proactive.signals import Signal
from src.proactive.engine import ProactiveEngine


def _make_signal(id="S1", tier="A", severity="warning"):
    return Signal(id=id, tier=tier, title="test", severity=severity, data={
        "collector": "test", "count": 3, "error": "boom",
    })


class TestProactiveEngine:
    def test_scan_cycle_no_signals(self):
        db = MagicMock()
        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        engine.detector = MagicMock()
        engine.detector.detect_all.return_value = []
        engine.scan_cycle()
        registry.broadcast.assert_not_called()

    def test_scan_cycle_sends_allowed_signal(self):
        db = MagicMock()
        db.log_proactive = MagicMock(return_value=1)
        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        signal = _make_signal()
        engine.detector = MagicMock()
        engine.detector.detect_all.return_value = [signal]
        engine.scan_cycle()
        registry.broadcast.assert_called_once()
        db.log_proactive.assert_called()

    def test_scan_cycle_throttled_signal_not_sent(self):
        db = MagicMock()
        db.log_proactive = MagicMock(return_value=1)
        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        signal = _make_signal(tier="B", severity="info")
        engine.detector = MagicMock()
        engine.detector.detect_all.return_value = [signal]
        engine.throttle.set_quiet(True)  # Force throttle
        engine.scan_cycle()
        registry.broadcast.assert_not_called()

    def test_scan_cycle_respects_llm_cap(self):
        db = MagicMock()
        db.log_proactive = MagicMock(return_value=1)
        registry = MagicMock()
        router = MagicMock()
        router.generate.return_value = "msg"
        engine = ProactiveEngine(db=db, registry=registry, llm_router=router)
        # 5 Tier-B signals, but MAX_LLM_PER_SCAN should cap LLM calls
        signals = [
            Signal(id=f"S{i}", tier="B", title="t", severity="info", data={})
            for i in range(5)
        ]
        engine.detector = MagicMock()
        engine.detector.detect_all.return_value = signals
        engine.scan_cycle()
        from src.proactive.config import MAX_LLM_PER_SCAN
        assert router.generate.call_count <= MAX_LLM_PER_SCAN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_engine.py -v 2>&1 | head -15`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write ProactiveEngine**

```python
# src/proactive/engine.py
"""ProactiveEngine — scan signals, throttle, generate, push."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.proactive import config as cfg
from src.proactive.signals import Signal, SignalDetector
from src.proactive.throttle import ThrottleGate
from src.proactive.messages import MessageGenerator

if TYPE_CHECKING:
    from src.channels.base import ChannelMessage
    from src.channels.registry import ChannelRegistry
    from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class ProactiveEngine:
    """Main loop: detect → throttle → generate → push."""

    def __init__(self, db: "EventsDB", registry: "ChannelRegistry", llm_router):
        self.db = db
        self.registry = registry
        self.detector = SignalDetector(db)
        self.throttle = ThrottleGate()
        self.generator = MessageGenerator(llm_router)

    def scan_cycle(self):
        """Single scan cycle — called by scheduler every N minutes."""
        signals = self.detector.detect_all()
        if not signals:
            return

        log.debug(f"proactive: detected {len(signals)} signals")
        llm_calls = 0

        for signal in signals:
            # Check LLM budget
            if signal.tier in ("B", "C") and llm_calls >= cfg.MAX_LLM_PER_SCAN:
                self._log_signal(signal, action="throttled", reason="llm_cap")
                continue

            if not self.throttle.should_send(signal):
                self._log_signal(signal, action="throttled", reason="throttle_gate")
                continue

            # Generate message
            message = self.generator.generate(signal)
            if signal.tier in ("B", "C"):
                llm_calls += 1

            # Push via channel registry
            try:
                from src.channels.base import ChannelMessage
                self.registry.broadcast(ChannelMessage(
                    text=message,
                    event_type=f"proactive.{signal.id}",
                    priority="HIGH" if signal.tier == "A" else "NORMAL",
                ))
                self.throttle.record_sent(signal)
                self._log_signal(signal, message=message, action="sent")
                log.info(f"proactive: pushed {signal.id} ({signal.title})")
            except Exception as e:
                log.warning(f"proactive: broadcast failed for {signal.id}: {e}")
                self._log_signal(signal, message=message, action="failed", reason=str(e))

    def _log_signal(self, signal: Signal, message: str = None,
                    action: str = "sent", reason: str = ""):
        """Persist to proactive_log table."""
        try:
            self.db.log_proactive(
                signal_id=signal.id,
                tier=signal.tier,
                severity=signal.severity,
                data=signal.data,
                message=message,
                action=action,
                reason=reason,
            )
        except Exception as e:
            log.warning(f"proactive: failed to log {signal.id}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_engine.py -v 2>&1 | tail -15`
Expected: 4 tests PASS

- [ ] **Step 5: Run all proactive tests together**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/ -v 2>&1 | tail -20`
Expected: All tests PASS (signals + throttle + messages + db + engine)

- [ ] **Step 6: Commit**

```bash
git add src/proactive/engine.py tests/proactive/test_engine.py
git commit -m "feat(proactive): ProactiveEngine — detect/throttle/generate/push loop"
```

---

## Task 7: Scheduler Integration

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: Read current scheduler.py state**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -c "from src.proactive.engine import ProactiveEngine; print('import OK')"`
Expected: `import OK`

- [ ] **Step 2: Add proactive scan job to scheduler**

In `src/scheduler.py`, after the Channel layer initialization block (after `channel_reg.start_all()`) and before the BrowserRuntime block, add:

```python
    # ── Proactive Engine: 主动推送扫描 (Reverse Prompting) ──
    try:
        from src.proactive.engine import ProactiveEngine
        from src.proactive.config import SCAN_INTERVAL_MINUTES
        from src.core.llm_router import LLMRouter

        proactive_engine = ProactiveEngine(
            db=db,
            registry=channel_reg if 'channel_reg' in dir() else None,
            llm_router=LLMRouter(),
        )
        s.add_job(
            lambda: proactive_engine.scan_cycle(),
            "interval",
            minutes=SCAN_INTERVAL_MINUTES,
            id="proactive_scan",
        )
        log.info(f"ProactiveEngine: scanning every {SCAN_INTERVAL_MINUTES}min")
    except Exception as e:
        log.debug(f"ProactiveEngine init skipped: {e}")
```

- [ ] **Step 3: Verify scheduler module loads without error**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -c "import src.scheduler; print('scheduler import OK')"`
Expected: `scheduler import OK`

- [ ] **Step 4: Commit**

```bash
git add src/scheduler.py
git commit -m "feat(proactive): wire ProactiveEngine into scheduler (5min interval)"
```

---

## Task 8: TG Bot Commands (/quiet, /loud, /proactive)

**Files:**
- Modify: `src/channels/chat/commands.py`

- [ ] **Step 1: Read commands.py again before editing**

(Re-read the file to avoid stale edits.)

- [ ] **Step 2: Add /quiet, /loud, /proactive commands**

Add to the `handle_command` dispatch chain in `src/channels/chat/commands.py`, before the `else` fallback:

```python
    elif cmd == "/quiet":
        _cmd_quiet(reply_fn, chat_id, True)
    elif cmd == "/loud":
        _cmd_quiet(reply_fn, chat_id, False)
    elif cmd == "/proactive":
        _cmd_proactive(reply_fn, chat_id, args)
```

Add to the `COMMANDS` dict:

```python
    "/quiet": "主动推送免打扰（紧急告警仍穿透）",
    "/loud": "恢复主动推送",
    "/proactive": "查看/控制主动推送 (on|off|status)",
```

Add the command handler functions at the end of the file:

```python
def _get_proactive_engine():
    """Lazy-get the ProactiveEngine singleton from scheduler context."""
    try:
        from src.proactive.engine import ProactiveEngine
        # Engine is created in scheduler.py — access via module-level reference
        # For now, create a lightweight query-only instance
        from src.storage.events_db import EventsDB
        db = EventsDB()
        return ProactiveEngine(db=db, registry=None, llm_router=None)
    except Exception:
        return None


# Shared throttle instance — commands need to toggle the same gate
_throttle_gate = None

def _get_throttle():
    global _throttle_gate
    if _throttle_gate is None:
        from src.proactive.throttle import ThrottleGate
        _throttle_gate = ThrottleGate()
    return _throttle_gate


def _cmd_quiet(reply_fn, chat_id: str, quiet: bool):
    try:
        gate = _get_throttle()
        gate.set_quiet(quiet)
        if quiet:
            reply_fn(chat_id, "🔇 主动推送已静音\n紧急告警（容器挂了等）仍会穿透\n发送 /loud 恢复")
        else:
            reply_fn(chat_id, "🔊 主动推送已恢复")
    except Exception as e:
        reply_fn(chat_id, f"操作失败: {e}")


def _cmd_proactive(reply_fn, chat_id: str, args: str):
    args = args.strip().lower()
    try:
        gate = _get_throttle()
        if args == "off":
            gate.set_enabled(False)
            reply_fn(chat_id, "主动推送已关闭\n发送 /proactive on 重新开启")
        elif args == "on":
            gate.set_enabled(True)
            reply_fn(chat_id, "主动推送已开启")
        else:
            # Show status + recent logs
            from src.storage.events_db import EventsDB
            db = EventsDB()
            stats = db.proactive_log_stats(hours=24)
            logs = db.recent_proactive_logs(limit=5)
            lines = [
                "📡 主动推送状态\n",
                f"  引擎: {'开启' if gate.is_enabled else '关闭'}",
                f"  静音: {'是' if gate.is_quiet else '否'}",
                f"  24h 推送: {stats['sent']} 条",
                f"  24h 拦截: {stats['throttled']} 条",
            ]
            if logs:
                lines.append("\n最近推送:")
                for entry in logs:
                    action_label = {"sent": "✅", "throttled": "🚫", "failed": "❌"}.get(
                        entry["action"], "?"
                    )
                    lines.append(f"  {action_label} {entry['signal_id']} — {(entry.get('message') or entry.get('reason') or '')[:60]}")
            reply_fn(chat_id, "\n".join(lines))
    except Exception as e:
        reply_fn(chat_id, f"获取状态失败: {e}")
```

- [ ] **Step 3: Verify commands parse without error**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -c "from src.channels.chat.commands import handle_command, COMMANDS; print(list(COMMANDS.keys()))"`
Expected: list includes `/quiet`, `/loud`, `/proactive`

- [ ] **Step 4: Commit**

```bash
git add src/channels/chat/commands.py
git commit -m "feat(proactive): /quiet /loud /proactive commands for TG bot"
```

---

## Task 9: Integration Smoke Test

**Files:**
- Create: `tests/proactive/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/proactive/test_integration.py
"""End-to-end smoke test for proactive engine."""
import pytest
from unittest.mock import MagicMock

from src.proactive.engine import ProactiveEngine
from src.proactive.signals import Signal
from src.storage.events_db import EventsDB


class TestProactiveIntegration:
    @pytest.fixture
    def db(self, tmp_path):
        return EventsDB(str(tmp_path / "test.db"))

    def test_full_scan_cycle_with_real_db(self, db):
        """Engine scans a real (empty) DB without crashing."""
        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        engine.scan_cycle()
        # Empty DB = no signals = no broadcasts
        registry.broadcast.assert_not_called()

    def test_full_cycle_with_injected_signal(self, db):
        """Inject collector errors, verify S1 fires and gets logged."""
        # Seed 3 consecutive ERROR logs for collector
        for i in range(3):
            db.write_log(f"采集失败: timeout {i}", "ERROR", "collector")

        registry = MagicMock()
        engine = ProactiveEngine(db=db, registry=registry, llm_router=None)
        engine.scan_cycle()

        # Should have broadcast S1
        if registry.broadcast.called:
            msg = registry.broadcast.call_args[0][0]
            assert "test_collector" in msg.text or "proactive" in msg.event_type

        # Should have logged to proactive_log
        logs = db.recent_proactive_logs(limit=10)
        assert len(logs) >= 1

    def test_commands_import_cleanly(self):
        """All new commands are registered."""
        from src.channels.chat.commands import COMMANDS
        assert "/quiet" in COMMANDS
        assert "/loud" in COMMANDS
        assert "/proactive" in COMMANDS

    def test_schema_has_proactive_table(self, db):
        with db._connect() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "proactive_log" in tables
```

- [ ] **Step 2: Run integration test**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/test_integration.py -v 2>&1 | tail -15`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/ -x -q 2>&1 | tail -10`
Expected: All tests PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/proactive/test_integration.py
git commit -m "test(proactive): integration smoke test — full scan cycle + commands + schema"
```

---

## Task 10: Shared ThrottleGate Singleton

**Important:** Task 8's commands create a local `ThrottleGate`, but the scheduler creates a separate one inside `ProactiveEngine`. They need to share state. Fix this now.

**Files:**
- Modify: `src/proactive/engine.py`
- Modify: `src/channels/chat/commands.py`

- [ ] **Step 1: Add module-level singleton accessor to engine.py**

Add at the bottom of `src/proactive/engine.py`:

```python
# ── Module-level singleton for cross-module access ──
_instance: ProactiveEngine | None = None

def get_proactive_engine() -> ProactiveEngine | None:
    """Return the singleton engine (created by scheduler)."""
    return _instance

def set_proactive_engine(engine: ProactiveEngine):
    """Called by scheduler after creating the engine."""
    global _instance
    _instance = engine
```

- [ ] **Step 2: Update scheduler.py to register singleton**

In the scheduler's proactive init block, after creating the engine, add:

```python
        from src.proactive.engine import set_proactive_engine
        set_proactive_engine(proactive_engine)
```

- [ ] **Step 3: Update commands.py to use shared singleton**

Replace `_get_throttle()` and `_get_proactive_engine()` in `src/channels/chat/commands.py`:

```python
def _get_throttle():
    """Get the throttle gate from the shared ProactiveEngine."""
    try:
        from src.proactive.engine import get_proactive_engine
        engine = get_proactive_engine()
        if engine:
            return engine.throttle
    except Exception:
        pass
    # Fallback: standalone gate (engine not yet initialized)
    from src.proactive.throttle import ThrottleGate
    return ThrottleGate()
```

Remove the `_throttle_gate` global and `_get_proactive_engine()` function.

- [ ] **Step 4: Run all proactive tests**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/proactive/ -v 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/engine.py src/scheduler.py src/channels/chat/commands.py
git commit -m "fix(proactive): shared ThrottleGate singleton between engine and commands"
```

---

## Dependency Graph

```
Task 1 (config)
  ↓
Task 2 (signals) ──→ Task 3 (throttle) ──→ Task 4 (messages)
                                               ↓
                     Task 5 (DB mixin) ───→ Task 6 (engine)
                                               ↓
                     Task 7 (scheduler) ←──────┘
                         ↓
                     Task 8 (commands)
                         ↓
                     Task 9 (integration test)
                         ↓
                     Task 10 (singleton fix)
```

Tasks 2, 3, 4 can run in parallel after Task 1. Task 5 can run in parallel with Tasks 2-4. Everything else is sequential.
