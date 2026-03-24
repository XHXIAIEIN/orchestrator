# Governor Design — 2026-03-07

## Overview

Add a governance layer to orchestrator that closes the loop between observation and action.
InsightEngine discovers patterns and generates prioritized recommendations; Governor executes them.

## Goals

- Auto-execute top-priority recommendations after each InsightEngine run
- Show pending tasks in dashboard before execution (notify, no approval needed)
- Allow manual task execution with full spec preview and user confirmation
- Record all task context and outcomes for future learning

## Architecture

```
InsightEngine (every 6h)
    ↓ generates recommendations with full spec
Governor.run()
    ↓ picks top priority=high action
    ↓ writes tasks table (status=pending, source=auto)
Dashboard shows task card
    ↓ subprocess: claude --dangerously-skip-permissions --print <task_prompt>
    ↓ writes output, status=done/failed
```

Manual path:
```
Dashboard: Recommendations panel
    ↓ user clicks "查看详情 + 手动执行"
Preview modal (full spec: problem/observation/expected/importance/...)
    ↓ user clicks "确认执行"
POST /api/tasks/:id/approve
    ↓ Governor executes synchronously
    ↓ Dashboard updates status
```

## Data Model

### tasks table

```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Execution spec (JSON)
    spec TEXT NOT NULL,
    -- spec fields: {
    --   problem: str,        -- 问题描述
    --   behavior_chain: str, -- 复现步骤（行为链）
    --   observation: str,    -- 观察结果
    --   expected: str,       -- 预期结果
    --   summary: str,        -- 计划概要
    --   importance: str      -- 为什么重要
    -- }
    -- Top-level execution fields
    action TEXT NOT NULL,          -- 执行计划
    reason TEXT,                   -- 执行原因
    priority TEXT,                 -- high/medium/low
    source TEXT DEFAULT 'auto',    -- auto | manual
    -- Execution tracking
    status TEXT DEFAULT 'pending', -- pending | awaiting_approval | running | done | failed
    output TEXT,                   -- Claude output
    created_at TEXT NOT NULL,
    approved_at TEXT,              -- manual approval timestamp
    started_at TEXT,
    finished_at TEXT
);
```

Status flow:
- Auto:   `pending` → `running` → `done/failed`
- Manual: `awaiting_approval` → `running` → `done/failed`

## Components

### 1. InsightEngine schema extension (`src/insights.py`)

Extend `recommendations` array items to include full spec fields:

```python
{
    "action": str,
    "reason": str,
    "priority": "high|medium|low",
    "problem": str,
    "behavior_chain": str,
    "observation": str,
    "expected": str,
    "summary": str,
    "importance": str
}
```

Increase `max_tokens` from 4096 to 6000 to accommodate richer output.

### 2. `src/governor.py` (new)

```python
class Governor:
    def run(self):
        # Read latest insights
        # Pick first high-priority recommendation
        # Write task (status=pending, source=auto)
        # Build task_prompt from spec fields
        # subprocess.run(["claude", "--dangerously-skip-permissions", "--print", prompt])
        # Update task status + output

    def execute_task(self, task_id: int):
        # Used by both auto and manual paths
        # Update status=running, started_at
        # Call claude subprocess
        # Update status=done/failed, output, finished_at
```

Task prompt template:
```
你在 /orchestrator 目录下工作。

问题：{problem}

行为链（观察到的数字行为）：{behavior_chain}

观察结果：{observation}

预期结果（执行后应该是什么样）：{expected}

任务：{action}

原因：{reason}

完成后以 DONE: <一句话描述做了什么> 结尾。
```

### 3. `src/storage/events_db.py` additions

```python
def create_task(self, action, reason, priority, spec, source='auto') -> int
def update_task_status(self, task_id, status, output=None, ...)
def get_tasks(self, limit=50) -> list
def get_task(self, task_id) -> dict
def approve_task(self, task_id) -> dict
```

### 4. `src/scheduler.py` modification

```python
def run_analysis():
    ...
    engine.run()           # existing InsightEngine
    governor = Governor(db=db)
    governor.run()         # new: triggers after insights
```

### 5. Dashboard additions

**API endpoints (dashboard/server.js):**
- `GET /api/tasks` — task list with spec parsed
- `GET /api/tasks/:id` — single task detail
- `POST /api/tasks` — create manual task from recommendation
- `POST /api/tasks/:id/approve` — confirm manual task execution

**UI (dashboard/public/index.html):**
- Tasks panel: list of task cards with status badge, summary, priority
- Recommendation cards: each has "手动执行" button
- Preview modal: shows all spec fields before confirmation
- Auto-refreshes via existing WebSocket

## Error Handling

- Claude subprocess timeout: 300s, on timeout → status=failed, output="timeout"
- Claude not found: log error, skip governor run silently
- No high-priority recommendations: skip, log info
- Manual task: if approve fails, stay at awaiting_approval, show error in dashboard

## Constraints

- Governor only picks ONE task per InsightEngine run (avoid runaway execution)
- Governor skips if a task is already `running` (no concurrent execution)
- All Claude output stored verbatim in `tasks.output`
