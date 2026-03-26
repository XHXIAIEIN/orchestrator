# Wake Session Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the file-based wake system with a DB-driven session model, integrated with Governor approval, supporting interactive mode switching and cancellation.

**Architecture:** New `wake_sessions` table + `_wake_mixin.py` for DB operations. `wake.py` rewritten as session manager (create/query/cancel). `/wake` command added to `commands.py`. `wake_claude` tool updated to create Governor task + session. `wake-watcher.py` rewritten to poll DB instead of files, with per-turn cancel/inject checking.

**Tech Stack:** SQLite (events.db via EventsDB mixin), Agent SDK, existing Governor/approval/channel infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-26-wake-session-redesign.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/storage/_schema.py` | Modify | Add `wake_sessions` DDL + index |
| `src/storage/_wake_mixin.py` | Create | Wake session CRUD mixin |
| `src/storage/events_db.py` | Modify | Add WakeMixin to class hierarchy |
| `src/channels/wake.py` | Rewrite | Session manager (create/query/cancel/update mode) |
| `src/channels/chat/commands.py` | Modify | Add `/wake` command with subcommand routing |
| `src/channels/chat/tools.py` | Modify | Rewrite `wake_claude` tool + add `wake_interact` tool |
| `bin/wake-watcher.py` | Rewrite | DB-polling executor with cancel/inject support |
| `tests/test_wake_session.py` | Create | Tests for wake session lifecycle |

---

### Task 1: Schema — wake_sessions table

**Files:**
- Modify: `src/storage/_schema.py`

- [ ] **Step 1: Add wake_sessions DDL to TABLE_DDL**

In `src/storage/_schema.py`, append to the `TABLE_DDL` string, before the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS wake_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    chat_id     TEXT NOT NULL,
    spotlight   TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'silent',
    status      TEXT NOT NULL DEFAULT 'pending',
    result      TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wake_status ON wake_sessions(status);
CREATE INDEX IF NOT EXISTS idx_wake_task ON wake_sessions(task_id);
```

- [ ] **Step 2: Verify schema loads**

Run: `python -c "from src.storage._schema import TABLE_DDL; assert 'wake_sessions' in TABLE_DDL; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/storage/_schema.py
git commit -m "feat(wake): add wake_sessions table schema"
```

---

### Task 2: DB Mixin — wake session CRUD

**Files:**
- Create: `src/storage/_wake_mixin.py`
- Modify: `src/storage/events_db.py`

- [ ] **Step 1: Write test for wake session CRUD**

Create `tests/test_wake_session.py`:

```python
"""Tests for wake session lifecycle."""
import os
import tempfile
import pytest
from src.storage.events_db import EventsDB


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = EventsDB(db_path=path)
    yield d
    os.unlink(path)


def test_create_and_get(db):
    # Create a Governor task first
    task_id = db.create_task(
        action="test wake", reason="test", priority="medium",
        spec={"summary": "test"}, source="wake",
    )
    sid = db.create_wake_session(
        task_id=task_id, chat_id="123", spotlight="fix TG bot [telegram, fix]",
    )
    assert sid > 0

    session = db.get_wake_session(sid)
    assert session["task_id"] == task_id
    assert session["chat_id"] == "123"
    assert session["spotlight"] == "fix TG bot [telegram, fix]"
    assert session["mode"] == "silent"
    assert session["status"] == "pending"
    assert session["result"] is None


def test_update_status(db):
    task_id = db.create_task(
        action="test", reason="test", priority="medium",
        spec={}, source="wake",
    )
    sid = db.create_wake_session(task_id=task_id, chat_id="123", spotlight="test")

    db.update_wake_session(sid, status="approved")
    assert db.get_wake_session(sid)["status"] == "approved"

    db.update_wake_session(sid, status="running")
    s = db.get_wake_session(sid)
    assert s["status"] == "running"
    assert s["started_at"] is not None


def test_finish_session(db):
    task_id = db.create_task(
        action="test", reason="test", priority="medium",
        spec={}, source="wake",
    )
    sid = db.create_wake_session(task_id=task_id, chat_id="123", spotlight="test")
    db.update_wake_session(sid, status="running")

    db.finish_wake_session(sid, status="done", result="Changed 3 files, tests pass")
    s = db.get_wake_session(sid)
    assert s["status"] == "done"
    assert s["result"] == "Changed 3 files, tests pass"
    assert s["finished_at"] is not None


def test_get_by_status(db):
    for i in range(3):
        tid = db.create_task(action=f"t{i}", reason="t", priority="medium", spec={}, source="wake")
        db.create_wake_session(task_id=tid, chat_id="123", spotlight=f"task {i}")

    pending = db.get_wake_sessions(status="pending")
    assert len(pending) == 3

    # Approve first one
    db.update_wake_session(pending[0]["id"], status="approved")
    assert len(db.get_wake_sessions(status="pending")) == 2
    assert len(db.get_wake_sessions(status="approved")) == 1


def test_get_active_for_chat(db):
    tid = db.create_task(action="t", reason="t", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=tid, chat_id="456", spotlight="test")
    db.update_wake_session(sid, status="running")

    active = db.get_active_wake_session(chat_id="456")
    assert active is not None
    assert active["id"] == sid

    # No active session for other chat
    assert db.get_active_wake_session(chat_id="999") is None


def test_update_mode(db):
    tid = db.create_task(action="t", reason="t", priority="medium", spec={}, source="wake")
    sid = db.create_wake_session(task_id=tid, chat_id="123", spotlight="test")
    db.update_wake_session(sid, status="running")

    db.update_wake_session(sid, mode="milestone")
    assert db.get_wake_session(sid)["mode"] == "milestone"

    db.update_wake_session(sid, mode="silent")
    assert db.get_wake_session(sid)["mode"] == "silent"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_wake_session.py -v`
