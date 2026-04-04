# Proactive Phase 2: Engine + Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire SignalDetector → ThrottleGate → MessageGenerator → Channel into a live scan loop, add daily/weekly digest aggregation, and register everything in the scheduler so proactive push actually delivers to Telegram.

**Architecture:** A `ProactiveEngine` orchestrates the scan cycle: detect signals → filter through throttle → generate messages → broadcast via channel registry → persist to `proactive_log`. A separate `DigestBuilder` queries `proactive_log` to aggregate signals into daily (09:00 CST) and weekly (Monday 09:30 CST) summaries. Both are pure functions taking `db` as input, registered as APScheduler jobs alongside existing periodic tasks.

**Tech Stack:** Python 3.11, APScheduler, SQLite (EventsDB), existing channel registry (Telegram/WeCom)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/proactive/engine.py` | Scan loop: detect → throttle → message → broadcast → log |
| Create | `src/proactive/digest.py` | Aggregate proactive_log into daily/weekly HTML digest |
| Modify | `src/scheduler.py:38-57` | Register 3 new jobs: scan, daily digest, weekly digest |
| Create | `tests/proactive/test_engine.py` | Engine unit tests |
| Create | `tests/proactive/test_digest.py` | Digest unit tests |

---

## Task 1: ProactiveEngine — scan loop

**Files:**
- Create: `src/proactive/engine.py`
- Test: `tests/proactive/test_engine.py`

- [ ] **Step 1: Write failing tests for ProactiveEngine**

```python
"""Tests for ProactiveEngine scan loop."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.proactive.engine import ProactiveEngine
from src.proactive.signals import Signal


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.log_proactive = MagicMock(return_value=1)
    db._connect = MagicMock()
    return db


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.broadcast = MagicMock()
    return reg


@pytest.fixture
def engine(mock_db, mock_registry):
    return ProactiveEngine(db=mock_db, channel_registry=mock_registry, llm_router=None)


def _make_signal(sid="S1", tier="A", severity="critical"):
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={"k": "v"})


class TestRunScan:
    def test_scan_with_no_signals(self, engine):
        with patch.object(engine._detector, "detect_all", return_value=[]):
            sent, throttled = engine.run_scan()
        assert sent == 0
        assert throttled == 0

    def test_scan_sends_passing_signal(self, engine, mock_db, mock_registry):
        sig = _make_signal()
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            sent, throttled = engine.run_scan()
        assert sent == 1
        assert throttled == 0
        mock_registry.broadcast.assert_called_once()
        mock_db.log_proactive.assert_called_once()
        assert mock_db.log_proactive.call_args.kwargs["action"] == "sent"

    def test_scan_throttles_blocked_signal(self, engine, mock_db, mock_registry):
        sig = _make_signal(sid="S3", tier="C", severity="low")
        with (
            patch.object(engine._detector, "detect_all", return_value=[sig]),
            patch.object(engine._throttle, "should_send", return_value=False),
        ):
            sent, throttled = engine.run_scan()
        assert sent == 0
        assert throttled == 1
        mock_registry.broadcast.assert_not_called()
        assert mock_db.log_proactive.call_args.kwargs["action"] == "throttled"

    def test_scan_records_sent_in_throttle(self, engine):
        sig = _make_signal()
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            engine.run_scan()
        # throttle.record_sent should have been called for the sent signal
        assert any(
            sid == "S1" for sid, _ in engine._throttle._sent_log
        )

    def test_scan_handles_broadcast_failure(self, engine, mock_registry, mock_db):
        sig = _make_signal()
        mock_registry.broadcast.side_effect = Exception("network error")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            sent, throttled = engine.run_scan()
        # Should not crash, signal logged as send_failed
        assert sent == 0
        assert mock_db.log_proactive.call_args.kwargs["action"] == "send_failed"

    def test_scan_drains_queued_signals(self, engine, mock_registry):
        """Queued signals from previous throttle should be retried."""
        sig = _make_signal(sid="S5", tier="B", severity="medium")
        engine._throttle._queued.append(sig)
        with patch.object(engine._detector, "detect_all", return_value=[]):
            with patch.object(engine._throttle, "should_send", return_value=True):
                sent, _ = engine.run_scan()
        assert sent == 1


class TestMapPriority:
    def test_tier_a_maps_to_critical(self, engine):
        assert engine._map_priority("A", "critical") == "CRITICAL"

    def test_tier_b_maps_to_high(self, engine):
        assert engine._map_priority("B", "high") == "HIGH"

    def test_tier_c_maps_to_normal(self, engine):
        assert engine._map_priority("C", "medium") == "NORMAL"

    def test_tier_d_maps_to_low(self, engine):
        assert engine._map_priority("D", "low") == "LOW"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/proactive/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.proactive.engine'`

- [ ] **Step 3: Implement ProactiveEngine**

```python
"""ProactiveEngine — scan loop that wires SignalDetector → ThrottleGate → MessageGenerator → Channel."""
from __future__ import annotations

import logging
from typing import Any

from src.channels.base import ChannelMessage
from src.proactive.messages import MessageGenerator
from src.proactive.signals import Signal, SignalDetector
from src.proactive.throttle import ThrottleGate
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

# Tier/severity → ChannelMessage priority
_PRIORITY_MAP: dict[str, str] = {
    "A": "CRITICAL",
    "B": "HIGH",
    "C": "NORMAL",
    "D": "LOW",
}


class ProactiveEngine:
    """Orchestrates the proactive scan cycle.

    Each ``run_scan()`` call:
    1. Detects all signals via ``SignalDetector``
    2. Drains previously queued signals from ThrottleGate
    3. For each signal, checks ThrottleGate
    4. Generates a message via MessageGenerator
    5. Broadcasts via ChannelRegistry
    6. Persists outcome to ``proactive_log``
    """

    def __init__(
        self,
        db: EventsDB,
        channel_registry: Any,
        llm_router: Any | None = None,
    ) -> None:
        self._db = db
        self._registry = channel_registry
        self._detector = SignalDetector(db)
        self._throttle = ThrottleGate()
        self._messenger = MessageGenerator(llm_router)

    # ── public API ────────────────────────────────────────────────────────────

    def run_scan(self) -> tuple[int, int]:
        """Run one scan cycle. Returns (sent_count, throttled_count)."""
        signals = self._detector.detect_all()

        # Drain signals queued from previous cycles (time-window / rate cap)
        queued = self._throttle.drain_queued()
        signals.extend(queued)

        sent = 0
        throttled = 0

        for sig in signals:
            if self._throttle.should_send(sig):
                ok = self._try_send(sig)
                if ok:
                    sent += 1
                    self._throttle.record_sent(sig)
            else:
                throttled += 1
                self._db.log_proactive(
                    signal_id=sig.id,
                    tier=sig.tier,
                    severity=sig.severity,
                    data=sig.data,
                    message="",
                    action="throttled",
                    reason="throttle_gate",
                )

        if sent or throttled:
            logger.info("Proactive scan: sent=%d throttled=%d", sent, throttled)
        return sent, throttled

    # ── internals ─────────────────────────────────────────────────────────────

    def _try_send(self, sig: Signal) -> bool:
        """Generate message, broadcast, and log. Returns True on success."""
        try:
            text = self._messenger.generate(sig)
            msg = ChannelMessage(
                text=text,
                event_type=f"proactive.{sig.id}",
                priority=self._map_priority(sig.tier, sig.severity),
                department="proactive",
            )
            self._registry.broadcast(msg)
            self._db.log_proactive(
                signal_id=sig.id,
                tier=sig.tier,
                severity=sig.severity,
                data=sig.data,
                message=text,
                action="sent",
            )
            return True
        except Exception:
            logger.exception("Failed to send signal %s", sig.id)
            self._db.log_proactive(
                signal_id=sig.id,
                tier=sig.tier,
                severity=sig.severity,
                data=sig.data,
                message="",
                action="send_failed",
                reason="broadcast_exception",
            )
            return False

    @staticmethod
    def _map_priority(tier: str, severity: str) -> str:
        """Map signal tier to ChannelMessage priority level."""
        return _PRIORITY_MAP.get(tier, "NORMAL")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/proactive/test_engine.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/engine.py tests/proactive/test_engine.py
git commit -m "feat(proactive): ProactiveEngine scan loop — detect → throttle → send → log"
```

---

## Task 2: DigestBuilder — daily/weekly reports

**Files:**
- Create: `src/proactive/digest.py`
- Test: `tests/proactive/test_digest.py`

depends on: Task 1 (uses proactive_log data written by engine)

- [ ] **Step 1: Write failing tests for DigestBuilder**

```python
"""Tests for DigestBuilder — daily/weekly signal aggregation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.proactive.digest import DigestBuilder


