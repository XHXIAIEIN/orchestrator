# Evolution Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the self-evolution loop — Orchestrator autonomously detects issues, classifies risk, executes fixes, evaluates results, and feeds learnings back into Qdrant.

**Architecture:** A new `src/evolution/` module with 3 files (loop, risk, actions) wires the existing ProactiveEngine signals into Governor dispatch, gated by a RiskClassifier. After execution, results feed into ExperimentLedger for keep/discard decisions, then back to InstinctPipeline for long-term learning.

**Tech Stack:** Python 3.14, SQLite (events.db), Qdrant, Ollama embeddings, APScheduler, existing Governor/Blueprint/ProactiveEngine

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/evolution/__init__.py` | Package init |
| Create | `src/evolution/risk.py` | RiskLevel enum + RiskClassifier (signal → AUTO/REVIEW/BLOCK) |
| Create | `src/evolution/actions.py` | 6 Action types + ActionResult + rollback logic |
| Create | `src/evolution/loop.py` | EvolutionEngine: detect → classify → act → evaluate → learn |
| Create | `src/jobs/evolution_jobs.py` | Scheduler entry points (thin wrappers) |
| Create | `tests/evolution/__init__.py` | Test package |
| Create | `tests/evolution/test_risk.py` | RiskClassifier unit tests |
| Create | `tests/evolution/test_actions.py` | Action execution + rollback tests |
| Create | `tests/evolution/test_loop.py` | Full cycle integration tests |
| Modify | `src/scheduler.py:60-63` | Register evolution_cycle + steal_patrol jobs |
| Modify | `src/storage/_schema.py` | Add `evolution_log` table DDL |
| Modify | `src/storage/events_db.py` | Add EvolutionMixin (log_evolution, get_evolution_history) |

---

### Task 1: evolution_log Table + DB Mixin

**Files:**
- Modify: `src/storage/_schema.py`
- Create: `src/storage/mixins/evolution_mixin.py`
- Modify: `src/storage/events_db.py`
- Create: `tests/evolution/__init__.py`
- Create: `tests/evolution/test_evolution_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/evolution/test_evolution_db.py
"""Tests for evolution_log table and EvolutionMixin."""
import pytest
from src.storage.events_db import EventsDB


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def test_log_evolution_and_retrieve(db):
    row_id = db.log_evolution(
        signal_id="S1",
        action_type="collector_heal",
        risk_level="AUTO",
        status="success",
        detail={"collector": "git", "fix": "restart"},
        score_before=None,
        score_after=None,
    )
    assert row_id > 0

    history = db.get_evolution_history(limit=10)
    assert len(history) == 1
    row = history[0]
    assert row["signal_id"] == "S1"
    assert row["action_type"] == "collector_heal"
    assert row["risk_level"] == "AUTO"
    assert row["status"] == "success"


def test_log_evolution_with_scores(db):
    row_id = db.log_evolution(
        signal_id="S4",
        action_type="prompt_tune",
        risk_level="REVIEW",
        status="kept",
        detail={"department": "engineering", "diff_lines": 12},
        score_before=0.82,
        score_after=0.87,
    )
    history = db.get_evolution_history(limit=1)
    assert history[0]["score_before"] == 0.82
    assert history[0]["score_after"] == 0.87


def test_get_evolution_history_filter_by_action(db):
    db.log_evolution("S1", "collector_heal", "AUTO", "success", {})
    db.log_evolution("S4", "prompt_tune", "REVIEW", "kept", {})
    db.log_evolution("S1", "collector_heal", "AUTO", "failed", {})

    heals = db.get_evolution_history(action_type="collector_heal")
    assert len(heals) == 2
    assert all(r["action_type"] == "collector_heal" for r in heals)
```

- [ ] **Step 2: Create tests/evolution/__init__.py**

```python
# tests/evolution/__init__.py
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/evolution/test_evolution_db.py -v`
Expected: FAIL — `log_evolution` method does not exist

- [ ] **Step 4: Add evolution_log DDL to schema**

In `src/storage/_schema.py`, append to `TABLE_DDL`:

```sql
CREATE TABLE IF NOT EXISTS evolution_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   TEXT NOT NULL,
    action_type TEXT NOT NULL,
    risk_level  TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT DEFAULT '{}',
    score_before REAL,
    score_after  REAL,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evo_action ON evolution_log(action_type);
CREATE INDEX IF NOT EXISTS idx_evo_created ON evolution_log(created_at);
```

- [ ] **Step 5: Create EvolutionMixin**

```python
# src/storage/mixins/evolution_mixin.py
"""DB mixin for evolution_log table."""
from __future__ import annotations

