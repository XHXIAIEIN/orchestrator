# P0 Steal Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 4 highest-value patterns stolen from 19-project analysis: StuckDetector, Compaction Recovery, Condenser Pipeline, and EventStream typing.

**Architecture:** Incremental upgrades to existing governance pipeline. Each task is independently deployable — no big-bang migration. StuckDetector plugs into executor's doom loop. Compaction recovery uses existing hook system. Condenser adds a new module. EventStream typing is a gradual migration from flat JSONL to typed events.

**Tech Stack:** Python 3.12, SQLite (events.db), Agent SDK, bash hooks

**Scope Decision:** EventStream full migration is a multi-session project. This plan covers Phase 1 only: type definitions + StuckDetector + Condenser core. Full pub-sub migration is a separate plan.

---

## File Structure

```
src/governance/
├── stuck_detector.py          (CREATE) — 5-pattern stuck detection
├── condenser/
│   ├── __init__.py            (CREATE) — exports
│   ├── base.py                (CREATE) — Condenser ABC + View
│   ├── recent_events.py       (CREATE) — keep last N events
│   ├── amortized_forgetting.py (CREATE) — drop middle, keep head+tail
│   ├── llm_summarizing.py     (CREATE) — LLM-based compression
│   └── pipeline.py            (CREATE) — chain condensers
├── events/
│   ├── __init__.py            (CREATE) — exports
│   ├── types.py               (CREATE) — Action/Observation type hierarchy
│   └── stream.py              (CREATE) — EventStream with pub-sub (Phase 1: write-only)
├── executor.py                (MODIFY:265-274) — integrate StuckDetector
├── review.py                  (MODIFY:125-255) — emit typed events
src/storage/
├── events_db.py               (MODIFY) — add condenser_snapshots table
.claude/hooks/
├── pre-compact.sh             (CREATE) — save state before compaction
├── session-start.sh           (MODIFY) — restore compaction snapshot
```

---

### Task 1: StuckDetector — 5-pattern agent stuck detection

**Files:**
- Create: `src/governance/stuck_detector.py`
- Modify: `src/governance/executor.py:265-274` (replace inline doom loop check)

**Why:** Currently executor only has a basic doom loop check every 5 turns. OpenHands detects 5 distinct stuck patterns. This is a drop-in replacement.

- [ ] **Step 1: Create stuck_detector.py with 5 detection patterns**