Expected: FAIL — `AttributeError: 'EventsDB' object has no attribute 'create_wake_session'`

- [ ] **Step 3: Create `_wake_mixin.py`**

Create `src/storage/_wake_mixin.py`:

```python
"""Wake session methods for EventsDB."""
from datetime import datetime, timezone


class WakeMixin:

    def create_wake_session(self, task_id: int, chat_id: str,
                            spotlight: str, mode: str = "silent") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO wake_sessions "
                "(task_id, chat_id, spotlight, mode, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (task_id, chat_id, spotlight, mode, now),
            )
            return cursor.lastrowid

    def get_wake_session(self, session_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_wake_session_by_task(self, task_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions WHERE task_id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_wake_sessions(self, status: str = None, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM wake_sessions WHERE status = ? "
                    "ORDER BY id DESC LIMIT ?", (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM wake_sessions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_active_wake_session(self, chat_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wake_sessions "
                "WHERE chat_id = ? AND status IN ('pending', 'approved', 'running') "
                "ORDER BY id DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_wake_session(self, session_id: int, **kwargs):
        allowed = {"status", "mode", "result", "started_at", "finished_at"}
        invalid = set(kwargs) - allowed
        if invalid:
            raise ValueError(f"Invalid wake_session columns: {invalid}")
        # Auto-set started_at when transitioning to running
        if kwargs.get("status") == "running" and "started_at" not in kwargs:
            kwargs["started_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE wake_sessions SET {sets} WHERE id = ?", vals,
            )

    def finish_wake_session(self, session_id: int, status: str,
                            result: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE wake_sessions SET status = ?, result = ?, "
                "finished_at = ? WHERE id = ?",
                (status, result, now, session_id),
            )
```

- [ ] **Step 4: Add WakeMixin to EventsDB**

In `src/storage/events_db.py`, add import:

```python
from src.storage._wake_mixin import WakeMixin
```

Update class definition:

```python
class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin, SessionsMixin, WakeMixin):
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_wake_session.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/storage/_wake_mixin.py src/storage/events_db.py tests/test_wake_session.py
git commit -m "feat(wake): add WakeMixin — session CRUD for wake_sessions table"
```

---

### Task 3: Rewrite wake.py — session manager

**Files:**
- Rewrite: `src/channels/wake.py`

- [ ] **Step 1: Move old wake.py to .trash**

```bash
mv src/channels/wake.py .trash/2026-03-26-wake-redesign/wake.py.bak
```

- [ ] **Step 2: Write new wake.py**

Create `src/channels/wake.py`:

```python
"""
Wake Session Manager — 创建、查询、取消 wake session。

DB-driven，不再写文件。tmp/wake/{channel}/{session_id}/ 仅用作临时工作目录。
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

WAKE_WORK_DIR = _REPO_ROOT / "tmp" / "wake"

# Sub-commands reserved words — first token match
_SUBCOMMANDS = {"cancel", "verbose", "quiet"}


def create_session(chat_id: str, spotlight: str, channel: str = "telegram",
                   mode: str = "silent", db: EventsDB = None) -> dict:
    """Create a wake session + Governor task. Returns {"session_id", "task_id"}."""
    db = db or EventsDB()

    # Create Governor task (source="wake" so it enters approval chain)
    task_id = db.create_task(
        action=spotlight,
        reason=f"Wake request from {channel}:{chat_id}",
        priority="high",
        spec={"summary": spotlight, "source": "wake", "chat_id": chat_id},
        source="wake",
    )

    session_id = db.create_wake_session(
        task_id=task_id,
        chat_id=chat_id,
        spotlight=spotlight,
        mode=mode,
    )

    # Create work directory
    work_dir = WAKE_WORK_DIR / channel / str(session_id)
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"wake: session #{session_id} created (task #{task_id}): {spotlight}")
    return {"session_id": session_id, "task_id": task_id}


def cancel_session(chat_id: str, db: EventsDB = None) -> str:
    """Cancel the active wake session for a chat. Returns status message."""
    db = db or EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "没有正在进行的 wake 任务"

    sid = session["id"]
    old_status = session["status"]

    if old_status == "pending":
        db.finish_wake_session(sid, status="cancelled")
        db.update_task(session["task_id"], status="cancelled")
        return f"Wake #{sid} 已取消（还没开始审批）"

    if old_status == "approved":
        db.finish_wake_session(sid, status="cancelled")
        return f"Wake #{sid} 已取消（审批通过但还没执行）"

    if old_status == "running":
        # Set cancelled — watcher will detect and kill on next turn check
        db.update_wake_session(sid, status="cancelled")
        return f"Wake #{sid} 正在取消（等待当前 turn 结束）"

    return f"Wake #{sid} 状态为 {old_status}，无法取消"


def set_mode(chat_id: str, mode: str, db: EventsDB = None) -> str:
    """Switch mode for the active wake session. Returns status message."""
    db = db or EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "没有正在进行的 wake 任务"

    db.update_wake_session(session["id"], mode=mode)
    label = "里程碑模式（实时推送进度）" if mode == "milestone" else "静默模式（完成后推送报告）"
    return f"Wake #{session['id']} 已切换到{label}"


def list_active(chat_id: str = "", db: EventsDB = None) -> list[dict]:
    """List active wake sessions, optionally filtered by chat_id."""
    db = db or EventsDB()
    active = []
    for status in ("pending", "approved", "running"):
        active.extend(db.get_wake_sessions(status=status))
    if chat_id:
        active = [s for s in active if s["chat_id"] == chat_id]
    return active


def format_session_status(sessions: list[dict]) -> str:
    """Format session list for display."""
    if not sessions:
        return "没有活跃的 wake 任务"
    lines = []
    for s in sessions:
        elapsed = ""
        if s["started_at"]:
            start = datetime.fromisoformat(s["started_at"])
            mins = int((datetime.now(timezone.utc) - start).total_seconds() / 60)
            elapsed = f" ({mins}min)"
        lines.append(
            f"#{s['id']} [{s['status']}] {s['spotlight']}{elapsed}"
        )
    return "\n".join(lines)


def parse_wake_command(args: str) -> tuple[str, str]:
    """Parse /wake args. Returns (subcommand, rest) or ('task', full_args)."""
    if not args.strip():
        return ("status", "")
    parts = args.strip().split(maxsplit=1)
    first = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if first in _SUBCOMMANDS:
        return (first, rest)
    return ("task", args.strip())
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from src.channels.wake import create_session, cancel_session, parse_wake_command; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add .trash/2026-03-26-wake-redesign/wake.py.bak src/channels/wake.py
git commit -m "feat(wake): rewrite wake.py as DB-driven session manager"
```

---

### Task 4: /wake command in commands.py

**Files:**
- Modify: `src/channels/chat/commands.py`

- [ ] **Step 1: Read current commands.py**

Read `src/channels/chat/commands.py` to locate the exact insertion points.

- [ ] **Step 2: Add /wake to command routing**

Add to the elif chain in `handle_command()`:

```python
    elif cmd == "/wake":
        _cmd_wake(reply_fn, chat_id, args, channel_source)
```