@pytest.fixture
def db():
    """In-memory EventsDB with proactive_log data."""
    from src.storage.events_db import EventsDB
    _db = EventsDB(":memory:")
    return _db


@pytest.fixture
def builder(db):
    return DigestBuilder(db)


def _seed_logs(db, entries):
    """Insert proactive_log entries. Each entry: (signal_id, tier, severity, data, message, action, created_at)."""
    with db._connect() as conn:
        for e in entries:
            conn.execute(
                "INSERT INTO proactive_log (signal_id, tier, severity, data, message, action, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                e,
            )


class TestBuildDaily:
    def test_empty_returns_none(self, builder):
        result = builder.build_daily()
        assert result is None

    def test_returns_summary_with_sent_signals(self, db, builder):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=2)).isoformat()
        _seed_logs(db, [
            ("S1", "A", "critical", '{"collector":"rss"}', "RSS挂了", "sent", recent),
            ("S3", "A", "high", '{"size_mb":55}', "DB大了", "sent", recent),
            ("S7", "B", "medium", '{"count":5}', "重复错误", "sent", recent),
            ("S11", "D", "low", '{}', "GitHub通知", "throttled", recent),
        ])
        result = builder.build_daily()
        assert result is not None
        assert "sent" in result.lower() or "发送" in result or "S1" in result
        # Should contain signal counts
        assert "3" in result  # 3 sent signals

    def test_excludes_old_logs(self, db, builder):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        _seed_logs(db, [
            ("S1", "A", "critical", '{}', "旧信号", "sent", old),
        ])
        result = builder.build_daily()
        assert result is None