import json
from typing import Any


class EvolutionMixin:
    """Mixin providing evolution log read/write methods."""

    def log_evolution(
        self,
        signal_id: str,
        action_type: str,
        risk_level: str,
        status: str,
        detail: dict[str, Any] | None = None,
        score_before: float | None = None,
        score_after: float | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO evolution_log
                   (signal_id, action_type, risk_level, status, detail, score_before, score_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (signal_id, action_type, risk_level, status,
                 json.dumps(detail or {}, ensure_ascii=False),
                 score_before, score_after),
            )
            return cur.lastrowid

    def get_evolution_history(
        self,
        limit: int = 50,
        action_type: str | None = None,
    ) -> list[dict]:
        q = "SELECT * FROM evolution_log"
        params: list = []
        if action_type:
            q += " WHERE action_type = ?"
            params.append(action_type)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 6: Wire EvolutionMixin into EventsDB**

In `src/storage/events_db.py`, add import and mixin:

```python
from src.storage.mixins.evolution_mixin import EvolutionMixin

class EventsDB(..., EvolutionMixin):
    ...
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/evolution/test_evolution_db.py -v`
Expected: 3 tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/storage/_schema.py src/storage/mixins/evolution_mixin.py src/storage/events_db.py tests/evolution/
git commit -m "feat(evolution): add evolution_log table + EvolutionMixin"
```

---

### Task 2: RiskClassifier

**Files:**
- Create: `src/evolution/__init__.py`
- Create: `src/evolution/risk.py`
- Create: `tests/evolution/test_risk.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/evolution/test_risk.py
"""Tests for RiskClassifier — signal → risk level mapping."""
import pytest
from src.proactive.signals import Signal
from src.evolution.risk import RiskLevel, RiskClassifier, ActionType


def _signal(sid: str, tier: str = "B", severity: str = "medium") -> Signal:
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={})