Add to the COMMANDS dict:

```python
    "/wake": "查看/派发/控制 wake 任务",
```

- [ ] **Step 3: Implement _cmd_wake handler**

Add at end of `commands.py`:

```python
def _cmd_wake(reply_fn, chat_id: str, args: str, channel_source: str):
    """Handle /wake command with subcommand routing."""
    from src.channels.wake import (
        parse_wake_command, create_session, cancel_session,
        set_mode, list_active, format_session_status,
    )
    from src.channels import config as ch_cfg

    if not ch_cfg.user_can(chat_id, "wake_claude"):
        reply_fn(chat_id, "权限不足")
        return

    subcmd, rest = parse_wake_command(args)

    if subcmd == "status":
        sessions = list_active(chat_id)
        reply_fn(chat_id, format_session_status(sessions))

    elif subcmd == "cancel":
        msg = cancel_session(chat_id)
        reply_fn(chat_id, msg)

    elif subcmd == "verbose":
        msg = set_mode(chat_id, "milestone")
        reply_fn(chat_id, msg)

    elif subcmd == "quiet":
        msg = set_mode(chat_id, "silent")
        reply_fn(chat_id, msg)

    elif subcmd == "task":
        # rest is the full spotlight text
        result = create_session(
            chat_id=chat_id, spotlight=rest, channel=channel_source,
        )
        reply_fn(
            chat_id,
            f"Wake #{result['session_id']} 已提交（任务 #{result['task_id']}），等待审批",
        )
```

- [ ] **Step 4: Verify command parsing**

Run:
```bash
python -c "
from src.channels.wake import parse_wake_command
assert parse_wake_command('') == ('status', '')
assert parse_wake_command('cancel') == ('cancel', '')
assert parse_wake_command('verbose') == ('verbose', '')
assert parse_wake_command('修复 TG bot 轮询崩溃') == ('task', '修复 TG bot 轮询崩溃')
assert parse_wake_command('修复 cancel 相关的 bug') == ('task', '修复 cancel 相关的 bug')
print('OK')
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/channels/chat/commands.py
git commit -m "feat(wake): add /wake command — status/cancel/verbose/quiet/task"
```

---

### Task 5: Rewrite wake_claude tool + add wake_interact

**Files:**
- Modify: `src/channels/chat/tools.py`

- [ ] **Step 1: Read current tools.py**

Read `src/channels/chat/tools.py` to see exact tool definitions and handler locations.

- [ ] **Step 2: Update wake_claude tool schema**

Replace the existing `wake_claude` tool definition in CHAT_TOOLS with:

```python
{
    "name": "wake_claude",
    "description": (
        "Wake up Claude Code on the host machine to do real work "
        "(code changes, file ops, git). Provide a spotlight: one-line summary + keywords."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "spotlight": {
                "type": "string",
                "description": "One-line task summary with keywords, e.g. '修复 TG bot 轮询崩溃 [telegram, polling, fix]'",
            },
        },
        "required": ["spotlight"],
    },
},
```

- [ ] **Step 3: Add wake_interact tool to CHAT_TOOLS**

Add after wake_claude in the array:

```python
{
    "name": "wake_interact",
    "description": (
        "Send a message to a running wake session — add instructions, "
        "ask for progress, or nudge the running Claude Code."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to inject into the running wake session",
            },
        },
        "required": ["message"],
    },
},
```

- [ ] **Step 4: Rewrite _tool_wake_claude handler**

Replace the existing handler:

```python
def _tool_wake_claude(params: dict, chat_id: str, channel_source: str = "channel") -> str:
    from src.channels.wake import create_session
    spotlight = params.get("spotlight", "")
    if not spotlight:
        return "Error: spotlight is required"
    result = create_session(
        chat_id=chat_id, spotlight=spotlight, channel=channel_source,
    )
    return (
        f"Wake session #{result['session_id']} created (task #{result['task_id']}). "
        f"Waiting for Governor approval."
    )
```

- [ ] **Step 5: Add _tool_wake_interact handler**