class TestBuildWeekly:
    def test_empty_returns_none(self, builder):
        result = builder.build_weekly()
        assert result is None

    def test_returns_trend_summary(self, db, builder):
        now = datetime.now(timezone.utc)
        for day_offset in range(5):
            ts = (now - timedelta(days=day_offset, hours=3)).isoformat()
            _seed_logs(db, [
                ("S1", "A", "critical", '{}', "采集器挂", "sent", ts),
            ])
        result = builder.build_weekly()
        assert result is not None
        assert "5" in result  # 5 total signals across the week
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/proactive/test_digest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.proactive.digest'`

- [ ] **Step 3: Implement DigestBuilder**

```python
"""DigestBuilder — aggregate proactive_log into daily / weekly HTML digests."""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

_TIER_LABELS = {"A": "🔴 Critical", "B": "🟡 Important", "C": "🔵 Info", "D": "⚪ Digest"}
_TIER_ORDER = ["A", "B", "C", "D"]


class DigestBuilder:
    """Build human-readable digest strings from proactive_log history."""

    def __init__(self, db: EventsDB) -> None:
        self._db = db

    # ── public API ────────────────────────────────────────────────────────────

    def build_daily(self) -> str | None:
        """Build a 24h digest. Returns None if nothing to report."""
        rows = self._query_logs(hours=24)
        if not rows:
            return None
        return self._format_digest(rows, period="日报")

    def build_weekly(self) -> str | None:
        """Build a 7-day digest. Returns None if nothing to report."""
        rows = self._query_logs(hours=168)
        if not rows:
            return None
        return self._format_digest(rows, period="周报")

    # ── internals ─────────────────────────────────────────────────────────────

    def _query_logs(self, hours: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._db._connect() as conn:
            rows = conn.execute(
                "SELECT signal_id, tier, severity, message, action, created_at "
                "FROM proactive_log WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _format_digest(self, rows: list[dict], period: str) -> str:
        sent = [r for r in rows if r["action"] == "sent"]
        throttled = [r for r in rows if r["action"] == "throttled"]

        lines: list[str] = [f"<b>📊 Orchestrator {period}</b>"]
        lines.append(f"sent: {len(sent)} | throttled: {len(throttled)}")
        lines.append("")

        # Group sent signals by tier
        by_tier: dict[str, list[dict]] = {}
        for r in sent:
            by_tier.setdefault(r["tier"], []).append(r)

        for tier in _TIER_ORDER:
            group = by_tier.get(tier, [])
            if not group:
                continue
            label = _TIER_LABELS.get(tier, tier)
            lines.append(f"<b>{label} ({len(group)})</b>")
            # Count by signal_id
            id_counts = Counter(r["signal_id"] for r in group)
            for sid, cnt in id_counts.most_common():
                sample = next(r for r in group if r["signal_id"] == sid)
                msg_preview = (sample.get("message") or sid)[:80]
                suffix = f" ×{cnt}" if cnt > 1 else ""
                lines.append(f"  • {msg_preview}{suffix}")
            lines.append("")

        if throttled:
            lines.append(f"<i>🔇 Throttled: {len(throttled)}</i>")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/proactive/test_digest.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/proactive/digest.py tests/proactive/test_digest.py
git commit -m "feat(proactive): DigestBuilder — daily/weekly HTML digest from proactive_log"
```

