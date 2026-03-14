# Governor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a governance layer that auto-executes top-priority recommendations from InsightEngine and allows manual task execution with preview + confirmation from the dashboard.

**Architecture:** InsightEngine generates structured recommendations (with full spec); Governor picks the highest-priority one and runs `claude --dangerously-skip-permissions --print <prompt>` as a subprocess. Tasks are stored in a `tasks` table with status tracking. Dashboard shows tasks and lets user manually trigger execution with a preview modal.

**Tech Stack:** Python (subprocess, APScheduler), SQLite, Node/Express (existing), sql.js (read-only dashboard), vanilla JS (existing dashboard pattern)

**Key constraint:** Dashboard Node server uses sql.js in read-only buffer mode — it cannot write to DB. The approve endpoint in Node calls a Python subprocess to write task state.

---

### Task 1: Add `tasks` table to EventsDB

**Files:**
- Modify: `orchestrator/src/storage/events_db.py`

**Step 1: Add table to `_init_tables`**

In `_init_tables`, append to the executescript string after the `insights` table:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec TEXT NOT NULL DEFAULT '{}',
    action TEXT NOT NULL,
    reason TEXT,
    priority TEXT DEFAULT 'medium',
    source TEXT DEFAULT 'auto',
    status TEXT DEFAULT 'pending',
    output TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    started_at TEXT,
    finished_at TEXT
);
```

**Step 2: Add DB methods**

Add these methods to the `EventsDB` class:

```python
def create_task(self, action: str, reason: str, priority: str,
                spec: dict, source: str = 'auto') -> int:
    now = datetime.now(timezone.utc).isoformat()
    status = 'pending' if source == 'auto' else 'awaiting_approval'
    with self._connect() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (spec, action, reason, priority, source, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (json.dumps(spec, ensure_ascii=False), action, reason, priority, source, status, now)
        )
        return cur.lastrowid

def update_task(self, task_id: int, **kwargs):
    if not kwargs:
        return
    sets = ', '.join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    with self._connect() as conn:
        conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", vals)

def get_tasks(self, limit: int = 50) -> list:
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d['spec'] = json.loads(d['spec'])
        result.append(d)
    return result

def get_task(self, task_id: int) -> dict | None:
    with self._connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d['spec'] = json.loads(d['spec'])
    return d

def get_running_task(self) -> dict | None:
    with self._connect() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE status = 'running' LIMIT 1"
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d['spec'] = json.loads(d['spec'])
    return d
```

**Step 3: Verify table creation**

Run in container (or locally with Python):
```bash
cd D:/Agent/orchestrator
python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
print(db.get_tables())
"
```
Expected output includes `'tasks'`.

**Step 4: Commit**

```bash
cd D:/Agent/orchestrator
git add src/storage/events_db.py
git commit -m "feat: add tasks table and DB methods to EventsDB"
```

---

### Task 2: Extend InsightEngine recommendations schema

**Files:**
- Modify: `orchestrator/src/insights.py`

**Step 1: Update `recommendations` items schema in `INSIGHTS_TOOL`**

Find the `recommendations` property in `INSIGHTS_TOOL` and replace the items schema:

```python
"items": {
    "type": "object",
    "properties": {
        "action":         {"type": "string"},
        "reason":         {"type": "string"},
        "priority":       {"type": "string", "enum": ["high", "medium", "low"]},
        "problem":        {"type": "string", "description": "这个建议要解决什么问题"},
        "behavior_chain": {"type": "string", "description": "观察到的数字行为链，支撑问题存在的证据"},
        "observation":    {"type": "string", "description": "目前看到了什么现象"},
        "expected":       {"type": "string", "description": "执行后应该变成什么样"},
        "summary":        {"type": "string", "description": "一句话计划概要"},
        "importance":     {"type": "string", "description": "为什么这个重要"}
    },
    "required": ["action", "reason", "priority", "problem", "observation", "expected", "summary", "importance"]
},
```

**Step 2: Increase max_tokens**

In `InsightEngine.run()`, change:
```python
max_tokens=4096,
```
to:
```python
max_tokens=6000,
```

**Step 3: Commit**

```bash
git add src/insights.py
git commit -m "feat: extend InsightEngine recommendations with full spec fields"
```

---

### Task 3: Create `src/governor.py`

**Files:**
- Create: `orchestrator/src/governor.py`

**Step 1: Write the file**

```python
"""
Governor — picks top-priority insight recommendation and executes it via claude subprocess.
Auto-triggered after InsightEngine; also called by dashboard approve endpoint.
"""
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

