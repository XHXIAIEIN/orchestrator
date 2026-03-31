# Context Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Governor sub-agents the same context access as the main Claude process through a DB-backed progressive disclosure system.

**Architecture:** New `context_store` table in EventsDB, written by a `ContextWriter` before dispatch and read on-demand by sub-agents via a `ctx_read` CLI tool. 4-layer progressive disclosure (L0 always injected, L1-L3 pulled by agent). 3-tier task pricing controls budget.

**Tech Stack:** Python 3.14, SQLite (EventsDB), pytest, Agent SDK

**Spec:** `docs/superpowers/specs/2026-03-31-context-parity-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/storage/_context_mixin.py` | DB mixin: context_store CRUD |
| Modify | `src/storage/_schema.py` | Add context_store DDL |
| Modify | `src/storage/events_db.py` | Mix in ContextMixin |
| Create | `src/governance/context/writer.py` | ContextWriter: populate context_store before dispatch |
| Create | `src/governance/context/tiers.py` | TaskTier dataclass + classify_task_tier() |
| Create | `scripts/ctx_read.py` | CLI tool for sub-agents to read context |
| Modify | `src/governance/executor_prompt.py` | Inject L0 + ctx_read instructions |
| Modify | `src/governance/executor.py` | Call ContextWriter pre-execution, store chain output post-execution |
| Modify | `scripts/dispatch.py` | Add --tier flag, pass session_id |
| Create | `tests/storage/test_context_mixin.py` | Tests for context_store CRUD |
| Create | `tests/governance/test_context_writer.py` | Tests for ContextWriter |
| Create | `tests/governance/test_task_tiers.py` | Tests for tier classification |
| Create | `tests/test_ctx_read.py` | Tests for ctx_read CLI |

---

### Task 1: Context Store DB Layer

**Files:**
- Create: `src/storage/_context_mixin.py`
- Modify: `src/storage/_schema.py`
- Modify: `src/storage/events_db.py`
- Create: `tests/storage/test_context_mixin.py`

- [ ] **Step 1: Write failing tests for context CRUD**

```python
# tests/storage/test_context_mixin.py
"""Tests for context_store DB operations."""
import pytest
from src.storage.events_db import EventsDB

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))

class TestContextStore:
    def test_upsert_and_get(self, db):
        db.upsert_context("sess-1", layer=0, key="identity:briefing",
                          content="You are Orchestrator.", token_est=10)
        row = db.get_context("sess-1", "identity:briefing")
        assert row is not None
        assert row["content"] == "You are Orchestrator."
        assert row["layer"] == 0
        assert row["token_est"] == 10

    def test_upsert_overwrites(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "v1", 5)
        db.upsert_context("sess-1", 0, "identity:briefing", "v2", 6)
        row = db.get_context("sess-1", "identity:briefing")
        assert row["content"] == "v2"
        assert row["token_est"] == 6

    def test_list_keys_by_session(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "brief", 10)
        db.upsert_context("sess-1", 1, "session:state", "state", 50)
        db.upsert_context("sess-2", 0, "identity:briefing", "other", 10)
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 2
        assert keys[0]["key"] == "identity:briefing"

    def test_get_context_by_layer(self, db):
        db.upsert_context("sess-1", 0, "identity:briefing", "brief", 10)
        db.upsert_context("sess-1", 1, "session:state", "state", 50)
        db.upsert_context("sess-1", 2, "file:main.py", "code", 200)
        rows = db.get_context_by_layer("sess-1", layer=1)
        assert len(rows) == 1
        assert rows[0]["key"] == "session:state"

    def test_get_context_total_tokens(self, db):
        db.upsert_context("sess-1", 0, "a", "x", 100)
        db.upsert_context("sess-1", 1, "b", "y", 200)
        total = db.get_context_total_tokens("sess-1")
        assert total == 300

    def test_delete_session_context(self, db):
        db.upsert_context("sess-1", 0, "a", "x", 10)
        db.upsert_context("sess-1", 1, "b", "y", 20)
        db.delete_context_session("sess-1")
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 0

    def test_delete_expired(self, db):
        db.upsert_context("sess-1", 2, "old", "data", 10,
                          expires_at="2020-01-01T00:00:00")
        db.upsert_context("sess-1", 0, "fresh", "data", 10)
        db.delete_expired_context()
        keys = db.list_context_keys("sess-1")
        assert len(keys) == 1
        assert keys[0]["key"] == "fresh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/storage/test_context_mixin.py -v`