---

## Task 3: Scheduler wiring + job entry point

**Files:**
- Modify: `src/scheduler.py:38-57` (add 3 jobs)
- Create: `src/jobs/proactive_jobs.py` (thin wrappers)
- Test: `tests/jobs/test_proactive_jobs.py`

depends on: Task 1, Task 2

- [ ] **Step 1: Write failing test for job wrappers**

```python
"""Tests for proactive job entry points."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_proactive_scan_calls_engine(tmp_path):
    from src.jobs.proactive_jobs import proactive_scan

    db = MagicMock()
    db._connect = MagicMock()

    with patch("src.jobs.proactive_jobs.ProactiveEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.run_scan.return_value = (2, 1)
        proactive_scan(db)
        MockEngine.assert_called_once()
        instance.run_scan.assert_called_once()


def test_proactive_daily_digest_broadcasts(tmp_path):
    from src.jobs.proactive_jobs import proactive_daily_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs.get_channel_registry") as mock_reg,
    ):
        MockDigest.return_value.build_daily.return_value = "<b>日报</b>\ntest"
        proactive_daily_digest(db)
        mock_reg.return_value.broadcast.assert_called_once()


def test_proactive_daily_digest_skips_when_empty(tmp_path):
    from src.jobs.proactive_jobs import proactive_daily_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs.get_channel_registry") as mock_reg,
    ):
        MockDigest.return_value.build_daily.return_value = None
        proactive_daily_digest(db)
        mock_reg.return_value.broadcast.assert_not_called()


def test_proactive_weekly_digest_broadcasts(tmp_path):
    from src.jobs.proactive_jobs import proactive_weekly_digest

    db = MagicMock()

    with (
        patch("src.jobs.proactive_jobs.DigestBuilder") as MockDigest,
        patch("src.jobs.proactive_jobs.get_channel_registry") as mock_reg,
    ):
        MockDigest.return_value.build_weekly.return_value = "<b>周报</b>\ntest"
        proactive_weekly_digest(db)
        mock_reg.return_value.broadcast.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/jobs/test_proactive_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.jobs.proactive_jobs'`