```python
# src/governance/stuck_detector.py
"""
StuckDetector — 5-pattern agent stuck detection.
Stolen from OpenHands/openhands/controller/stuck.py, adapted for Agent SDK events.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# Minimum events before detection kicks in
MIN_EVENTS = 6
# How many recent events to compare
WINDOW = 4


class StuckDetector:
    """Detect when an agent is stuck in a loop.

    Five patterns:
    1. REPEATED_ACTION_OBSERVATION — same action+observation pair repeats
    2. REPEATED_ACTION_ERROR — same action keeps producing same error
    3. MONOLOGUE — agent talks to itself without tool use
    4. ACTION_OBSERVATION_CYCLE — alternating pattern repeats
    5. CONTEXT_WINDOW_LOOP — keeps hitting context limit errors
    """

    def __init__(self, window: int = WINDOW):
        self.window = window
        self._events: list[dict] = []

    def record(self, event: dict) -> None:
        """Record an agent event (from agent_events table format)."""
        self._events.append(event)

    def is_stuck(self) -> tuple[bool, str]:
        """Check if agent is stuck. Returns (is_stuck, pattern_name)."""
        if len(self._events) < MIN_EVENTS:
            return False, ""

        recent = self._events[-self.window * 2:]

        # Pattern 1: Repeated action+observation
        if self._check_repeated_action_observation(recent):
            return True, "REPEATED_ACTION_OBSERVATION"

        # Pattern 2: Repeated action+error
        if self._check_repeated_action_error(recent):
            return True, "REPEATED_ACTION_ERROR"

        # Pattern 3: Monologue (no tool use for N turns)
        if self._check_monologue(recent):
            return True, "MONOLOGUE"

        # Pattern 4: Action-observation cycle
        if self._check_cycle(recent):
            return True, "ACTION_OBSERVATION_CYCLE"

        # Pattern 5: Context window errors
        if self._check_context_window_loop(recent):
            return True, "CONTEXT_WINDOW_LOOP"

        return False, ""

    def _check_repeated_action_observation(self, events: list[dict]) -> bool:
        """Same tool call + same output repeating."""
        signatures = []
        for e in events:
            data = e.get("data", {})
            tools = tuple(sorted(data.get("tools", [])))
            text = data.get("text", [""])
            sig = (tools, str(text)[:200])
            signatures.append(sig)
        if len(signatures) < 3:
            return False
        return len(set(signatures[-3:])) == 1

    def _check_repeated_action_error(self, events: list[dict]) -> bool:
        """Same tool keeps producing same error."""
        errors = []
        for e in events:
            data = e.get("data", {})
            err = data.get("error")
            if err:
                tools = tuple(sorted(data.get("tools", [])))
                errors.append((tools, str(err)[:200]))
        if len(errors) < 3:
            return False
        return len(set(errors[-3:])) == 1

    def _check_monologue(self, events: list[dict]) -> bool:
        """Agent produces text without any tool calls for 4+ turns."""
        no_tool_count = 0
        for e in reversed(events):
            data = e.get("data", {})
            if data.get("tools"):
                break
            no_tool_count += 1
        return no_tool_count >= self.window

    def _check_cycle(self, events: list[dict]) -> bool:
        """A-B-A-B pattern detection."""
        if len(events) < 4:
            return False
        sigs = []
        for e in events[-4:]:
            data = e.get("data", {})
            tools = tuple(sorted(data.get("tools", [])))
            sigs.append(tools)
        return sigs[0] == sigs[2] and sigs[1] == sigs[3] and sigs[0] != sigs[1]

    def _check_context_window_loop(self, events: list[dict]) -> bool:
        """Repeated context window / token limit errors."""
        ctx_errors = 0
        for e in events[-self.window:]:
            data = e.get("data", {})
            err = str(data.get("error", "")).lower()
            if any(kw in err for kw in ("context", "token", "too long", "maximum")):
                ctx_errors += 1
        return ctx_errors >= 2

    def reset(self) -> None:
        """Clear recorded events."""
        self._events.clear()
```

- [ ] **Step 2: Integrate into executor.py — replace doom loop check**

In `src/governance/executor.py`, find the doom loop check section (~L265-274) and replace with StuckDetector integration.

The current code checks every 5 turns with a simple counter. Replace with:

```python
# At top of _run_agent_session, after variable init:
from src.governance.stuck_detector import StuckDetector
detector = StuckDetector()

# Inside the AssistantMessage handler, after recording agent_event:
detector.record({"data": {"tools": tool_names, "text": text_parts, "error": error_text}})

# Replace the existing doom loop check block with:
if turn_count > 0 and turn_count % 3 == 0:  # Check every 3 turns (was 5)
    stuck, pattern = detector.is_stuck()
    if stuck:
        log.warning(f"StuckDetector: task #{task_id} stuck — {pattern}")
        self.db.add_agent_event(task_id, "stuck_detected", {
            "pattern": pattern, "turn": turn_count
        })
        result_text = f"[STUCK: {pattern}] Agent detected in loop after {turn_count} turns"
        break
```

- [ ] **Step 3: Commit**

```bash
git add src/governance/stuck_detector.py src/governance/executor.py
git commit -m "feat(governance): add StuckDetector with 5-pattern loop detection

Replaces simple doom loop counter with OpenHands-inspired StuckDetector:
- REPEATED_ACTION_OBSERVATION: same tool+output repeating
- REPEATED_ACTION_ERROR: same tool keeps erroring identically
- MONOLOGUE: agent talks without tool use 4+ turns
- ACTION_OBSERVATION_CYCLE: A-B-A-B pattern
- CONTEXT_WINDOW_LOOP: repeated context limit errors

Checks every 3 turns instead of 5 for faster detection."
```