Expected: FAIL — `AttributeError: 'EventsDB' object has no attribute 'upsert_context'`

- [ ] **Step 3: Add context_store DDL to schema**

```python
# src/storage/_schema.py — append to TABLE_DDL string, before the closing """

CREATE TABLE IF NOT EXISTS context_store (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    layer       INTEGER NOT NULL CHECK (layer BETWEEN 0 AND 3),
    key         TEXT NOT NULL,
    content     TEXT NOT NULL,
    token_est   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    UNIQUE(session_id, key)
);
CREATE INDEX IF NOT EXISTS idx_context_session_layer ON context_store(session_id, layer);
CREATE INDEX IF NOT EXISTS idx_context_key ON context_store(key);
```

- [ ] **Step 4: Create ContextMixin**

```python
# src/storage/_context_mixin.py
"""Mixin for context_store table operations."""
from datetime import datetime, timezone


class ContextMixin:
    """DB operations for the context_store table (progressive disclosure)."""

    def upsert_context(self, session_id: str, layer: int, key: str,
                       content: str, token_est: int = 0,
                       expires_at: str | None = None):
        if token_est <= 0:
            token_est = max(1, len(content) // 4)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO context_store (session_id, layer, key, content, token_est, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, key) DO UPDATE SET
                    content = excluded.content,
                    token_est = excluded.token_est,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
            """, (session_id, layer, key, content, token_est, now, expires_at))

    def get_context(self, session_id: str, key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM context_store WHERE session_id = ? AND key = ?",
                (session_id, key),
            ).fetchone()
            return dict(row) if row else None

    def get_context_by_layer(self, session_id: str, layer: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM context_store WHERE session_id = ? AND layer = ? ORDER BY key",
                (session_id, layer),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_context_keys(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT layer, key, token_est FROM context_store WHERE session_id = ? ORDER BY layer, key",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_context_total_tokens(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(token_est), 0) as total FROM context_store WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["total"]

    def delete_context_session(self, session_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM context_store WHERE session_id = ?", (session_id,))

    def delete_expired_context(self):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM context_store WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
```

- [ ] **Step 5: Register mixin in EventsDB**

```python
# src/storage/events_db.py — add import and mixin
from src.storage._context_mixin import ContextMixin

class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin, SessionsMixin, WakeMixin, ContextMixin):
    ...
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/storage/test_context_mixin.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/storage/_context_mixin.py src/storage/_schema.py src/storage/events_db.py tests/storage/test_context_mixin.py
git commit -m "feat(storage): add context_store table and ContextMixin for progressive disclosure"
```

---

### Task 2: Task Tier System

**Files:**
- Create: `src/governance/context/tiers.py`
- Create: `tests/governance/test_task_tiers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/governance/test_task_tiers.py
"""Tests for task tier classification and budget control."""
import pytest
from src.governance.context.tiers import TaskTier, TIERS, classify_task_tier

class TestTaskTier:
    def test_tiers_exist(self):
        assert "light" in TIERS
        assert "standard" in TIERS
        assert "heavy" in TIERS

    def test_tier_budgets_ascending(self):
        assert TIERS["light"].context_budget < TIERS["standard"].context_budget
        assert TIERS["standard"].context_budget < TIERS["heavy"].context_budget

    def test_classify_exam_as_heavy(self):
        tier = classify_task_tier("Clawvard practice: understanding", {})
        assert tier.name == "heavy"

    def test_classify_patrol_as_light(self):
        tier = classify_task_tier("check container status", {})
        assert tier.name == "light"

    def test_classify_default_as_standard(self):
        tier = classify_task_tier("fix import error in collector.py", {})
        assert tier.name == "standard"

    def test_spec_tier_override(self):
        tier = classify_task_tier("simple task", {"tier": "heavy"})
        assert tier.name == "heavy"

    def test_classify_analyze_as_heavy(self):
        tier = classify_task_tier("analyze codebase architecture", {})
        assert tier.name == "heavy"

    def test_classify_status_as_light(self):
        tier = classify_task_tier("status check for docker containers", {})
        assert tier.name == "light"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/governance/test_task_tiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.governance.context.tiers'`

- [ ] **Step 3: Implement tiers module**