```python
def _tool_wake_interact(params: dict, chat_id: str) -> str:
    from src.storage.events_db import EventsDB
    db = EventsDB()
    session = db.get_active_wake_session(chat_id)
    if not session:
        return "No active wake session for this chat"
    if session["status"] != "running":
        return f"Wake session #{session['id']} is {session['status']}, not running"
    message = params.get("message", "")
    if not message:
        return "Error: message is required"
    db.add_agent_event(
        task_id=session["task_id"],
        event_type="wake.inject",
        data={"message": message, "chat_id": chat_id},
    )
    return f"Message injected into wake session #{session['id']}"
```

- [ ] **Step 6: Update execute_tool routing**

In `execute_tool()`, add routing for the new tool names. Update the `wake_claude` call to pass `channel_source`, and add the `wake_interact` case:

```python
elif tool_name == "wake_claude":
    return _tool_wake_claude(tool_input, chat_id, channel_source)
elif tool_name == "wake_interact":
    return _tool_wake_interact(tool_input, chat_id)
```

- [ ] **Step 7: Verify tool definitions load**

Run: `python -c "from src.channels.chat.tools import CHAT_TOOLS; names = [t['name'] for t in CHAT_TOOLS]; assert 'wake_claude' in names; assert 'wake_interact' in names; print('OK:', names)"`
Expected: `OK: [... 'wake_claude', 'wake_interact' ...]`

- [ ] **Step 8: Commit**

```bash
git add src/channels/chat/tools.py
git commit -m "feat(wake): rewrite wake_claude tool + add wake_interact for session injection"
```

---

### Task 6: Rewrite wake-watcher.py — DB-driven executor

**Files:**
- Rewrite: `bin/wake-watcher.py`

- [ ] **Step 1: Move old watcher to .trash**

```bash
cp bin/wake-watcher.py .trash/2026-03-26-wake-redesign/wake-watcher.py.bak
```

- [ ] **Step 2: Write new wake-watcher.py**

Rewrite `bin/wake-watcher.py`:

```python
#!/usr/bin/env python3
"""
Wake Watcher — DB 轮询执行器。

在宿主机运行（不在 Docker 内）。
轮询 wake_sessions 表中 status='approved' 的记录，拉起 Claude Code 执行。
每 turn 检查取消信号和交互注入。
"""
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from src.core.agent_client import agent_query
from src.storage.events_db import EventsDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("wake-watcher")

POLL_INTERVAL = 5   # seconds
MAX_WORKERS = 2
WORK_DIR = _root / "tmp" / "wake"

# Track which sessions are currently being executed
_active: set[int] = set()


def _load_env():
    """Load .env file, strip ANTHROPIC_API_KEY so Claude CLI uses OAuth."""
    env_file = _root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key == "ANTHROPIC_API_KEY":
                os.environ.pop(key, None)
                continue
            os.environ.setdefault(key, val)


def _build_prompt(session: dict) -> str:
    """Build the prompt for Claude Code from a wake session."""
    return f"""[Wake Session #{session['id']}] chat_id={session['chat_id']}

Task: {session['spotlight']}

Instructions:
- You were woken up by the orchestrator because it needs Claude Code to do real work.
- Use the /bot-tg or /bot-wx skill to check recent chat messages for full context (chat_id={session['chat_id']}).
- Complete the task, commit if needed, then write a brief result summary.
- Work in the orchestrator repo: {_root}
- If mode is 'milestone', write progress updates via agent_events (the system handles this automatically).
"""


def _check_cancel(db: EventsDB, session_id: int) -> bool:
    """Check if session has been cancelled."""
    s = db.get_wake_session(session_id)
    return s is not None and s["status"] == "cancelled"


def _check_injects(db: EventsDB, task_id: int, since_id: int) -> tuple[list[str], int]:
    """Check for injected messages. Returns (messages, new_since_id)."""
    events = db.get_agent_events(task_id, limit=50)
    messages = []
    max_id = since_id
    for ev in events:
        if ev["id"] <= since_id:
            continue
        data = json.loads(ev["data"]) if isinstance(ev["data"], str) else ev["data"]
        if data.get("message"):
            messages.append(data["message"])
        max_id = max(max_id, ev["id"])
    return messages, max_id


def _write_milestone(db: EventsDB, task_id: int, step: str, message: str):
    """Write a milestone event."""
    db.add_agent_event(
        task_id=task_id,
        event_type="wake.milestone",
        data={"step": step, "msg": message, "ts": datetime.now(timezone.utc).isoformat()},
    )


def _dispatch(session: dict):
    """Execute a single wake session."""
    db = EventsDB()
    sid = session["id"]
    task_id = session["task_id"]

    log.info("Starting wake session #%d: %s", sid, session["spotlight"])

    # Mark running
    db.update_wake_session(sid, status="running")
    db.update_task(task_id, status="running",
                   started_at=datetime.now(timezone.utc).isoformat())

    _write_milestone(db, task_id, "start", f"开始执行: {session['spotlight']}")

    prompt = _build_prompt(session)

    try:
        result = agent_query(
            prompt=prompt,
            max_turns=25,
            cwd=str(_root),
        )

        # Check cancel one last time
        if _check_cancel(db, sid):
            log.info("Wake #%d cancelled during execution", sid)
            db.finish_wake_session(sid, status="cancelled", result="执行中被取消")
            _write_milestone(db, task_id, "cancelled", "任务被用户取消")
            return

        # Trim result for storage
        result_text = result.strip()[-2000:] if len(result) > 2000 else result.strip()
        db.finish_wake_session(sid, status="done", result=result_text)
        db.update_task(task_id, status="done", output=result_text[:500],
                       finished_at=datetime.now(timezone.utc).isoformat())

        _write_milestone(db, task_id, "done", "任务完成")
        log.info("Wake #%d completed", sid)

    except Exception as e:
        error_msg = f"Agent SDK error: {str(e)[:500]}"
        log.error("Wake #%d failed: %s", sid, e)
        db.finish_wake_session(sid, status="failed", result=error_msg)
        db.update_task(task_id, status="failed", output=error_msg,
                       finished_at=datetime.now(timezone.utc).isoformat())
        _write_milestone(db, task_id, "failed", error_msg)

    finally:
        _active.discard(sid)


def main():
    _load_env()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    db = EventsDB()
    log.info("Wake watcher started (polling every %ds, max %d workers)", POLL_INTERVAL, MAX_WORKERS)

    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="wake")

    try:
        while True:
            sessions = db.get_wake_sessions(status="approved")
            for s in sessions:
                if s["id"] not in _active:
                    _active.add(s["id"])
                    pool.submit(_dispatch, s)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        log.info("Shutting down")
        pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify watcher imports**

Run: `python -c "import bin; exec(open('bin/wake-watcher.py').read().split('def main')[0]); print('OK')"`

Or simpler: `python -c "sys_path_hack = __import__('sys'); sys_path_hack.path.insert(0, '.'); from src.core.agent_client import agent_query; from src.storage.events_db import EventsDB; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add .trash/2026-03-26-wake-redesign/wake-watcher.py.bak bin/wake-watcher.py
git commit -m "feat(wake): rewrite watcher — DB polling, cancel support, milestone events"
```

---

### Task 7: Governor integration — approval callback

**Files:**
- Modify: `src/channels/wake.py`

- [ ] **Step 1: Read Governor approval flow**

Read how Governor currently handles task approval callbacks, specifically how `source="wake"` tasks will be approved and how the approval result propagates back to `wake_sessions`.

- [ ] **Step 2: Add approval callback to wake.py**

Add to `src/channels/wake.py`:

```python
def on_task_approved(task_id: int, db: EventsDB = None):
    """Callback: Governor approved a wake task → mark session as approved."""
    db = db or EventsDB()
    session = db.get_wake_session_by_task(task_id)
    if not session:
        return
    if session["status"] == "pending":
        db.update_wake_session(session["id"], status="approved")
        log.info(f"wake: session #{session['id']} approved (task #{task_id})")


def on_task_denied(task_id: int, db: EventsDB = None):
    """Callback: Governor denied a wake task → mark session as denied."""
    db = db or EventsDB()
    session = db.get_wake_session_by_task(task_id)
    if not session:
        return
    db.finish_wake_session(session["id"], status="denied")
    log.info(f"wake: session #{session['id']} denied (task #{task_id})")
```

- [ ] **Step 3: Wire callbacks into approval gateway**

In `src/governance/approval.py`, in `submit_decision()`, after setting the decision, add a check for wake tasks:

```python
# After setting req.decision and notifying:
try:
    from src.channels.wake import on_task_approved, on_task_denied
    if decision == "approve":
        on_task_approved(task_id)
    elif decision == "deny":
        on_task_denied(task_id)
except Exception:
    pass  # wake module not critical for approval flow