---

### Task 2: Condenser Pipeline — context compression strategies

**Files:**
- Create: `src/governance/condenser/__init__.py`
- Create: `src/governance/condenser/base.py`
- Create: `src/governance/condenser/recent_events.py`
- Create: `src/governance/condenser/amortized_forgetting.py`
- Create: `src/governance/condenser/pipeline.py`

**Why:** No context compression exists. Long-running tasks or multi-turn agents accumulate events until context window overflows. OpenHands has 9 strategies; we implement the 3 most useful ones first.

- [ ] **Step 1: Create base.py with Condenser ABC and View**

```python
# src/governance/condenser/base.py
"""Condenser base classes. Inspired by OpenHands condenser architecture."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Event:
    """Minimal typed event for condenser processing."""
    id: int
    event_type: str  # "action" | "observation" | "system"
    source: str      # "agent" | "user" | "environment"
    content: str
    metadata: dict = field(default_factory=dict)
    condensed: bool = False


class View:
    """Immutable view over an event list. Condensers produce new Views."""

    def __init__(self, events: list[Event]):
        self._events = list(events)

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def token_estimate(self) -> int:
        """Rough token estimate (~1.3 tokens per word)."""
        total_chars = sum(len(e.content) for e in self._events)
        return int(total_chars / 3.5)


class Condenser(ABC):
    """Abstract condenser. Takes a View, returns a compressed View."""

    @abstractmethod
    def condense(self, view: View) -> View:
        ...
```

- [ ] **Step 2: Create recent_events.py**

```python
# src/governance/condenser/recent_events.py
"""Keep only the most recent N events."""
from .base import Condenser, View


class RecentEventsCondenser(Condenser):
    def __init__(self, max_events: int = 50):
        self.max_events = max_events

    def condense(self, view: View) -> View:
        if len(view) <= self.max_events:
            return view
        return View(view.events[-self.max_events:])
```

- [ ] **Step 3: Create amortized_forgetting.py**

```python
# src/governance/condenser/amortized_forgetting.py
"""Drop middle events, keep head (instructions) and tail (recent context)."""
from .base import Condenser, View


class AmortizedForgettingCondenser(Condenser):
    def __init__(self, max_events: int = 100, keep_head: int = 10, keep_tail: int = 30):
        self.max_events = max_events
        self.keep_head = keep_head
        self.keep_tail = keep_tail

    def condense(self, view: View) -> View:
        if len(view) <= self.max_events:
            return view
        events = view.events
        head = events[:self.keep_head]
        tail = events[-self.keep_tail:]
        # Mark gap
        from .base import Event
        gap = Event(
            id=-1, event_type="system", source="condenser",
            content=f"[{len(events) - self.keep_head - self.keep_tail} events condensed]",
            condensed=True,
        )
        return View(head + [gap] + tail)
```

- [ ] **Step 4: Create pipeline.py**

```python
# src/governance/condenser/pipeline.py
"""Chain multiple condensers into a pipeline."""
from .base import Condenser, View


class CondenserPipeline(Condenser):
    def __init__(self, condensers: list[Condenser]):
        self.condensers = condensers

    def condense(self, view: View) -> View:
        for c in self.condensers:
            view = c.condense(view)
        return view
```

- [ ] **Step 5: Create __init__.py**

```python
# src/governance/condenser/__init__.py
from .base import Condenser, View, Event
from .recent_events import RecentEventsCondenser
from .amortized_forgetting import AmortizedForgettingCondenser
from .pipeline import CondenserPipeline

__all__ = [
    "Condenser", "View", "Event",
    "RecentEventsCondenser",
    "AmortizedForgettingCondenser",
    "CondenserPipeline",
]
```

- [ ] **Step 6: Commit**

```bash
git add src/governance/condenser/
git commit -m "feat(condenser): add context compression pipeline with 2 strategies

OpenHands-inspired condenser architecture:
- View: immutable event list with token estimation
- RecentEventsCondenser: keep last N events
- AmortizedForgettingCondenser: drop middle, keep head+tail
- CondenserPipeline: chain multiple condensers

Phase 1: standalone module, not yet integrated into executor."
```