- [ ] **Step 3: Implement job wrappers**

```python
"""Proactive job entry points — thin wrappers for scheduler registration."""
from __future__ import annotations

import logging

from src.channels.base import ChannelMessage
from src.proactive.digest import DigestBuilder
from src.proactive.engine import ProactiveEngine
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)


def _get_registry():
    """Lazy import to avoid circular dependency at module level."""
    from src.channels.registry import get_channel_registry
    return get_channel_registry()


def proactive_scan(db: EventsDB) -> None:
    """Run one proactive signal scan cycle."""
    registry = _get_registry()
    engine = ProactiveEngine(db=db, channel_registry=registry)
    sent, throttled = engine.run_scan()
    if sent or throttled:
        db.write_log(
            f"Proactive scan: sent={sent} throttled={throttled}",
            "INFO", "proactive",
        )


def proactive_daily_digest(db: EventsDB) -> None:
    """Build and broadcast daily digest."""
    builder = DigestBuilder(db)
    text = builder.build_daily()
    if text is None:
        logger.info("Daily digest: nothing to report")
        return
    registry = _get_registry()
    registry.broadcast(ChannelMessage(
        text=text,
        event_type="proactive.digest.daily",
        priority="NORMAL",
        department="proactive",
    ))
    db.write_log("Daily digest sent", "INFO", "proactive")


def proactive_weekly_digest(db: EventsDB) -> None:
    """Build and broadcast weekly digest."""
    builder = DigestBuilder(db)
    text = builder.build_weekly()
    if text is None:
        logger.info("Weekly digest: nothing to report")
        return
    registry = _get_registry()
    registry.broadcast(ChannelMessage(
        text=text,
        event_type="proactive.digest.weekly",
        priority="NORMAL",
        department="proactive",
    ))
    db.write_log("Weekly digest sent", "INFO", "proactive")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/jobs/test_proactive_jobs.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Wire into scheduler.py**

Add these 3 jobs to `src/scheduler.py` after the existing `sync_vectors` job (line 57):

```python
from src.jobs.proactive_jobs import proactive_scan, proactive_daily_digest, proactive_weekly_digest
```

```python
s.add_job(lambda: run_job("proactive_scan", proactive_scan, db), "interval", minutes=5, id="proactive_scan")
s.add_job(lambda: run_job("proactive_daily", proactive_daily_digest, db), "cron", hour=9, timezone="Asia/Shanghai", id="proactive_daily")
s.add_job(lambda: run_job("proactive_weekly", proactive_weekly_digest, db), "cron", day_of_week="mon", hour=9, minute=30, timezone="Asia/Shanghai", id="proactive_weekly")
```

Update the startup log message to include proactive scan info.

- [ ] **Step 6: Run full proactive test suite**

Run: `python -m pytest tests/proactive/ tests/jobs/test_proactive_jobs.py -v`
Expected: All tests PASS (36 existing + 8 engine + 5 digest + 4 jobs = 53 total)

- [ ] **Step 7: Commit**

```bash
git add src/jobs/proactive_jobs.py tests/jobs/test_proactive_jobs.py src/scheduler.py
git commit -m "feat(proactive): wire engine + digest into scheduler — scan every 5min, daily 09:00, weekly Mon 09:30"
```

---

## Task 4: Commit the pending S7-S12 implementation

**Files:**
- Modified: `src/proactive/config.py`
- Modified: `src/proactive/signals.py`
- Modified: `tests/proactive/test_signals.py`

Note: These changes are already written and tested (36/36 pass). They should be committed first as they are the foundation for everything else.

- [ ] **Step 1: Commit the S7-S12 implementation**

```bash
git add src/proactive/config.py src/proactive/signals.py tests/proactive/test_signals.py
git commit -m "feat(proactive): implement S7-S12 signal detectors — repeated patterns, batch completion, defer overdue, GitHub activity, dependency vulns"
```

**Execution order:** Task 4 → Task 1 → Task 2 → Task 3