```python
# src/governance/context/tiers.py
"""Task Tier System — per-task pricing for context budget, model, and turns."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskTier:
    name: str
    context_budget: int    # max tokens for ctx_read
    model: str
    max_turns: int
    prompt_budget: int     # max tokens for L0 prompt injection


TIERS = {
    "light":    TaskTier("light",    4_000,   "haiku",  10, 1_000),
    "standard": TaskTier("standard", 24_000,  "sonnet", 25, 4_000),
    "heavy":    TaskTier("heavy",    128_000, "opus",   50, 16_000),
}

# Keywords that push toward a tier
_HEAVY_KEYWORDS = re.compile(
    r"exam|practice|clawvard|analy[zs]e|refactor.*architect|design.*review|"
    r"threat.model|security.audit|comprehensive",
    re.IGNORECASE,
)
_LIGHT_KEYWORDS = re.compile(
    r"check|status|patrol|ping|health|list|count|简单|查看|巡检",
    re.IGNORECASE,
)


def classify_task_tier(action: str, spec: dict) -> TaskTier:
    """Classify a task into light/standard/heavy tier.

    Priority: spec["tier"] override > keyword match > default (standard).
    """
    # Explicit override
    explicit = spec.get("tier", "")
    if explicit in TIERS:
        return TIERS[explicit]

    # Keyword match
    text = f"{action} {spec.get('problem', '')} {spec.get('summary', '')}"
    if _HEAVY_KEYWORDS.search(text):
        return TIERS["heavy"]
    if _LIGHT_KEYWORDS.search(text):
        return TIERS["light"]

    return TIERS["standard"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/governance/test_task_tiers.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/governance/context/tiers.py tests/governance/test_task_tiers.py
git commit -m "feat(context): add task tier system (light/standard/heavy)"
```

---

### Task 3: ContextWriter

**Files:**
- Create: `src/governance/context/writer.py`
- Create: `tests/governance/test_context_writer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/governance/test_context_writer.py
"""Tests for ContextWriter — populates context_store before dispatch."""
import pytest
from src.storage.events_db import EventsDB
from src.governance.context.writer import ContextWriter

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))

@pytest.fixture
def writer(db):
    return ContextWriter(db, "sess-test")

class TestContextWriter:
    def test_write_layer0_creates_identity(self, writer, db):
        task = {"action": "test task", "spec": {"problem": "test problem"}}
        writer.write_layer0(task, "engineering")
        row = db.get_context("sess-test", "identity:briefing")
        assert row is not None
        assert len(row["content"]) > 0

    def test_write_layer0_creates_catalog(self, writer, db):
        task = {"action": "test task", "spec": {}}
        writer.write_layer0(task, "engineering")
        row = db.get_context("sess-test", "catalog")
        assert row is not None
        assert "ctx_read" in row["content"]

    def test_write_layer1_session_state(self, writer, db):
        writer.write_layer1(conversation_summary="User asked to fix a bug.")
        row = db.get_context("sess-test", "session:conversation_summary")
        assert row["content"] == "User asked to fix a bug."
        assert row["layer"] == 1

    def test_write_layer1_git_diff(self, writer, db):
        writer.write_layer1(git_diff="diff --git a/main.py")
        row = db.get_context("sess-test", "session:git_diff")
        assert "main.py" in row["content"]

    def test_write_chain_output(self, writer, db):
        writer.write_chain_output(42, "task 42 output with nextBatch")
        row = db.get_context("sess-test", "chain:42")
        assert row["content"] == "task 42 output with nextBatch"
        assert row["layer"] == 1

    def test_write_layer2_file(self, writer, db):
        writer.write_file("src/main.py", "print('hello')")
        row = db.get_context("sess-test", "file:src/main.py")
        assert row["layer"] == 2
        assert row["content"] == "print('hello')"

    def test_write_layer2_memory(self, writer, db):
        writer.write_memory("guidelines", "Always use type hints.")
        row = db.get_context("sess-test", "memory:guidelines")
        assert row["layer"] == 2

    def test_catalog_lists_all_keys(self, writer, db):
        writer.write_layer1(conversation_summary="summary here")
        writer.write_file("src/main.py", "code")
        # Rebuild catalog
        writer.write_layer0({"action": "test", "spec": {}}, "engineering")
        catalog = db.get_context("sess-test", "catalog")
        assert "session:conversation_summary" in catalog["content"]
        assert "file:src/main.py" in catalog["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/governance/test_context_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.governance.context.writer'`

- [ ] **Step 3: Implement ContextWriter**