---

### Task 3: Event Type System — typed Action/Observation hierarchy

**Files:**
- Create: `src/governance/events/__init__.py`
- Create: `src/governance/events/types.py`

**Why:** Current agent_events use untyped dicts with string event_type. Adding a type hierarchy enables StuckDetector, Condenser, and future EventStream to work with structured data. This is Phase 1 — define types only, no migration.

- [ ] **Step 1: Create types.py**

```python
# src/governance/events/types.py
"""Typed event hierarchy for governance pipeline.

Phase 1: Type definitions only. Existing code continues using dicts.
New code can use these types for better structure.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventSource(Enum):
    AGENT = "agent"
    USER = "user"
    GOVERNOR = "governor"
    SCRUTINY = "scrutiny"
    REVIEW = "review"
    SYSTEM = "system"


@dataclass
class GovernanceEvent:
    """Base event for all governance pipeline events."""
    task_id: int
    source: EventSource
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cause_event_id: int | None = None  # causal link to triggering event

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v is not None}
        if isinstance(d.get("source"), EventSource):
            d["source"] = d["source"].value
        d["event_class"] = self.__class__.__name__
        return d


# ── Actions (things that happen TO the system) ──

@dataclass
class TaskCreated(GovernanceEvent):
    action: str = ""
    department: str = ""
    priority: str = "medium"
    cognitive_mode: str = ""


@dataclass
class TaskDispatched(GovernanceEvent):
    complexity: str = ""
    scrutiny_result: str = ""
    learnings_injected: int = 0


@dataclass
class AgentTurn(GovernanceEvent):
    turn: int = 0
    tools: list[str] = field(default_factory=list)
    thinking_preview: str = ""
    text_preview: str = ""
    error: str | None = None


@dataclass
class AgentResult(GovernanceEvent):
    status: str = ""  # done | failed | stuck
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    output_preview: str = ""


@dataclass
class StuckDetected(GovernanceEvent):
    pattern: str = ""  # from StuckDetector
    turn: int = 0


# ── Observations (results from the system) ──

@dataclass
class ScrutinyVerdict(GovernanceEvent):
    approved: bool = False
    note: str = ""
    blast_radius: str = ""
    second_opinion: bool = False


@dataclass
class QualityVerdict(GovernanceEvent):
    passed: bool = False
    critical_count: int = 0
    high_count: int = 0
    summary: str = ""


@dataclass
class ReworkDispatched(GovernanceEvent):
    original_task_id: int = 0
    rework_count: int = 0
    feedback_preview: str = ""


@dataclass
class TaskEscalated(GovernanceEvent):
    reason: str = ""
    rework_count: int = 0


# ── System Events ──

@dataclass
class LearningRecorded(GovernanceEvent):
    pattern_key: str = ""
    rule: str = ""
    recurrence: int = 1


@dataclass
class ContextCondensed(GovernanceEvent):
    strategy: str = ""
    events_before: int = 0
    events_after: int = 0
    tokens_saved: int = 0
```

- [ ] **Step 2: Create __init__.py**

```python
# src/governance/events/__init__.py
from .types import (
    EventSource, GovernanceEvent,
    TaskCreated, TaskDispatched, AgentTurn, AgentResult, StuckDetected,
    ScrutinyVerdict, QualityVerdict, ReworkDispatched, TaskEscalated,
    LearningRecorded, ContextCondensed,
)

__all__ = [
    "EventSource", "GovernanceEvent",
    "TaskCreated", "TaskDispatched", "AgentTurn", "AgentResult", "StuckDetected",
    "ScrutinyVerdict", "QualityVerdict", "ReworkDispatched", "TaskEscalated",
    "LearningRecorded", "ContextCondensed",
]
```

- [ ] **Step 3: Commit**