```

- [ ] **Step 4: Verify the callback integration**

Run:
```bash
python -c "
from src.channels.wake import on_task_approved, on_task_denied
from src.storage.events_db import EventsDB
import tempfile, os
fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
db = EventsDB(db_path=path)
tid = db.create_task(action='test', reason='t', priority='medium', spec={}, source='wake')
db.create_wake_session(task_id=tid, chat_id='123', spotlight='test')
on_task_approved(tid, db=db)
s = db.get_wake_session_by_task(tid)
assert s['status'] == 'approved', f'Expected approved, got {s[\"status\"]}'
print('OK')
os.unlink(path)
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/channels/wake.py src/governance/approval.py
git commit -m "feat(wake): wire Governor approval callbacks to wake session status"
```

---

### Task 8: Channel-layer notification for wake events

**Files:**
- Modify: `src/channels/chat/commands.py` (already done in Task 4)
- Modify: `src/channels/registry.py` or add event bus subscription

- [ ] **Step 1: Add wake event subscription to channel registry**

The watcher writes `wake.milestone` and status changes to DB. Channel layer needs to poll for these and push to TG/WX. Add a lightweight poller in `src/channels/wake.py`:

```python
def get_unsent_milestones(task_id: int, since_event_id: int = 0,
                          db: EventsDB = None) -> list[dict]:
    """Get milestone events newer than since_event_id."""
    db = db or EventsDB()
    events = db.get_agent_events(task_id, limit=50)
    result = []
    for ev in events:
        if ev["id"] <= since_event_id:
            continue
        data = json.loads(ev["data"]) if isinstance(ev["data"], str) else ev["data"]
        if "msg" in data:
            result.append({"id": ev["id"], **data})
    return result


def format_wake_notification(session: dict, event_type: str,
                             milestone: dict = None) -> str:
    """Format a wake notification message for TG/WX."""
    sid = session["id"]
    spot = session["spotlight"]

    if event_type == "started":
        return f"⚙️ Wake #{sid} 开始执行\n{spot}"
    elif event_type == "milestone":
        return f"📍 Wake #{sid}: {milestone.get('msg', '')}"
    elif event_type == "done":
        result = session.get("result", "")[:800]
        return f"✅ Wake #{sid} 完成\n{spot}\n\n{result}"
    elif event_type == "failed":
        result = session.get("result", "")[:500]
        return f"❌ Wake #{sid} 失败\n{result}"
    elif event_type == "cancelled":
        return f"🚫 Wake #{sid} 已取消"
    elif event_type == "denied":
        return f"⛔ Wake #{sid} 审批被拒"
    elif event_type == "approved":
        return f"✔ Wake #{sid} 审批通过，排队执行中"
    return f"Wake #{sid}: {event_type}"
```

- [ ] **Step 2: Add notification dispatch to approval callbacks**

Update `on_task_approved` and `on_task_denied` in `src/channels/wake.py` to broadcast notifications:

```python
def _notify(session: dict, event_type: str, milestone: dict = None):
    """Push wake notification to all channels."""
    try:
        from src.channels.registry import get_channel_registry
        from src.channels.base import ChannelMessage
        text = format_wake_notification(session, event_type, milestone)
        reg = get_channel_registry()
        reg.broadcast(ChannelMessage(
            text=text, event_type=f"wake.{event_type}", priority="HIGH",
        ))
    except Exception as e:
        log.warning(f"wake: notification failed: {e}")
```

Call `_notify(session, "approved")` from `on_task_approved` and `_notify(session, "denied")` from `on_task_denied`.

- [ ] **Step 3: Add notification calls to watcher**

In `bin/wake-watcher.py`, in `_dispatch()`:
- After marking running: broadcast "started"
- After writing milestone: broadcast milestone (if mode == "milestone")
- After done/failed/cancelled: broadcast terminal status

Add to `_dispatch()` after status changes:

```python
from src.channels.wake import _notify, format_wake_notification

# After marking running:
_notify(session, "started")

# After done:
updated = db.get_wake_session(sid)
_notify(updated, "done")