```python
# src/governance/context/writer.py
"""ContextWriter — populates context_store before task dispatch.

Main process (or dispatch pipeline) calls ContextWriter to pre-populate
the DB with context layers. Sub-agents then read on demand via ctx_read.
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

_KEY_LAYER_MAP = {
    "identity:": 0,
    "catalog": 0,
    "session:": 1,
    "chain:": 1,
    "file:": 2,
    "memory:": 2,
    "conversation:": 2,
    "codebase:": 3,
    "history:": 3,
}


def _key_to_layer(key: str) -> int:
    """Derive layer from key prefix."""
    if key == "catalog":
        return 0
    for prefix, layer in _KEY_LAYER_MAP.items():
        if key.startswith(prefix):
            return layer
    return 2  # default to L2


def _load_identity_briefing(dept_key: str) -> str:
    """Load a one-paragraph identity briefing for the department."""
    # Try to read from department SKILL.md
    skill_path = Path(f"departments/{dept_key}/SKILL.md")
    if skill_path.exists():
        text = skill_path.read_text(encoding="utf-8")
        # Take first paragraph (identity section)
        paragraphs = text.split("\n\n")
        return paragraphs[0][:500] if paragraphs else f"Department: {dept_key}"
    return f"You are a sub-agent in the {dept_key} department of the Orchestrator system."


class ContextWriter:
    """Writes context layers to DB before task dispatch."""

    def __init__(self, db: EventsDB, session_id: str):
        self.db = db
        self.session_id = session_id

    def write_layer0(self, task: dict, dept_key: str):
        """Always written. Identity + context catalog."""
        briefing = _load_identity_briefing(dept_key)
        self._upsert("identity:briefing", briefing)
        # Build catalog after all other writes
        catalog = self._build_catalog()
        self._upsert("catalog", catalog)

    def write_layer1(self, conversation_summary: str = "",
                     git_diff: str = "", chain_outputs: dict | None = None):
        """Session state. Written by dispatch pipeline."""
        if conversation_summary:
            self._upsert("session:conversation_summary", conversation_summary)
        if git_diff:
            self._upsert("session:git_diff", git_diff)
        for task_id, output in (chain_outputs or {}).items():
            self._upsert(f"chain:{task_id}", output)

    def write_chain_output(self, task_id: int, output: str):
        """Store a completed task's output for chain continuity."""
        self._upsert(f"chain:{task_id}", output)

    def write_file(self, path: str, content: str):
        """Store file content for agent retrieval."""
        self._upsert(f"file:{path}", content)

    def write_memory(self, category: str, content: str):
        """Store memory entry for agent retrieval."""
        self._upsert(f"memory:{category}", content)

    def write_conversation_full(self, transcript: str, expires_hours: int = 1):
        """Store full conversation transcript (L3, expensive)."""
        from datetime import datetime, timezone, timedelta
        expires = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).isoformat()
        self.db.upsert_context(
            self.session_id, 3, "conversation:full",
            transcript, expires_at=expires,
        )

    def _upsert(self, key: str, content: str):
        layer = _key_to_layer(key)
        self.db.upsert_context(self.session_id, layer, key, content)

    def _build_catalog(self) -> str:
        """List all available context keys for this session."""
        rows = self.db.list_context_keys(self.session_id)
        lines = [
            "## Available Context",
            "Use `python scripts/ctx_read.py --session {session_id} --key <key>` to read.",
            "",
        ]
        current_layer = -1
        for row in rows:
            if row["layer"] != current_layer:
                current_layer = row["layer"]
                lines.append(f"### Layer {current_layer}")
            lines.append(f"  - `{row['key']}` (~{row['token_est']} tokens)")
        if not rows:
            lines.append("  (no context available yet)")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/governance/test_context_writer.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/governance/context/writer.py tests/governance/test_context_writer.py
git commit -m "feat(context): add ContextWriter for pre-dispatch context population"
```

---

### Task 4: ctx_read CLI Tool

**Files:**
- Create: `scripts/ctx_read.py`
- Create: `tests/test_ctx_read.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ctx_read.py
"""Tests for ctx_read CLI — sub-agent context retrieval tool."""
import subprocess
import sys
import pytest
from src.storage.events_db import EventsDB

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = EventsDB(db_path)
    db.upsert_context("sess-1", 0, "identity:briefing", "You are a test agent.", 10)
    db.upsert_context("sess-1", 1, "session:state", '{"practiceId": "prac-123"}', 20)
    db.upsert_context("sess-1", 2, "file:main.py", "print('hello')", 5)
    return db_path

def _run_ctx_read(db_path: str, *args) -> str:
    result = subprocess.run(
        [sys.executable, "scripts/ctx_read.py", "--db", db_path, *args],
        capture_output=True, text=True, cwd=".",
    )
    return result.stdout.strip()

class TestCtxRead:
    def test_read_specific_key(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "identity:briefing")
        assert "You are a test agent." in out

    def test_read_layer(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--layer", "1")
        assert "practiceId" in out

    def test_list_keys(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--list")
        assert "identity:briefing" in out
        assert "session:state" in out
        assert "file:main.py" in out

    def test_missing_key_returns_not_found(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "nonexistent")
        assert "not found" in out.lower()

    def test_budget_tracking(self, db):
        out = _run_ctx_read(db, "--session", "sess-1", "--key", "identity:briefing",
                            "--budget", "5")
        # 10 tokens exceeds budget of 5
        assert "budget" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ctx_read.py -v`