```bash
git add src/governance/events/
git commit -m "feat(events): add typed event hierarchy for governance pipeline

Phase 1 of EventStream migration — type definitions only:
- EventSource enum (AGENT/USER/GOVERNOR/SCRUTINY/REVIEW/SYSTEM)
- GovernanceEvent base with task_id, source, timestamp, cause linking
- Action types: TaskCreated, TaskDispatched, AgentTurn, AgentResult, StuckDetected
- Observation types: ScrutinyVerdict, QualityVerdict, ReworkDispatched, TaskEscalated
- System types: LearningRecorded, ContextCondensed

No migration — existing dict-based code untouched. New code can import these types."
```

---

### Task 4: Compaction Recovery Hooks

**Files:**
- Create: `.claude/hooks/pre-compact.sh`
- Modify: `.claude/hooks/session-start.sh` — add snapshot restore

**Why:** Claude Code's auto-compaction silently drops context. pilot-shell's PreCompact → SessionStart recovery pattern prevents losing critical task state.

- [ ] **Step 1: Create pre-compact.sh**

```bash
#!/usr/bin/env bash
# Hook: PreCompact — save critical context before Claude Code compacts
# Triggered by Claude Code before context compression

SNAPSHOT_DIR="tmp/compaction-snapshots"
mkdir -p "$SNAPSHOT_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SNAPSHOT_FILE="$SNAPSHOT_DIR/snapshot-$TIMESTAMP.md"

# Save current task state from DB
python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB()
tasks = db.get_running_tasks()
if tasks:
    print('## Active Tasks at Compaction')
    for t in tasks:
        print(f'- #{t[\"id\"]}: {t[\"action\"][:100]} [{t[\"status\"]}]')
    print()

recent = db.get_logs(limit=10)
if recent:
    print('## Recent Governor Logs')
    for l in recent:
        print(f'- [{l[\"level\"]}] {l[\"message\"][:150]}')
" > "$SNAPSHOT_FILE" 2>/dev/null

if [ -s "$SNAPSHOT_FILE" ]; then
    echo "[compaction] Snapshot saved: $SNAPSHOT_FILE"
else
    rm -f "$SNAPSHOT_FILE"
fi
```

- [ ] **Step 2: Add restore logic to session-start.sh**

Append to existing session-start.sh, after the current status output:

```bash
# ── Compaction Recovery ──
SNAPSHOT_DIR="tmp/compaction-snapshots"
if [ -d "$SNAPSHOT_DIR" ]; then
    LATEST=$(ls -t "$SNAPSHOT_DIR"/snapshot-*.md 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        AGE_SECONDS=$(( $(date +%s) - $(stat -c %Y "$LATEST" 2>/dev/null || echo 0) ))
        if [ "$AGE_SECONDS" -lt 600 ]; then  # Less than 10 minutes old
            echo "[recovery] Recent compaction snapshot found (${AGE_SECONDS}s ago):"
            cat "$LATEST"
            echo "---"
        fi
    fi
fi
```

- [ ] **Step 3: Register hook in settings**

Add to `.claude/settings.json` (or `settings.local.json`) the PreCompact hook event if not already present.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/pre-compact.sh .claude/hooks/session-start.sh
git commit -m "feat(hooks): add compaction recovery — save/restore context snapshots

pilot-shell-inspired pattern:
- pre-compact.sh: saves active tasks + recent logs before Claude compacts
- session-start.sh: restores snapshot if less than 10 minutes old

Prevents losing critical task context during auto-compaction."
```

---

## Execution Order

1. **Task 1 (StuckDetector)** — standalone, zero dependencies, immediate value
2. **Task 3 (Event Types)** — type definitions only, no integration needed
3. **Task 2 (Condenser)** — standalone module, uses Event types from Task 3
4. **Task 4 (Compaction Recovery)** — hooks, independent of code changes

Tasks 1+3 can run in parallel. Tasks 2+4 can run in parallel after Task 3.

## Future Work (separate plans)

- **EventStream Phase 2**: Replace `add_agent_event()` calls with typed events + pub-sub
- **LLMSummarizingCondenser**: Requires LLM integration, separate task
- **Condenser integration into executor**: Wire condenser into `_run_agent_session()` loop
- **P1 patterns**: Phase rollback, confidence scoring, attention decay, etc.