class TestRiskClassifier:
    def test_collector_fail_is_auto(self):
        sig = _signal("S1", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.AUTO
        assert result.action_type == ActionType.COLLECTOR_HEAL

    def test_governor_fail_maps_to_prompt_tune(self):
        sig = _signal("S4", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.PROMPT_TUNE
        assert result.risk == RiskLevel.REVIEW

    def test_db_size_maps_to_memory_hygiene(self):
        sig = _signal("S3", tier="B", severity="medium")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.MEMORY_HYGIENE
        assert result.risk == RiskLevel.AUTO

    def test_repeated_pattern_maps_to_param_tune(self):
        sig = _signal("S7", tier="B", severity="medium")
        result = RiskClassifier.classify(sig)
        assert result.action_type == ActionType.PARAM_TUNE
        assert result.risk == RiskLevel.REVIEW

    def test_unknown_signal_returns_none(self):
        sig = _signal("S99", tier="D", severity="low")
        result = RiskClassifier.classify(sig)
        assert result is None

    def test_container_health_is_block(self):
        sig = _signal("S2", tier="A", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.BLOCK

    def test_dependency_vuln_is_block(self):
        sig = _signal("S12", tier="D", severity="high")
        result = RiskClassifier.classify(sig)
        assert result.risk == RiskLevel.BLOCK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/evolution/test_risk.py -v`
Expected: FAIL — module `src.evolution.risk` does not exist

- [ ] **Step 3: Implement risk.py**

```python
# src/evolution/__init__.py
```

```python
# src/evolution/risk.py
"""RiskClassifier — maps proactive Signals to risk levels and action types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.proactive.signals import Signal


class RiskLevel(Enum):
    AUTO = "AUTO"        # Execute immediately, log only
    REVIEW = "REVIEW"    # Execute, then notify owner
    BLOCK = "BLOCK"      # Notify owner, wait for approval


class ActionType(Enum):
    MEMORY_HYGIENE = "memory_hygiene"
    COLLECTOR_HEAL = "collector_heal"
    PROMPT_TUNE = "prompt_tune"
    PARAM_TUNE = "param_tune"
    CODE_FIX = "code_fix"
    STEAL_PATROL = "steal_patrol"


@dataclass
class ClassificationResult:
    risk: RiskLevel
    action_type: ActionType
    reason: str


# ── Signal → (ActionType, RiskLevel) routing table ────────────────────────────
# Key: signal ID.  Value: (action_type, risk_level, reason).
# Signals not in this table are ignored (no automatic action).

_ROUTING: dict[str, tuple[ActionType, RiskLevel, str]] = {
    # S1: collector failures — auto-heal, low risk
    "S1": (ActionType.COLLECTOR_HEAL, RiskLevel.AUTO,
           "Collector streak failure — restart or fix path"),
    # S2: container health — dangerous, need human
    "S2": (ActionType.CODE_FIX, RiskLevel.BLOCK,
           "Container unhealthy — needs investigation"),
    # S3: DB size warning — memory cleanup
    "S3": (ActionType.MEMORY_HYGIENE, RiskLevel.AUTO,
           "DB growing large — run hygiene"),
    # S4: governor failures — prompt might need tuning
    "S4": (ActionType.PROMPT_TUNE, RiskLevel.REVIEW,
           "Governor failure streak — check department prompts"),
    # S5: project silence — informational, no action
    # S6: late night activity — informational, no action
    # S7: repeated patterns — parameter tuning opportunity
    "S7": (ActionType.PARAM_TUNE, RiskLevel.REVIEW,
           "Repeated pattern detected — consider parameter adjustment"),
    # S10: deferred overdue — memory hygiene
    "S10": (ActionType.MEMORY_HYGIENE, RiskLevel.AUTO,
            "Deferred items overdue — cull or promote"),
    # S12: dependency vulnerabilities — needs human review
    "S12": (ActionType.CODE_FIX, RiskLevel.BLOCK,
            "Dependency vulnerability — needs security review"),
}


class RiskClassifier:
    """Stateless classifier: Signal → ClassificationResult | None."""

    @staticmethod
    def classify(signal: Signal) -> Optional[ClassificationResult]:
        """Classify a signal into risk level + action type.

        Returns None for signals that have no automatic action
        (informational only, e.g. S5, S6, S8, S9, S11).
        """
        route = _ROUTING.get(signal.id)
        if route is None:
            return None
        action_type, risk, reason = route
        return ClassificationResult(risk=risk, action_type=action_type, reason=reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/evolution/test_risk.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/evolution/ tests/evolution/test_risk.py
git commit -m "feat(evolution): RiskClassifier — signal-to-action routing table"
```

---

### Task 3: Action Definitions + Rollback

**Files:**
- Create: `src/evolution/actions.py`
- Create: `tests/evolution/test_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/evolution/test_actions.py
"""Tests for evolution actions — execute + rollback."""
import pytest
from unittest.mock import MagicMock, patch
from src.evolution.actions import (
    ActionResult, MemoryHygieneAction, CollectorHealAction,
    StealPatrolAction, ActionStatus,
)


class TestMemoryHygieneAction:
    def test_execute_calls_experience_cull(self):
        db = MagicMock()
        action = MemoryHygieneAction()
        with patch("src.evolution.actions.run_cull") as mock_cull:
            mock_cull.return_value = MagicMock(
                retired=[{"id": 1}], at_risk=[], promoted=[], total_active=40,
                format=MagicMock(return_value="1 retired"),
            )
            result = action.execute(db, signal_data={"size_mb": 55})
        assert result.status == ActionStatus.SUCCESS
        assert result.detail["retired_count"] == 1
        mock_cull.assert_called_once_with(db)

    def test_rollback_is_noop(self):
        action = MemoryHygieneAction()
        # Should not raise
        action.rollback(MagicMock(), {})


class TestCollectorHealAction:
    def test_execute_restarts_collector(self):
        db = MagicMock()
        action = CollectorHealAction()
        with patch("src.evolution.actions.run_collectors") as mock_collect:
            mock_collect.return_value = None
            result = action.execute(db, signal_data={"collector": "git", "error": "path not found"})
        assert result.status == ActionStatus.SUCCESS
        mock_collect.assert_called_once()

    def test_execute_handles_failure(self):
        db = MagicMock()
        action = CollectorHealAction()
        with patch("src.evolution.actions.run_collectors", side_effect=Exception("boom")):
            result = action.execute(db, signal_data={"collector": "git"})
        assert result.status == ActionStatus.FAILED
        assert "boom" in result.detail.get("error", "")


class TestStealPatrolAction:
    def test_execute_scans_watchlist(self):
        db = MagicMock()
        action = StealPatrolAction()
        result = action.execute(db, signal_data={})
        # Steal patrol is read-only, should always succeed
        assert result.status in (ActionStatus.SUCCESS, ActionStatus.SKIPPED)


class TestActionResult:
    def test_is_success(self):
        r = ActionResult(status=ActionStatus.SUCCESS, detail={"msg": "ok"})
        assert r.is_success

    def test_is_not_success_on_fail(self):
        r = ActionResult(status=ActionStatus.FAILED, detail={"error": "bad"})
        assert not r.is_success
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/evolution/test_actions.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement actions.py**

```python
# src/evolution/actions.py
"""Evolution actions — concrete operations the loop can execute autonomously."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class ActionStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class ActionResult:
    status: ActionStatus
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == ActionStatus.SUCCESS


class BaseAction(ABC):
    """Base class for all evolution actions."""

    @abstractmethod
    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        """Execute the action. Returns ActionResult."""

    def rollback(self, db: EventsDB, execute_detail: dict[str, Any]) -> None:
        """Rollback the action. Default: no-op (action is inherently safe)."""


# ── 1. Memory Hygiene ─────────────────────────────────────────────────────────

class MemoryHygieneAction(BaseAction):
    """Retire stale learnings, dedup memories, decay hotness."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.governance.learning.experience_cull import run_cull
        try:
            report = run_cull(db)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail={
                    "retired_count": len(report.retired),
                    "promoted_count": len(report.promoted),
                    "at_risk_count": len(report.at_risk),
                    "total_active": report.total_active,
                    "summary": report.format(),
                },
            )
        except Exception as e:
            log.warning(f"MemoryHygiene failed: {e}")
            return ActionResult(status=ActionStatus.FAILED, detail={"error": str(e)})


# ── 2. Collector Heal ──────────────────────────────────────────────────────────

class CollectorHealAction(BaseAction):
    """Restart failed collectors."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.jobs.collectors import run_collectors
        collector = signal_data.get("collector", "unknown")
        try:
            run_collectors(db)
            return ActionResult(
                status=ActionStatus.SUCCESS,
                detail={"collector": collector, "action": "restarted"},
            )
        except Exception as e:
            log.warning(f"CollectorHeal failed for {collector}: {e}")
            return ActionResult(
                status=ActionStatus.FAILED,
                detail={"collector": collector, "error": str(e)},
            )


# ── 3. Prompt Tune ────────────────────────────────────────────────────────────

class PromptTuneAction(BaseAction):
    """Apply skill evolution suggestions to department SKILL.md."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        from src.governance.learning.skill_evolver import analyze_department
        from pathlib import Path

        department = signal_data.get("department")
        if not department:
            return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "no department in signal"})

        suggestion_path = Path(f"departments/{department}/skill-suggestions.md")
        skill_path = Path(f"departments/{department}/SKILL.md")

        if not suggestion_path.exists():
            # Generate suggestions first
            result_text = analyze_department(department)
            if not result_text:
                return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "insufficient data for analysis"})

        if not suggestion_path.exists():
            return ActionResult(status=ActionStatus.SKIPPED, detail={"reason": "no suggestions generated"})

        # Save original for rollback
        original = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
        suggestions = suggestion_path.read_text(encoding="utf-8")

        return ActionResult(
            status=ActionStatus.SUCCESS,
            detail={
                "department": department,
                "original_hash": hash(original),
                "suggestions_preview": suggestions[:200],
                "applied": False,  # Mark as "ready to apply" — actual apply needs LLM rewrite
            },
        )

    def rollback(self, db: EventsDB, execute_detail: dict[str, Any]) -> None:
        # Prompt tune rollback handled by ExperimentLedger discard → git checkout
        pass


# ── 4. Param Tune ─────────────────────────────────────────────────────────────

class ParamTuneAction(BaseAction):
    """Adjust numerical parameters based on observed patterns."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        # For now: log the opportunity, don't auto-modify config
        pattern = signal_data.get("pattern", "unknown")
        return ActionResult(
            status=ActionStatus.SUCCESS,
            detail={"pattern": pattern, "recommendation": "logged for review"},
        )


# ── 5. Code Fix ───────────────────────────────────────────────────────────────

class CodeFixAction(BaseAction):
    """Fix lint errors, broken imports — only for BLOCK signals, so this is a no-op
    that flags the issue for human review."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        # BLOCK-level: we only create a report, not auto-fix
        return ActionResult(
            status=ActionStatus.SKIPPED,
            detail={"reason": "BLOCK-level action — awaiting owner approval", "signal_data": signal_data},
        )


# ── 6. Steal Patrol ───────────────────────────────────────────────────────────

class StealPatrolAction(BaseAction):
    """Scan watchlist repos for new patterns. Read-only operation."""

    def execute(self, db: EventsDB, signal_data: dict[str, Any]) -> ActionResult:
        # Phase 1: just log that patrol ran.
        # Phase 2 (future): actually scan GitHub repos via API.
        return ActionResult(
            status=ActionStatus.SKIPPED,
            detail={"reason": "steal patrol placeholder — needs GitHub API integration"},
        )


# ── Action Registry ───────────────────────────────────────────────────────────

from src.evolution.risk import ActionType

ACTION_REGISTRY: dict[ActionType, BaseAction] = {
    ActionType.MEMORY_HYGIENE: MemoryHygieneAction(),
    ActionType.COLLECTOR_HEAL: CollectorHealAction(),
    ActionType.PROMPT_TUNE: PromptTuneAction(),
    ActionType.PARAM_TUNE: ParamTuneAction(),
    ActionType.CODE_FIX: CodeFixAction(),
    ActionType.STEAL_PATROL: StealPatrolAction(),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/evolution/test_actions.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/evolution/actions.py tests/evolution/test_actions.py
git commit -m "feat(evolution): 6 action types with execute + rollback"
```

---

### Task 4: EvolutionEngine — The Core Loop

**Files:**
- Create: `src/evolution/loop.py`
- Create: `tests/evolution/test_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/evolution/test_loop.py
"""Tests for EvolutionEngine — the core detect→classify→act→evaluate→learn loop."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.evolution.loop import EvolutionEngine, CycleResult
from src.evolution.risk import RiskLevel, ActionType, ClassificationResult
from src.evolution.actions import ActionResult, ActionStatus
from src.proactive.signals import Signal


def _make_signal(sid="S1", tier="A", severity="high"):
    return Signal(id=sid, tier=tier, title="test", severity=severity, data={"collector": "git"})


@pytest.fixture
def engine():
    db = MagicMock()
    db.log_evolution = MagicMock(return_value=1)
    db.get_evolution_history = MagicMock(return_value=[])
    channel_registry = MagicMock()
    return EvolutionEngine(db=db, channel_registry=channel_registry)


class TestRunCycle:
    def test_no_signals_returns_empty(self, engine):
        with patch.object(engine._detector, "detect_all", return_value=[]):
            results = engine.run_cycle()
        assert results == []

    def test_actionable_signal_gets_processed(self, engine):
        sig = _make_signal("S1")
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].signal_id == "S1"
        assert results[0].action_type == ActionType.COLLECTOR_HEAL
        # AUTO level: should have been executed
        assert results[0].executed

    def test_informational_signal_skipped(self, engine):
        sig = _make_signal("S6", tier="C", severity="low")  # late night, no action
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert results == []  # S6 has no routing, so no cycle result

    def test_block_signal_not_executed(self, engine):
        sig = _make_signal("S2", tier="A", severity="high")  # container health → BLOCK
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].risk == RiskLevel.BLOCK
        assert not results[0].executed  # BLOCK = not auto-executed

    def test_review_signal_executed_and_notified(self, engine):
        sig = _make_signal("S4", tier="A", severity="high")  # governor fail → REVIEW
        with patch.object(engine._detector, "detect_all", return_value=[sig]):
            results = engine.run_cycle()
        assert len(results) == 1
        assert results[0].risk == RiskLevel.REVIEW
        assert results[0].executed
        # Notification should have been sent
        engine._channel_registry.broadcast.assert_called()

    def test_failed_action_logged(self, engine):
        sig = _make_signal("S1")
        with patch.object(engine._detector, "detect_all", return_value=[sig]), \
             patch("src.evolution.actions.run_collectors", side_effect=Exception("broken")):
            results = engine.run_cycle()
        assert len(results) == 1
        # Should still be logged
        engine._db.log_evolution.assert_called()


class TestCycleResult:
    def test_score_delta(self):
        r = CycleResult(
            signal_id="S4", action_type=ActionType.PROMPT_TUNE,
            risk=RiskLevel.REVIEW, executed=True,
            action_status=ActionStatus.SUCCESS,
            score_before=0.82, score_after=0.87,
        )
        assert r.score_delta == pytest.approx(0.05)

    def test_score_delta_none_when_no_scores(self):
        r = CycleResult(
            signal_id="S1", action_type=ActionType.COLLECTOR_HEAL,
            risk=RiskLevel.AUTO, executed=True,
            action_status=ActionStatus.SUCCESS,
        )
        assert r.score_delta is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/evolution/test_loop.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement loop.py**

```python
# src/evolution/loop.py
"""EvolutionEngine — the self-evolution closed loop.

Cycle: Detect signals → Classify risk → Execute action → Evaluate → Learn.

Runs on a schedule (default: every 30 minutes).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from src.channels.base import ChannelMessage
from src.evolution.actions import ACTION_REGISTRY, ActionResult, ActionStatus
from src.evolution.risk import ActionType, ClassificationResult, RiskClassifier, RiskLevel
from src.proactive.signals import Signal, SignalDetector
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Outcome of one signal through the evolution pipeline."""
    signal_id: str
    action_type: ActionType
    risk: RiskLevel
    executed: bool
    action_status: ActionStatus = ActionStatus.SKIPPED
    detail: dict[str, Any] = field(default_factory=dict)
    score_before: float | None = None
    score_after: float | None = None

    @property
    def score_delta(self) -> float | None:
        if self.score_before is not None and self.score_after is not None:
            return self.score_after - self.score_before
        return None


class EvolutionEngine:
    """Orchestrates the detect → classify → act → evaluate → learn loop."""

    def __init__(
        self,
        db: EventsDB,
        channel_registry: Any = None,
        dry_run: bool = False,
    ):
        self._db = db
        self._channel_registry = channel_registry
        self._dry_run = dry_run
        self._detector = SignalDetector(db)

    def run_cycle(self) -> list[CycleResult]:
        """Run one evolution cycle: detect all signals, process actionable ones."""
        signals = self._detector.detect_all()
        if not signals:
            return []

        results: list[CycleResult] = []
        for signal in signals:
            result = self._process_signal(signal)
            if result is not None:
                results.append(result)

        if results:
            log.info(
                f"Evolution cycle: {len(results)} actions "
                f"({sum(1 for r in results if r.executed)} executed, "
                f"{sum(1 for r in results if not r.executed)} blocked/skipped)"
            )
        return results

    def _process_signal(self, signal: Signal) -> Optional[CycleResult]:
        """Process a single signal through classify → act → evaluate → learn."""
        # ── Classify ──
        classification = RiskClassifier.classify(signal)
        if classification is None:
            return None  # Informational signal, no action

        # ── Decide ──
        if classification.risk == RiskLevel.BLOCK:
            self._notify_block(signal, classification)
            self._log_to_db(signal, classification, executed=False)
            return CycleResult(
                signal_id=signal.id,
                action_type=classification.action_type,
                risk=classification.risk,
                executed=False,
                action_status=ActionStatus.SKIPPED,
                detail={"reason": "BLOCK — awaiting owner approval"},
            )

        # ── Act ──
        action = ACTION_REGISTRY.get(classification.action_type)
        if action is None:
            log.warning(f"No action registered for {classification.action_type}")
            return None

        if self._dry_run:
            return CycleResult(
                signal_id=signal.id,
                action_type=classification.action_type,
                risk=classification.risk,
                executed=False,
                action_status=ActionStatus.SKIPPED,
                detail={"reason": "dry_run"},
            )

        action_result = action.execute(self._db, signal.data)

        # ── Evaluate ──
        # For now, evaluation is pass/fail based on ActionResult.
        # Future: integrate ExperimentLedger for before/after scoring.

        # ── Learn ──
        self._log_to_db(
            signal, classification,
            executed=True,
            status=action_result.status.value,
            detail=action_result.detail,
        )

        # ── Notify (REVIEW level) ──
        if classification.risk == RiskLevel.REVIEW:
            self._notify_review(signal, classification, action_result)

        return CycleResult(
            signal_id=signal.id,
            action_type=classification.action_type,
            risk=classification.risk,
            executed=True,
            action_status=action_result.status,
            detail=action_result.detail,
        )

    def _log_to_db(
        self,
        signal: Signal,
        classification: ClassificationResult,
        executed: bool,
        status: str = "blocked",
        detail: dict | None = None,
        score_before: float | None = None,
        score_after: float | None = None,
    ) -> None:
        try:
            self._db.log_evolution(
                signal_id=signal.id,
                action_type=classification.action_type.value,
                risk_level=classification.risk.value,
                status=status if executed else "blocked",
                detail=detail,
                score_before=score_before,
                score_after=score_after,
            )
        except Exception as e:
            log.warning(f"Failed to log evolution: {e}")

    def _notify_review(
        self,
        signal: Signal,
        classification: ClassificationResult,
        action_result: ActionResult,
    ) -> None:
        if not self._channel_registry:
            return
        emoji = "✅" if action_result.is_success else "❌"
        text = (
            f"[进化] {emoji} {classification.action_type.value}\n"
            f"触发: {signal.title}\n"
            f"结果: {action_result.status.value}"
        )
        try:
            self._channel_registry.broadcast(ChannelMessage(
                text=text,
                event_type="evolution.review",
                priority="NORMAL",
                department="evolution",
            ))
        except Exception as e:
            log.warning(f"Failed to send evolution notification: {e}")

    def _notify_block(
        self,
        signal: Signal,
        classification: ClassificationResult,
    ) -> None:
        if not self._channel_registry:
            return
        text = (
            f"[审批] 🔒 {classification.action_type.value}\n"
            f"触发: {signal.title}\n"
            f"原因: {classification.reason}\n"
            f"需要你确认后才能执行"
        )
        try:
            self._channel_registry.broadcast(ChannelMessage(
                text=text,
                event_type="evolution.block",
                priority="CRITICAL",
                department="evolution",
            ))
        except Exception as e:
            log.warning(f"Failed to send evolution block notification: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/evolution/test_loop.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/evolution/loop.py tests/evolution/test_loop.py
git commit -m "feat(evolution): EvolutionEngine — detect→classify→act→evaluate→learn loop"
```

---

### Task 5: Scheduler Wiring + Job Entry Points

**Files:**
- Create: `src/jobs/evolution_jobs.py`
- Modify: `src/scheduler.py:60-63`

- [ ] **Step 1: Create evolution_jobs.py entry points**

```python
# src/jobs/evolution_jobs.py
"""Evolution loop job entry points — thin wrappers for scheduler registration."""
from __future__ import annotations

import logging

from src.evolution.loop import EvolutionEngine
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

# Module-level singleton — keeps state between cycles
_engine: EvolutionEngine | None = None


def _get_registry():
    """Lazy import to avoid circular dependency."""
    try:
        from src.channels.registry import get_channel_registry
        return get_channel_registry()
    except Exception:
        return None


def _get_engine(db: EventsDB) -> EvolutionEngine:
    global _engine
    if _engine is None:
        _engine = EvolutionEngine(db=db, channel_registry=_get_registry())
    return _engine


def evolution_cycle(db: EventsDB) -> None:
    """Run one evolution cycle (detect → classify → act → evaluate → learn)."""
    engine = _get_engine(db)
    results = engine.run_cycle()
    if results:
        executed = sum(1 for r in results if r.executed)
        blocked = sum(1 for r in results if not r.executed)
        db.write_log(
            f"Evolution cycle: {len(results)} signals → {executed} executed, {blocked} blocked",
            "INFO", "evolution",
        )


def steal_patrol(db: EventsDB) -> None:
    """Weekly steal patrol — scan watchlist repos for new patterns."""
    from src.evolution.actions import StealPatrolAction
    action = StealPatrolAction()
    result = action.execute(db, signal_data={})
    if result.detail:
        db.write_log(
            f"Steal patrol: {result.status.value} — {result.detail}",
            "INFO", "evolution",
        )
```

- [ ] **Step 2: Register jobs in scheduler.py**

Add after the proactive_weekly line (line 63), before the Agent Cron section:

```python
    # ── Evolution Loop ──
    from src.jobs.evolution_jobs import evolution_cycle, steal_patrol
    s.add_job(lambda: run_job("evolution_cycle", evolution_cycle, db), "interval", minutes=30, id="evolution_cycle")
    s.add_job(lambda: run_job("steal_patrol", steal_patrol, db), "cron", day_of_week="wed", hour=14, timezone="Asia/Shanghai", id="steal_patrol")
```

- [ ] **Step 3: Update scheduler log message**

Append `，进化循环：每30分钟，偷师巡查：每周三14:00` to the log string at line 135.

- [ ] **Step 4: Verify scheduler loads without error**

Run: `python -c "from src.jobs.evolution_jobs import evolution_cycle, steal_patrol; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/jobs/evolution_jobs.py src/scheduler.py
git commit -m "feat(evolution): wire Evolution Loop into scheduler (30min cycle + weekly patrol)"
```

---

### Task 6: Integration Test — Full Cycle End-to-End

**Files:**
- Create: `tests/evolution/test_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/evolution/test_integration.py
"""Integration test — full evolution cycle with real DB."""
import pytest
from src.storage.events_db import EventsDB
from src.evolution.loop import EvolutionEngine
from src.evolution.risk import RiskLevel, ActionType
from unittest.mock import MagicMock, patch
from src.proactive.signals import Signal


@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))


def test_full_cycle_collector_heal(db):
    """S1 signal → AUTO → CollectorHeal → logged to evolution_log."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signal = Signal(
        id="S1", tier="A", title="git collector failing",
        severity="high", data={"collector": "git", "count": 3, "error": "path not found"},
    )

    with patch.object(engine._detector, "detect_all", return_value=[signal]), \
         patch("src.evolution.actions.run_collectors"):
        results = engine.run_cycle()

    assert len(results) == 1
    r = results[0]
    assert r.signal_id == "S1"
    assert r.action_type == ActionType.COLLECTOR_HEAL
    assert r.risk == RiskLevel.AUTO
    assert r.executed

    # Verify logged to DB
    history = db.get_evolution_history(limit=10)
    assert len(history) >= 1
    assert history[0]["signal_id"] == "S1"
    assert history[0]["action_type"] == "collector_heal"
    assert history[0]["risk_level"] == "AUTO"
    assert history[0]["status"] == "success"


def test_full_cycle_block_not_executed(db):
    """S2 signal → BLOCK → not executed, logged as blocked."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signal = Signal(
        id="S2", tier="A", title="container unhealthy",
        severity="high", data={"name": "orchestrator", "status": "exited"},
    )

    with patch.object(engine._detector, "detect_all", return_value=[signal]):
        results = engine.run_cycle()

    assert len(results) == 1
    assert not results[0].executed

    history = db.get_evolution_history(limit=10)
    assert history[0]["status"] == "blocked"


def test_full_cycle_multiple_signals(db):
    """Multiple signals in one cycle — each processed independently."""
    engine = EvolutionEngine(db=db, channel_registry=MagicMock())

    signals = [
        Signal(id="S1", tier="A", title="collector fail", severity="high",
               data={"collector": "git", "count": 3, "error": "x"}),
        Signal(id="S3", tier="B", title="db large", severity="medium",
               data={"size_mb": 55, "delta_mb": 5}),
        Signal(id="S6", tier="C", title="late night", severity="low", data={}),
    ]

    with patch.object(engine._detector, "detect_all", return_value=signals), \
         patch("src.evolution.actions.run_collectors"), \
         patch("src.evolution.actions.run_cull") as mock_cull:
        mock_cull.return_value = MagicMock(
            retired=[], at_risk=[], promoted=[], total_active=40,
            format=MagicMock(return_value="ok"),
        )
        results = engine.run_cycle()

    # S1 → AUTO executed, S3 → AUTO executed, S6 → no routing (skipped)
    assert len(results) == 2
    assert {r.signal_id for r in results} == {"S1", "S3"}
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/evolution/test_integration.py -v`
Expected: 3 tests PASS

- [ ] **Step 3: Run all evolution tests together**

Run: `python -m pytest tests/evolution/ -v`
Expected: All tests PASS (15+ tests across 4 files)

- [ ] **Step 4: Commit**

```bash
git add tests/evolution/test_integration.py
git commit -m "test(evolution): integration tests — full cycle end-to-end"
```

---

### Task 7: Dashboard API Endpoint (Optional)

**Files:**
- Modify: `dashboard/server.js` (add `/api/evolution` route)

- [ ] **Step 1: Add API route**

Add a new route to `dashboard/server.js` that queries `evolution_log`:

```javascript
app.get('/api/evolution', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 50;
    const rows = db.prepare(
      'SELECT * FROM evolution_log ORDER BY created_at DESC LIMIT ?'
    ).all(limit);
    res.json(rows);
  } catch (e) {
    res.json([]);
  }
});
```

- [ ] **Step 2: Verify endpoint**

Run: `curl http://localhost:23714/api/evolution?limit=5`
Expected: JSON array (empty initially)

- [ ] **Step 3: Commit**

```bash
git add dashboard/server.js
git commit -m "feat(dashboard): add /api/evolution endpoint"
```

---

## Summary

| Task | What It Builds | New Files | Tests |
|------|---------------|-----------|-------|
| 1 | evolution_log table + DB mixin | 2 create, 2 modify | 3 |
| 2 | RiskClassifier (signal → risk + action) | 2 create | 7 |
| 3 | 6 Action types with execute/rollback | 1 create | 5 |
| 4 | EvolutionEngine core loop | 1 create | 7 |
| 5 | Scheduler wiring | 1 create, 1 modify | 1 (smoke) |
| 6 | Integration tests | 1 create | 3 |
| 7 | Dashboard API (optional) | 1 modify | 1 |
| **Total** | | **8 create, 3 modify** | **~27 tests** |

Estimated new code: ~500 lines production + ~300 lines test.

Dependencies between tasks: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 (strictly sequential — each builds on the previous).