Expected: FAIL — `FileNotFoundError` or script not found

- [ ] **Step 3: Implement ctx_read.py**

```python
# scripts/ctx_read.py
"""ctx_read — CLI tool for sub-agents to read from context_store.

Usage:
    python scripts/ctx_read.py --session <id> --key <key>       # Read specific key
    python scripts/ctx_read.py --session <id> --layer <0-3>     # Read all in layer
    python scripts/ctx_read.py --session <id> --list            # List available keys
    python scripts/ctx_read.py --session <id> --key <k> --budget <N>  # Budget-limited read
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.events_db import EventsDB

_DEFAULT_DB = str(Path(__file__).parent.parent / "data" / "events.db")


def main():
    parser = argparse.ArgumentParser(description="Read context from context_store")
    parser.add_argument("--session", required=True, help="Session ID")
    parser.add_argument("--key", help="Specific context key to read")
    parser.add_argument("--layer", type=int, help="Read all entries in layer (0-3)")
    parser.add_argument("--list", action="store_true", help="List available keys")
    parser.add_argument("--budget", type=int, default=0,
                        help="Max tokens to return (0 = unlimited)")
    parser.add_argument("--db", default=_DEFAULT_DB, help="DB path")
    args = parser.parse_args()

    db = EventsDB(args.db)

    if args.list:
        _list_keys(db, args.session)
    elif args.key:
        _read_key(db, args.session, args.key, args.budget)
    elif args.layer is not None:
        _read_layer(db, args.session, args.layer, args.budget)
    else:
        print("Error: specify --key, --layer, or --list")
        sys.exit(1)


def _list_keys(db: EventsDB, session_id: str):
    rows = db.list_context_keys(session_id)
    if not rows:
        print("No context available for this session.")
        return
    for row in rows:
        print(f"  L{row['layer']} | {row['key']:40s} | ~{row['token_est']} tokens")


def _read_key(db: EventsDB, session_id: str, key: str, budget: int):
    row = db.get_context(session_id, key)
    if not row:
        print(f"Key '{key}' not found in session '{session_id}'.")
        return
    content = row["content"]
    if budget > 0 and row["token_est"] > budget:
        char_limit = budget * 4
        print(f"[BUDGET] Truncating to ~{budget} tokens ({char_limit} chars)")
        print(content[:char_limit])
        print(f"\n[BUDGET] {row['token_est'] - budget} tokens remaining in this entry")
    else:
        print(content)


def _read_layer(db: EventsDB, session_id: str, layer: int, budget: int):
    rows = db.get_context_by_layer(session_id, layer)
    if not rows:
        print(f"No context in Layer {layer} for session '{session_id}'.")
        return
    tokens_used = 0
    for row in rows:
        if budget > 0 and tokens_used + row["token_est"] > budget:
            remaining = len(rows) - rows.index(row)
            print(f"\n[BUDGET] Budget exhausted ({tokens_used}/{budget} tokens). {remaining} entries skipped.")
            break
        print(f"--- {row['key']} ({row['token_est']} tokens) ---")
        print(row["content"])
        print()
        tokens_used += row["token_est"]


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ctx_read.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ctx_read.py tests/test_ctx_read.py
git commit -m "feat: add ctx_read CLI tool for sub-agent context retrieval"
```

---

### Task 5: Executor Integration — ContextWriter + Chain Output

**Files:**
- Modify: `src/governance/executor.py`
- Modify: `src/governance/executor_prompt.py`

- [ ] **Step 1: Generate session_id in executor and call ContextWriter before execution**

In `src/governance/executor.py`, add imports at top:

```python
import uuid
from src.governance.context.writer import ContextWriter
from src.governance.context.tiers import classify_task_tier
```

In `execute_task()`, after the line `task_cwd = _resolve_project_cwd(...)` (around line 471), add session_id generation and ContextWriter population:

```python
        # ── Session ID + Context Store (progressive disclosure) ──
        session_id = f"task-{task_id}-{uuid.uuid4().hex[:8]}"
        tier = classify_task_tier(task.get("action", ""), spec)
        log.info(f"TaskExecutor: task #{task_id} tier={tier.name}, session={session_id}")

        ctx_writer = ContextWriter(self.db, session_id)
        # L1: chain outputs from predecessor tasks
        chain_from = spec.get("chain_from")
        if chain_from:
            prev_task = self.db.get_task(int(chain_from))
            if prev_task and prev_task.get("output"):
                ctx_writer.write_chain_output(int(chain_from), prev_task["output"])
        # L1: conversation summary if provided
        conv_summary = spec.get("conversation_summary", "")
        if conv_summary:
            ctx_writer.write_layer1(conversation_summary=conv_summary)
        # L0: identity + catalog (written last so catalog includes L1 entries)
        ctx_writer.write_layer0(task, dept_key)
```

- [ ] **Step 2: Pass session_id and tier to prompt builder**

Change the `prompt = self._prepare_prompt(...)` call to also pass session_id and tier:

```python
        prompt = self._prepare_prompt(task, dept_key, dept, task_cwd, project_name,
                                      blueprint=blueprint, session_id=session_id, tier=tier)
```

Update `_prepare_prompt` signature:

```python
    def _prepare_prompt(self, task: dict, dept_key: str, dept: dict,
                        task_cwd: str, project_name: str,
                        blueprint=None, session_id: str = "", tier=None) -> str:
        return build_execution_prompt(task, dept_key, dept, task_cwd, project_name,
                                      blueprint=blueprint, session_id=session_id, tier=tier)
```

- [ ] **Step 3: Store chain output after task completion**

After the `output = compressed.content` line (around line 771), add:

```python
                    # Store output for chain continuity
                    if session_id:
                        ctx_writer.write_chain_output(task_id, output)
```

- [ ] **Step 4: Use tier for model, turns, and timeout**

Replace the existing model/turns resolution (around lines 529-545) with tier-aware logic. After the tier assignment line, add:

```python
        # ── Tier-aware defaults (override blueprint/policy if tier is set) ──
        if tier:
            if not blueprint:
                task_max_turns = tier.max_turns
            # Tier context budget stored in spec for ctx_read enforcement
            spec["context_budget"] = tier.context_budget
            spec["session_id"] = session_id
            self.db.update_task(task_id, spec=json.dumps(spec, ensure_ascii=False, default=str))
```

- [ ] **Step 5: Commit**

```bash
git add src/governance/executor.py
git commit -m "feat(executor): integrate ContextWriter + tier system + chain output"
```

---

### Task 6: Executor Prompt — L0 Injection + ctx_read Instructions

**Files:**
- Modify: `src/governance/executor_prompt.py`

- [ ] **Step 1: Update build_execution_prompt signature and inject ctx_read instructions**

Add `session_id` and `tier` params to `build_execution_prompt`:

```python
def build_execution_prompt(task: dict, dept_key: str, dept: dict,
                           task_cwd: str, project_name: str,
                           blueprint=None, session_id: str = "", tier=None) -> str:
```

After the existing `dynamic_ctx` injection (around line 125), replace it with L0 catalog injection and ctx_read instructions:

```python
    # ── Context Access: progressive disclosure via ctx_read ──
    if session_id:
        ctx_instructions = f"""

## Context Access (Progressive Disclosure)

You have access to additional context stored in a database. Read what you need — don't read everything.

**Tool:** `python scripts/ctx_read.py --session {session_id} <command>`

**Commands:**
- `--list` — see all available context keys and their token sizes
- `--key <key>` — read a specific context entry
- `--layer <0-3>` — read all entries in a layer
- `--budget <N>` — limit read to N tokens

**Layers:**
- L0 (in this prompt): identity, task description
- L1: session state, predecessor task outputs, conversation summary
- L2: file contents, memory entries, conversation fragments
- L3: full conversation transcript, codebase search, department history

**Start with `--list` to see what's available, then read what's relevant to your task.**
"""
        prompt += ctx_instructions

        # Inject L0 catalog directly (agent sees what's available without a tool call)
        try:
            from src.storage.events_db import EventsDB
            from pathlib import Path
            _db = EventsDB(str(Path(task_cwd).parent / "data" / "events.db")
                           if task_cwd else "data/events.db")
            catalog_row = _db.get_context(session_id, "catalog")
            if catalog_row:
                prompt += "\n" + catalog_row["content"]
        except Exception:
            pass  # Catalog injection is best-effort

    # ── Legacy ContextEngine (still runs, will be migrated in Phase 5) ──
    try:
        ctx = TaskContext.from_task(task, department=dept_key)
        ctx.cwd = task_cwd
        ctx.project_name = project_name
        budget = tier.prompt_budget if tier else 2000
        dynamic_ctx = _context_engine.assemble(ctx, budget_tokens=budget)
        if dynamic_ctx:
            prompt += "\n\n" + dynamic_ctx
    except Exception as e:
        log.warning(f"TaskExecutor: context assembly failed ({e}), continuing without dynamic context")
```