TASK_PROMPT_TEMPLATE = """你在 /orchestrator 目录下工作。

问题：{problem}

行为链（观察到的数字行为）：{behavior_chain}

观察结果：{observation}

预期结果（执行后应该变成什么样）：{expected}

任务：{action}

原因：{reason}

完成后以 DONE: <一句话描述做了什么> 结尾。"""

CLAUDE_TIMEOUT = 300  # seconds


class Governor:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)

    def run(self) -> dict | None:
        """Auto-triggered: pick top high-priority recommendation and execute."""
        # Skip if something is already running
        if self.db.get_running_task():
            log.info("Governor: task already running, skipping")
            return None

        insights = self.db.get_latest_insights()
        recs = insights.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if not high:
            log.info("Governor: no high-priority recommendations, skipping")
            return None

        rec = high[0]
        spec = {
            "problem":        rec.get("problem", ""),
            "behavior_chain": rec.get("behavior_chain", ""),
            "observation":    rec.get("observation", ""),
            "expected":       rec.get("expected", ""),
            "summary":        rec.get("summary", ""),
            "importance":     rec.get("importance", ""),
        }
        task_id = self.db.create_task(
            action=rec.get("action", ""),
            reason=rec.get("reason", ""),
            priority=rec.get("priority", "high"),
            spec=spec,
            source="auto",
        )
        log.info(f"Governor: created task #{task_id}: {rec.get('summary', '')}")
        return self.execute_task(task_id)

    def execute_task(self, task_id: int) -> dict:
        """Execute task by ID — used by both auto and manual paths."""
        task = self.db.get_task(task_id)
        if not task:
            log.error(f"Governor: task #{task_id} not found")
            return {}

        spec = task.get("spec", {})
        prompt = TASK_PROMPT_TEMPLATE.format(
            problem=spec.get("problem", ""),
            behavior_chain=spec.get("behavior_chain", ""),
            observation=spec.get("observation", ""),
            expected=spec.get("expected", ""),
            action=task.get("action", ""),
            reason=task.get("reason", ""),
        )

        now = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status="running", started_at=now)
        log.info(f"Governor: executing task #{task_id}")

        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", prompt],
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                cwd="/orchestrator",
            )
            output = result.stdout.strip() or result.stderr.strip() or "(no output)"
            status = "done" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output = f"timeout after {CLAUDE_TIMEOUT}s"
            status = "failed"
        except FileNotFoundError:
            output = "claude CLI not found"
            status = "failed"
            log.error("Governor: claude CLI not found in PATH")
        except Exception as e:
            output = str(e)
            status = "failed"

        finished = datetime.now(timezone.utc).isoformat()
        self.db.update_task(task_id, status=status, output=output, finished_at=finished)
        log.info(f"Governor: task #{task_id} {status}")
        return self.db.get_task(task_id)
```

**Step 2: Quick smoke test (no claude needed)**

```bash
cd D:/Agent/orchestrator
python3 -c "
from src.governor import Governor
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
g = Governor(db=db)
# Create a manual test task
task_id = db.create_task(
    action='echo hello',
    reason='smoke test',
    priority='high',
    spec={'problem':'test','behavior_chain':'','observation':'','expected':'','summary':'test','importance':'test'},
    source='manual'
)
print('task_id:', task_id)
t = db.get_task(task_id)
print('status:', t['status'])
print('tasks:', len(db.get_tasks()))
"
```
Expected: prints task_id, status `awaiting_approval`, tasks count > 0.

**Step 3: Commit**

```bash
git add src/governor.py
git commit -m "feat: add Governor class with auto and manual execution paths"
```

---

### Task 4: Wire Governor into scheduler

**Files:**
- Modify: `orchestrator/src/scheduler.py`

**Step 1: Import Governor**

Add after existing imports:
```python
from src.governor import Governor
```

**Step 2: Call Governor in `run_analysis`**

After the InsightEngine block, add:
```python
    try:
        governor = Governor(db=db)
        governor.run()
    except Exception as e:
        log.error(f"Governor failed: {e}")