# After failed:
updated = db.get_wake_session(sid)
_notify(updated, "failed")
```

- [ ] **Step 4: Commit**

```bash
git add src/channels/wake.py bin/wake-watcher.py
git commit -m "feat(wake): add channel-layer notifications for wake lifecycle events"
```

---

### Task 9: End-to-end integration test

**Files:**
- Modify: `tests/test_wake_session.py`

- [ ] **Step 1: Add integration test for full lifecycle**

Append to `tests/test_wake_session.py`:

```python
def test_full_lifecycle(db):
    """Test: create → approve → run → done."""
    from src.channels.wake import create_session, cancel_session, on_task_approved

    result = create_session(chat_id="100", spotlight="test task [test]", db=db)
    sid = result["session_id"]
    tid = result["task_id"]

    # Should be pending
    s = db.get_wake_session(sid)
    assert s["status"] == "pending"

    # Approve
    on_task_approved(tid, db=db)
    s = db.get_wake_session(sid)
    assert s["status"] == "approved"

    # Simulate watcher picking it up
    db.update_wake_session(sid, status="running")
    s = db.get_wake_session(sid)
    assert s["status"] == "running"
    assert s["started_at"] is not None

    # Simulate completion
    db.finish_wake_session(sid, status="done", result="Changed 2 files")
    s = db.get_wake_session(sid)
    assert s["status"] == "done"
    assert s["result"] == "Changed 2 files"
    assert s["finished_at"] is not None


def test_cancel_running(db):
    """Test: cancel a running session."""
    from src.channels.wake import create_session, cancel_session, on_task_approved

    result = create_session(chat_id="200", spotlight="cancellable [test]", db=db)
    sid = result["session_id"]
    on_task_approved(result["task_id"], db=db)
    db.update_wake_session(sid, status="running")

    msg = cancel_session("200", db=db)
    assert "正在取消" in msg
    assert db.get_wake_session(sid)["status"] == "cancelled"


def test_parse_wake_command():
    from src.channels.wake import parse_wake_command
    assert parse_wake_command("") == ("status", "")
    assert parse_wake_command("cancel") == ("cancel", "")
    assert parse_wake_command("cancel something") == ("cancel", "something")
    assert parse_wake_command("verbose") == ("verbose", "")
    assert parse_wake_command("quiet") == ("quiet", "")
    assert parse_wake_command("修复 TG bot") == ("task", "修复 TG bot")
    assert parse_wake_command("修复 cancel 相关") == ("task", "修复 cancel 相关")
    assert parse_wake_command("CANCEL") == ("cancel", "")


def test_inject_message(db):
    """Test: inject message into running session via agent_events."""
    from src.channels.wake import create_session, on_task_approved
    import json

    result = create_session(chat_id="300", spotlight="inject test", db=db)
    on_task_approved(result["task_id"], db=db)
    db.update_wake_session(result["session_id"], status="running")

    # Inject
    db.add_agent_event(
        task_id=result["task_id"],
        event_type="wake.inject",
        data={"message": "also fix the tests", "chat_id": "300"},
    )

    events = db.get_agent_events(result["task_id"])
    inject_events = [e for e in events if json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]]
    assert len(inject_events) >= 1
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_wake_session.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_wake_session.py
git commit -m "test(wake): add integration tests for full session lifecycle"
```

---

### Task 10: Cleanup — remove old wake dedup and update health check

**Files:**
- Modify: `src/core/health.py`

- [ ] **Step 1: Add wake session check to health.py**

In `_check_channels()` in `src/core/health.py`, add wake session monitoring:

```python
# Check for stuck wake sessions (running > 30 min)
try:
    from datetime import timedelta
    with self.db._connect() as conn:
        stuck = conn.execute(
            "SELECT COUNT(*) FROM wake_sessions "
            "WHERE status = 'running' AND started_at < ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),)
        ).fetchone()[0]
    if stuck > 0:
        self.issues.append({
            "level": "high", "component": "wake",
            "summary": f"{stuck} 个 wake session 运行超过 30 分钟",
        })
    result["wake_stuck"] = stuck
except Exception:
    pass
```

- [ ] **Step 2: Commit**

```bash
git add src/core/health.py
git commit -m "feat(wake): add stuck wake session detection to health check"
```

---

## Execution Order

Tasks 1-2 are foundational (schema + mixin). Tasks 3-5 are the channel layer (wake manager + commands + tools). Task 6 is the executor. Task 7 wires approval. Task 8 adds notifications. Task 9 validates everything. Task 10 cleans up.

Dependencies: 1 → 2 → 3 → 4, 5 (parallel) → 6 → 7 → 8 → 9 → 10