- [ ] **Step 2: Commit**

```bash
git add src/governance/executor_prompt.py
git commit -m "feat(prompt): inject ctx_read instructions and L0 catalog into sub-agent prompt"
```

---

### Task 7: Dispatch Integration — --tier and --chain-from Flags

**Files:**
- Modify: `scripts/dispatch.py`

- [ ] **Step 1: Add --tier and --chain-from CLI flags**

In `main()`, add to the argparse section (after `--skip-scrutiny`):

```python
    parser.add_argument("--tier", default=None,
                        choices=["light", "standard", "heavy"],
                        help="Task tier (controls context budget, model, turns)")
    parser.add_argument("--chain-from", type=int, default=None,
                        help="Task ID to read chain context from (predecessor task)")
    parser.add_argument("--conversation-summary", type=str, default=None,
                        help="Summary of current conversation for sub-agent context")
```

- [ ] **Step 2: Pass tier, chain_from, and conversation_summary to dispatch_raw**

Update `dispatch_raw` signature:

```python
def dispatch_raw(text: str, department: str, action: str, priority: str,
                 cognitive_mode: str, db: EventsDB,
                 skip_scrutiny: bool = False,
                 tier: str | None = None,
                 chain_from: int | None = None,
                 conversation_summary: str | None = None) -> dict:
```

In the spec dict, add:

```python
    if tier:
        spec["tier"] = tier
    if chain_from:
        spec["chain_from"] = chain_from
    if conversation_summary:
        spec["conversation_summary"] = conversation_summary
```

Update the call site in `main()`:

```python
        result = dispatch_raw(args.text, args.dept, action, args.priority, args.mode, db,
                              skip_scrutiny=args.skip_scrutiny,
                              tier=args.tier,
                              chain_from=args.chain_from,
                              conversation_summary=args.conversation_summary)
```

- [ ] **Step 3: Commit**

```bash
git add scripts/dispatch.py
git commit -m "feat(dispatch): add --tier, --chain-from, --conversation-summary flags"
```

---

### Task 8: Update Clawvard Practice Runner

**Files:**
- Modify: `scripts/clawvard_practice_runner.py`

- [ ] **Step 1: Use --tier heavy and --chain-from in dispatch calls**

In `dispatch_batch()`, update the `dispatch_raw` call:

```python
    result = dispatch_raw(prompt, "engineering", action, "high", "react", db,
                          skip_scrutiny=True,
                          tier="heavy",
                          chain_from=chain_from)
```

Add `chain_from` parameter to `dispatch_batch` signature:

```python
def dispatch_batch(db, practice_id, hash_val, task_order, current_index, questions,
                   chain_from: int | None = None):
```

In `main()` loop, pass the previous task_id:

```python
    prev_task_id = None
    while current_batch:
        batch_num += 1
        dim = current_batch[0].get("dimension", "?")
        print(f"\n=== Batch {batch_num}: {dim} (index={current_index}) ===")

        scores, new_hash, next_batch, task_id = dispatch_batch(
            db, practice_id, current_hash, task_order, current_index, current_batch,
            chain_from=prev_task_id,
        )
        prev_task_id = task_id
        ...
```

Update `dispatch_batch` to return `task_id`:

```python
    return scores, new_hash, next_batch, task_id
```

- [ ] **Step 2: Remove _extract_json_with_hash — agent now reads chain context via ctx_read**

The agent reads `chain:<prev_task_id>` via ctx_read, which contains the full API response. The runner still needs to extract scores from the task output for reporting, but the nextBatch is now handled by the agent reading chain context.

Keep `_extract_json_with_hash` for the runner's score reporting, but it's no longer critical for chain continuity.

- [ ] **Step 3: Commit**