```

**Step 3: Commit**

```bash
git add src/scheduler.py
git commit -m "feat: trigger Governor automatically after InsightEngine"
```

---

### Task 5: Add CLI entry point for Node → Python bridge

**Files:**
- Create: `orchestrator/src/governor_cli.py`

Node's approve endpoint can't write to SQLite via sql.js, so it calls this script as a subprocess.

**Step 1: Write the file**

```python
#!/usr/bin/env python3
"""CLI bridge called by Node dashboard to approve/execute manual tasks."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governor import Governor
from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent / "events.db")


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "approve":
        print(json.dumps({"error": "usage: governor_cli.py approve <task_id>"}))
        sys.exit(1)

    try:
        task_id = int(sys.argv[2])
    except ValueError:
        print(json.dumps({"error": "task_id must be an integer"}))
        sys.exit(1)

    db = EventsDB(DB_PATH)
    task = db.get_task(task_id)
    if not task:
        print(json.dumps({"error": f"task {task_id} not found"}))
        sys.exit(1)
    if task["status"] != "awaiting_approval":
        print(json.dumps({"error": f"task {task_id} is not awaiting_approval (status={task['status']})"}))
        sys.exit(1)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    db.update_task(task_id, approved_at=now)

    governor = Governor(db=db)
    result = governor.execute_task(task_id)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
```

**Step 2: Test the CLI**

```bash
cd D:/Agent/orchestrator
python3 src/governor_cli.py approve 999
```
Expected: JSON with `{"error": "task 999 not found"}` — confirming it runs correctly.

**Step 3: Commit**

```bash
git add src/governor_cli.py
git commit -m "feat: add governor_cli.py for Node-to-Python task approval bridge"
```

---

### Task 6: Add tasks API to dashboard server

**Files:**
- Modify: `orchestrator/dashboard/server.js`

**Step 1: Add `express.json()` middleware and child_process import**

After `const fs = require('fs');` add:
```javascript
const { spawn } = require('child_process');
```

After `app.use(express.static(...))` add:
```javascript
app.use(express.json());
```

**Step 2: Add GET /api/tasks endpoint**

After the `/api/insights` endpoint:
```javascript
app.get('/api/tasks', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const rows = dbAll(db,
    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50"
  );
  db.close();
  res.json(rows.map(r => ({ ...r, spec: JSON.parse(r.spec || '{}') })));
});

app.get('/api/tasks/:id', (req, res) => {
  const db = getDb();
  if (!db) return res.json(null);
  const rows = dbAll(db, "SELECT * FROM tasks WHERE id = ?", [req.params.id]);
  db.close();
  if (!rows.length) return res.status(404).json({ error: 'not found' });
  const r = rows[0];
  res.json({ ...r, spec: JSON.parse(r.spec || '{}') });
});
```

**Step 3: Add POST /api/tasks/:id/approve endpoint**

```javascript
app.post('/api/tasks/:id/approve', (req, res) => {
  const taskId = parseInt(req.params.id);
  if (isNaN(taskId)) return res.status(400).json({ error: 'invalid task id' });

  const proc = spawn('python3', ['/orchestrator/src/governor_cli.py', 'approve', String(taskId)]);
  let stdout = '';
  let stderr = '';
  proc.stdout.on('data', d => { stdout += d; });
  proc.stderr.on('data', d => { stderr += d; });
  proc.on('close', code => {
    try {
      const result = JSON.parse(stdout);
      if (result.error) return res.status(400).json(result);
      broadcast({ type: 'task_update', task: result });
      res.json(result);
    } catch {
      res.status(500).json({ error: stderr || stdout || 'unknown error' });
    }
  });
});
```

**Step 4: Commit**

```bash
git add dashboard/server.js
git commit -m "feat: add tasks API endpoints and approve bridge to dashboard server"
```

---

### Task 7: Add Tasks panel + manual execution UI to dashboard

**Files:**
- Modify: `orchestrator/dashboard/public/index.html`

**Step 1: Add CSS for tasks panel**

In the `<style>` block, add after the existing `.anomaly` rule:

```css
/* Tasks panel */
.task-card { padding: 10px 0; border-bottom: 1px solid #161616; }
.task-card:last-child { border-bottom: none; }
.task-summary { font-size: 0.82rem; color: #ccc; }
.task-meta { font-size: 0.68rem; color: #3a3a3a; margin-top: 3px; }
.status-badge { font-size: 0.6rem; padding: 1px 6px; border-radius: 2px; margin-right: 6px; }
.status-pending    { background: #1a1a1e; color: #4a4a7a; }
.status-awaiting   { background: #1e1a0e; color: #7a5a1a; }
.status-running    { background: #0e1a0e; color: #2a6a2a; }
.status-done       { background: #0a1a0a; color: #2a5a2a; }
.status-failed     { background: #1a0a0a; color: #7a2a2a; }
.task-output { font-size: 0.72rem; color: #555; margin-top: 6px; background: #0d0d0d; padding: 6px 8px; border-radius: 3px; white-space: pre-wrap; word-break: break-word; }
.btn-exec { font-size: 0.65rem; padding: 2px 8px; border-radius: 2px; border: 1px solid #2a2a3a; background: #111; color: #4a4a7a; cursor: pointer; margin-left: 8px; }
.btn-exec:hover { background: #1a1a2a; color: #8a8ab0; }
/* Preview modal */
#task-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; }
#task-modal.open { display: flex; }
.modal-box { background: #111; border: 1px solid #1e1e1e; border-radius: 6px; padding: 24px; width: min(680px, 92vw); max-height: 80vh; overflow-y: auto; }
.modal-box h3 { font-size: 0.7rem; text-transform: uppercase; color: #333; letter-spacing: 1px; margin-bottom: 16px; }
.spec-field { margin: 10px 0; }
.spec-label { font-size: 0.6rem; text-transform: uppercase; color: #333; letter-spacing: 1px; }
.spec-value { font-size: 0.8rem; color: #aaa; margin-top: 3px; line-height: 1.6; }
.modal-actions { display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end; }
.btn-cancel { font-size: 0.72rem; padding: 5px 14px; border-radius: 3px; border: 1px solid #2a2a2a; background: #0a0a0a; color: #444; cursor: pointer; }
.btn-confirm { font-size: 0.72rem; padding: 5px 14px; border-radius: 3px; border: 1px solid #2a3a2a; background: #0a1a0a; color: #3a7a3a; cursor: pointer; }
.btn-confirm:hover { background: #0f2a0f; }
.btn-confirm:disabled { opacity: 0.4; cursor: not-allowed; }
```

**Step 2: Add Tasks panel card in HTML**

Find the `.grid` div and add a new card (place after the existing insights/recommendations card):

```html
<!-- Tasks Panel -->
<div class="card wide">
  <h2>执行任务</h2>
  <div id="tasks-list"><span class="no-data">暂无任务</span></div>
</div>

<!-- Manual execution modal -->
<div id="task-modal">
  <div class="modal-box">
    <h3>任务预览</h3>
    <div id="modal-spec"></div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeModal()">取消</button>
      <button class="btn-confirm" id="modal-confirm-btn" onclick="confirmExec()">确认执行</button>
    </div>
  </div>
</div>
```

**Step 3: Add JS for tasks loading and modal**

In the `<script>` block, add:

```javascript
let pendingTaskId = null;

function statusBadge(s) {
  const map = { pending:'status-pending', awaiting_approval:'status-awaiting',
                running:'status-running', done:'status-done', failed:'status-failed' };
  const label = { pending:'待执行', awaiting_approval:'待确认',
                  running:'执行中', done:'完成', failed:'失败' };
  return `<span class="status-badge ${map[s]||''}">${label[s]||s}</span>`;
}

async function loadTasks() {
  const r = await fetch('/api/tasks');
  const tasks = await r.json();
  const el = document.getElementById('tasks-list');
  if (!tasks.length) { el.innerHTML = '<span class="no-data">暂无任务</span>'; return; }
  el.innerHTML = tasks.map(t => `
    <div class="task-card">
      <div class="task-summary">
        ${statusBadge(t.status)}
        ${t.spec.summary || t.action}
        ${t.status === 'awaiting_approval'
          ? `<button class="btn-exec" onclick="openModal(${t.id})">查看 + 执行</button>`
          : ''}
      </div>
      <div class="task-meta">${t.priority} · ${t.source} · ${t.created_at.slice(0,16)}</div>
      ${t.output ? `<div class="task-output">${t.output.slice(0,400)}</div>` : ''}
    </div>
  `).join('');
}

async function openModal(taskId) {
  const r = await fetch(`/api/tasks/${taskId}`);
  const t = await r.json();
  pendingTaskId = taskId;
  const s = t.spec;
  const fields = [
    ['问题描述', s.problem],
    ['行为链', s.behavior_chain],
    ['观察结果', s.observation],
    ['预期结果', s.expected],
    ['为什么重要', s.importance],
    ['执行计划', t.action],
    ['执行原因', t.reason],
  ];
  document.getElementById('modal-spec').innerHTML = fields
    .filter(([,v]) => v)
    .map(([l,v]) => `<div class="spec-field"><div class="spec-label">${l}</div><div class="spec-value">${v}</div></div>`)
    .join('');
  document.getElementById('modal-confirm-btn').disabled = false;
  document.getElementById('task-modal').classList.add('open');
}

function closeModal() {
  document.getElementById('task-modal').classList.remove('open');
  pendingTaskId = null;
}

async function confirmExec() {
  if (!pendingTaskId) return;
  const btn = document.getElementById('modal-confirm-btn');
  btn.disabled = true;
  btn.textContent = '执行中...';
  try {
    await fetch(`/api/tasks/${pendingTaskId}/approve`, { method: 'POST' });
    closeModal();
    await loadTasks();
  } catch (e) {
    btn.textContent = '失败，重试';
    btn.disabled = false;
  }
}

// Load tasks on page load and refresh every 30s
loadTasks();
setInterval(loadTasks, 30000);

// Also reload on WebSocket updates
// (find existing ws.onmessage and add loadTasks() call there)
```

**Step 4: Hook into existing WebSocket onmessage**

Find the existing `ws.onmessage` handler and add `loadTasks()` inside it so tasks refresh on any broadcast.

**Step 5: Also wire up recommendations "手动执行" buttons**

In the existing recommendations rendering JS, add a "手动执行" button per recommendation that POSTs to `/api/tasks` to create a manual task then opens the modal. Add this endpoint to server.js:

```javascript
app.post('/api/tasks', (req, res) => {
  // Create manual task from recommendation payload
  const proc = spawn('python3', ['-c', `
import sys, json
sys.path.insert(0, '/orchestrator')
from src.storage.events_db import EventsDB
db = EventsDB('/orchestrator/events.db')
data = json.loads(sys.stdin.read())
tid = db.create_task(
    action=data['action'],
    reason=data.get('reason',''),
    priority=data.get('priority','medium'),
    spec=data.get('spec',{}),
    source='manual'
)
print(json.dumps({'id': tid}))
  `]);
  let body = '';
  req.on('data', d => { body += d; });
  req.on('end', () => { proc.stdin.write(body); proc.stdin.end(); });
  let out = '';
  proc.stdout.on('data', d => { out += d; });
  proc.on('close', () => {
    try { res.json(JSON.parse(out)); }
    catch { res.status(500).json({ error: out }); }
  });
});
```

**Step 6: Commit**

```bash
git add dashboard/server.js dashboard/public/index.html
git commit -m "feat: add tasks panel and manual execution modal to dashboard"
```

---

### Task 8: Rebuild Docker and verify end-to-end

**Step 1: Rebuild container**

```bash
cd D:/Agent/orchestrator
docker compose down
docker compose build --no-cache
docker compose up -d
```

**Step 2: Verify tasks table exists in container**

```bash
docker exec orchestrator python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
print(db.get_tables())
"
```
Expected: list includes `'tasks'`.

**Step 3: Smoke-test governor manually**

```bash
docker exec orchestrator python3 -c "
from src.governor import Governor
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
tid = db.create_task('echo test', 'smoke test', 'high',
    {'problem':'test','behavior_chain':'','observation':'','expected':'','summary':'smoke','importance':'test'},
    'manual')
db.update_task(tid, approved_at='2026-01-01T00:00:00Z')
g = Governor(db=db)
result = g.execute_task(tid)
print('status:', result.get('status'))
print('output:', result.get('output','')[:100])
"
```
Expected: status=done or failed (failed is OK if claude not authenticated), output shows something.

**Step 4: Verify dashboard at http://localhost:23714**

- Open browser → check Tasks panel appears
- Should show the smoke test task card with status

**Step 5: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "chore: governor end-to-end verified"
```