```bash
git add scripts/clawvard_practice_runner.py
git commit -m "feat(clawvard): use --tier heavy and --chain-from for context parity"
```

---

### Task 9: Integration Test — End-to-End Context Flow

**Files:**
- Create: `tests/governance/test_context_parity_e2e.py`

- [ ] **Step 1: Write integration test**

```python
# tests/governance/test_context_parity_e2e.py
"""End-to-end test: context flows from writer → DB → ctx_read."""
import subprocess
import sys
import pytest
from src.storage.events_db import EventsDB
from src.governance.context.writer import ContextWriter
from src.governance.context.tiers import classify_task_tier, TIERS

@pytest.fixture
def db(tmp_path):
    return EventsDB(str(tmp_path / "test.db"))

class TestContextParityE2E:
    def test_writer_to_ctx_read_flow(self, db, tmp_path):
        """ContextWriter writes → ctx_read reads back correctly."""
        db_path = str(tmp_path / "test.db")
        session = "e2e-test-1"
        writer = ContextWriter(db, session)

        # Writer populates context
        writer.write_layer1(conversation_summary="User wants to run Clawvard practice")
        writer.write_chain_output(99, '{"hash": "abc123", "nextBatch": [{"id": "q1"}]}')
        writer.write_layer0({"action": "test", "spec": {}}, "engineering")

        # ctx_read should see all keys
        result = subprocess.run(
            [sys.executable, "scripts/ctx_read.py", "--db", db_path,
             "--session", session, "--list"],
            capture_output=True, text=True, cwd=".",
        )
        assert "session:conversation_summary" in result.stdout
        assert "chain:99" in result.stdout

        # ctx_read should read chain output
        result = subprocess.run(
            [sys.executable, "scripts/ctx_read.py", "--db", db_path,
             "--session", session, "--key", "chain:99"],
            capture_output=True, text=True, cwd=".",
        )
        assert "abc123" in result.stdout
        assert "nextBatch" in result.stdout

    def test_tier_classification_affects_budget(self, db):
        """Heavy tier gets 128K budget, light gets 4K."""
        heavy = classify_task_tier("Clawvard practice: understanding", {})
        light = classify_task_tier("check docker status", {})
        assert heavy.context_budget == 128_000
        assert light.context_budget == 4_000

    def test_chain_context_survives_compression(self, db):
        """Chain output stored in DB is not subject to output_compress truncation."""
        session = "e2e-chain"
        writer = ContextWriter(db, session)
        # Simulate a large API response with nextBatch
        large_output = '{"results": [], "hash": "x" , "nextBatch": ' + '[' + ','.join(
            [f'{{"id": "q{i}", "prompt": "x" * 500}}' for i in range(10)]
        ) + ']}'
        writer.write_chain_output(100, large_output)
        row = db.get_context(session, "chain:100")
        # Full content preserved, no truncation
        assert len(row["content"]) == len(large_output)
        assert "nextBatch" in row["content"]
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/storage/test_context_mixin.py tests/governance/test_context_writer.py tests/governance/test_task_tiers.py tests/test_ctx_read.py tests/governance/test_context_parity_e2e.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/governance/test_context_parity_e2e.py
git commit -m "test: add end-to-end integration test for context parity flow"
```

---

### Task 10: Cleanup — Wire Today's Hotfixes into New System

**Files:**
- Modify: `src/governance/pipeline/output_compress.py`
- Modify: `src/governance/dispatcher.py`

- [ ] **Step 1: Keep output_compress DEFAULT_MAX_CHARS at 6000**

Verify the changes from today's hotfix are still in place:
- `output_compress.py`: `DEFAULT_MAX_CHARS = 6000`
- `executor.py`: `compress_output(response.output)` (no hardcoded max_chars)

No code change needed — just verify.

- [ ] **Step 2: Clean up dispatcher skip-scrutiny to use tier**

In `src/governance/dispatcher.py`, update the complexity override to also respect tier:

```python
        # ── Complexity Classification ──
        # Respect pre-set complexity (e.g. from --skip-scrutiny) or tier override
        if spec.get("complexity") == "trivial" or spec.get("tier") == "light":
            from src.gateway.complexity import Complexity
            complexity = Complexity.TRIVIAL
        else:
            complexity = classify_complexity(action, spec)
            spec["complexity"] = complexity.name
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: No regressions

- [ ] **Step 4: Final commit**

```bash
git add src/governance/pipeline/output_compress.py src/governance/dispatcher.py
git commit -m "chore: wire hotfixes into context parity system, light tier skips scrutiny"
```
