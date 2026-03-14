# Dashboard Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保持当前极简黑色风格的前提下，为 dashboard 增加：顶部 sticky 状态栏、全中文增强任务卡片（可展开/时间线/动画）、实时日志流（SSE）。

**Architecture:** Python 将日志和调度状态写入 SQLite（`logs` 表 + `scheduler_status` 表），Node 通过 SSE 流式推送日志给前端，前端用原生 JS 消费 SSE 并实时渲染。任务卡片在前端展开/折叠，无需额外 API。

**Tech Stack:** 纯原生 JS（无框架）、CSS 动画、Server-Sent Events、SQLite via sql.js（只读）、Python sqlite3（写入）

---

### Task 1: 为 EventsDB 添加 `logs` 表和 `scheduler_status` 表

**Files:**
- Modify: `orchestrator/src/storage/events_db.py`

**Step 1: 在 `_init_tables` 的 executescript 末尾追加两张表**

找到 tasks 表定义后面，加入：

```sql
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL DEFAULT 'INFO',
    source TEXT NOT NULL DEFAULT 'system',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduler_status (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**Step 2: 添加 3 个方法到 EventsDB 类末尾**

```python
def write_log(self, message: str, level: str = 'INFO', source: str = 'system'):
    now = datetime.now(timezone.utc).isoformat()
    with self._connect() as conn:
        conn.execute(
            "INSERT INTO logs (level, source, message, created_at) VALUES (?, ?, ?, ?)",
            (level, source, message, now)
        )

def get_logs(self, since_id: int = 0, limit: int = 100) -> list:
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT id, level, source, message, created_at FROM logs WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]

def set_scheduler_status(self, key: str, value: str):
    now = datetime.now(timezone.utc).isoformat()
    with self._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO scheduler_status (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now)
        )

def get_scheduler_status(self) -> dict:
    with self._connect() as conn:
        rows = conn.execute("SELECT key, value FROM scheduler_status").fetchall()
    return {r['key']: r['value'] for r in rows}
```

**Step 3: 验证**

```bash
cd D:/Agent/orchestrator
python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
db.write_log('test message', 'INFO', 'test')
logs = db.get_logs()
print('log count:', len(logs), 'last:', logs[-1]['message'])
db.set_scheduler_status('next_collect', '2026-01-01T00:00:00+00:00')
status = db.get_scheduler_status()
print('status:', status)
"
```

Expected: `log count: 1+ last: test message` 和 `status: {'next_collect': ...}`

**Step 4: Commit**

```bash
cd D:/Agent/orchestrator
git add src/storage/events_db.py
git commit -m "feat: add logs and scheduler_status tables to EventsDB"
```

---

### Task 2: scheduler.py 写日志 + 调度状态

**Files:**
- Modify: `orchestrator/src/scheduler.py`

**Step 1: 在 `run_collectors` 开头和结尾写日志**

在函数顶部 `db = EventsDB(DB_PATH)` 后加：
```python
db.write_log("开始采集数据", "INFO", "collector")
```

在 `log.info(f"Collection done: {results}")` 后加：
```python
ok = [k for k, v in results.items() if v >= 0]
fail = [k for k, v in results.items() if v < 0]
msg = f"采集完成：{', '.join(ok)} 各 {[results[k] for k in ok]} 条" + (f"；失败：{', '.join(fail)}" if fail else "")
db.write_log(msg, "INFO", "collector")
```

**Step 2: 在 `run_analysis` 各步骤写日志**

在 `analyst.run()` 调用前后加：
```python
db.write_log("开始每日分析", "INFO", "analyst")
# ...（analyst.run() 已有）
db.write_log(f"每日分析完成：{result.get('summary','')[:60]}", "INFO", "analyst")
```

在 `engine.run()` 前后加：
```python
db.write_log("开始生成洞察", "INFO", "insights")
# ...（engine.run() 已有）
db.write_log("洞察生成完成", "INFO", "insights")
```

在 `governor.run()` 前后加：
```python
db.write_log("Governor 开始检查任务", "INFO", "governor")
# ...（governor.run() 已有）
db.write_log("Governor 执行完毕", "INFO", "governor")
```

**Step 3: 在 `start()` 里写调度状态**

APScheduler 有 `job.next_run_time` 属性。在 `scheduler.start()` 前加：

```python
def _update_schedule_status(scheduler, db):
    try:
        for job in scheduler.get_jobs():
            if job.next_run_time:
                db.set_scheduler_status(f"next_{job.id}", job.next_run_time.isoformat())
    except Exception:
        pass
```

在 `run_collectors()` 调用后加：
```python
_update_schedule_status(scheduler, EventsDB(DB_PATH))
```

在 scheduler.add_job 回调里更新状态——最简单做法是把 `run_collectors` 和 `run_analysis` 包装：

```python
def _wrap(fn, name, db_path):
    def wrapper():
        fn()
        try:
            db = EventsDB(db_path)
            from apscheduler.schedulers.blocking import BlockingScheduler
            # 写下次运行时间由 add_job 的 listener 处理
        except Exception:
            pass
    return wrapper
```

实际上最简单：在 `start()` 加 APScheduler event listener：

```python
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

def job_listener(event, db_path=DB_PATH):
    try:
        db = EventsDB(db_path)
        scheduler_ref = event.scheduler if hasattr(event, 'scheduler') else None
        # 直接记录执行事件
        status = "完成" if not event.exception else f"失败: {event.exception}"
        db.write_log(f"任务 [{event.job_id}] {status}", "INFO" if not event.exception else "ERROR", "scheduler")
    except Exception:
        pass
```

Wait - APScheduler's event object doesn't have `scheduler` ref easily. Simpler: just use a global ref or write status in the wrapped functions themselves.

**实际最简实现：直接在 `start()` 里记录初始状态，并在每次 job 执行后更新**

```python
def start():
    db = EventsDB(DB_PATH)
    scheduler = BlockingScheduler()

    def _collectors():
        run_collectors()
        try:
            job = scheduler.get_job("collectors")
            if job and job.next_run_time:
                EventsDB(DB_PATH).set_scheduler_status("next_collectors", job.next_run_time.isoformat())
        except Exception:
            pass

    def _analysis():
        run_analysis()
        try:
            job = scheduler.get_job("analysis")
            if job and job.next_run_time:
                EventsDB(DB_PATH).set_scheduler_status("next_analysis", job.next_run_time.isoformat())
        except Exception:
            pass

    scheduler.add_job(_collectors, "interval", hours=1, id="collectors")
    scheduler.add_job(_analysis, "interval", hours=6, id="analysis")

    db.write_log("调度器已启动，采集：每小时，分析：每6小时", "INFO", "scheduler")

    log.info("Scheduler started. Collectors: hourly. Analysis: every 6 hours.")
    log.info("Running initial collection...")
    _collectors()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")
```

将原来的 `scheduler.add_job(run_collectors, ...)` 和 `scheduler.add_job(run_analysis, ...)` 替换为上面的包装版本。

**Step 4: governor.py 写执行日志**

在 `src/governor.py` 的 `execute_task` 方法中，在 `subprocess.run` 前后：

```python
self.db.write_log(f"开始执行任务 #{task_id}：{task.get('action','')[:50]}", "INFO", "governor")
# ... subprocess.run ...
self.db.write_log(f"任务 #{task_id} {status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
```

**Step 5: 验证**

```bash
cd D:/Agent/orchestrator
python3 -c "
from src.scheduler import run_collectors
from src.storage.events_db import EventsDB
run_collectors()
db = EventsDB('events.db')
logs = db.get_logs(limit=10)
for l in logs[-5:]:
    print(f'[{l[\"source\"]}] {l[\"message\"]}')
"
```

Expected: 看到 collector 日志输出。

**Step 6: Commit**

```bash
cd D:/Agent/orchestrator
git add src/scheduler.py src/governor.py
git commit -m "feat: instrument scheduler and governor to write structured logs"
```

---

### Task 3: Node 后端——`/api/schedule-status` 和 `/api/logs` SSE

**Files:**
- Modify: `orchestrator/dashboard/server.js`

**Step 1: 添加 `/api/schedule-status` 端点**

在 `/api/stats` 之后添加：

```javascript
app.get('/api/schedule-status', (req, res) => {
  const db = getDb();
  if (!db) return res.json({ next_collectors: null, next_analysis: null, running_task: false });
  try {
    const statusRows = dbAll(db, "SELECT key, value FROM scheduler_status");
    const status = Object.fromEntries(statusRows.map(r => [r.key, r.value]));
    const running = dbAll(db, "SELECT id FROM tasks WHERE status = 'running' LIMIT 1");
    res.json({
      next_collectors: status.next_collectors || null,
      next_analysis: status.next_analysis || null,
      running_task: running.length > 0
    });
  } catch {
    res.json({ next_collectors: null, next_analysis: null, running_task: false });
  } finally {
    db.close();
  }
});
```

**Step 2: 添加 `/api/logs` SSE 端点**

SSE 原理：保持 HTTP 连接打开，每隔 1 秒轮询 DB，推送新日志行。

```javascript
// SSE log stream: polls DB every 1s, pushes new log rows since last_id
app.get('/api/logs', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  let lastId = 0;

  // Send initial backlog (last 50 logs)
  const initDb = getDb();
  if (initDb) {
    try {
      const rows = dbAll(initDb, 'SELECT * FROM logs ORDER BY id DESC LIMIT 50').reverse();
      if (rows.length) {
        lastId = rows[rows.length - 1].id;
        res.write(`data: ${JSON.stringify({ type: 'backlog', logs: rows })}\n\n`);
      }
    } catch { /* logs table may not exist yet */ }
    finally { initDb.close(); }
  }

  const interval = setInterval(() => {
    const db = getDb();
    if (!db) return;
    try {
      const rows = dbAll(db, 'SELECT * FROM logs WHERE id > ? ORDER BY id ASC LIMIT 50', [lastId]);
      if (rows.length) {
        lastId = rows[rows.length - 1].id;
        res.write(`data: ${JSON.stringify({ type: 'append', logs: rows })}\n\n`);
      }
    } catch { /* ignore */ }
    finally { db.close(); }
  }, 1000);

  req.on('close', () => clearInterval(interval));
});
```

**Step 3: 验证 SSE 端点语法**

```bash
cd D:/Agent/orchestrator/dashboard
node -e "require('./server.js'); console.log('OK');" 2>&1 | head -3
```

**Step 4: Commit**

```bash
cd D:/Agent/orchestrator
git add dashboard/server.js
git commit -m "feat: add /api/schedule-status and /api/logs SSE endpoint"
```

---

### Task 4: 前端——顶部 sticky 状态栏

**Files:**
- Modify: `orchestrator/dashboard/public/index.html`

**Step 1: 把 `<h1>` 替换为 sticky header**

找到：
```html
<h1>Orchestrator · Life Observer</h1>
<div class="grid">
```

替换为：
```html
<header id="top-bar">
  <span id="top-title">Orchestrator · Life Observer</span>
  <div id="top-status">
    <span id="top-collect" class="top-item" title="下次采集">采集 —</span>
    <span id="top-analyze" class="top-item" title="下次分析">分析 —</span>
    <span id="top-governor" class="top-item hidden" title="Governor 执行中">● 执行中</span>
    <span id="dot">◉ 连接中</span>
  </div>
</header>
<div class="grid">
```

**Step 2: 添加 CSS**

在 `<style>` 块末尾加：

```css
/* Top bar */
#top-bar {
  position: sticky; top: 0; z-index: 50;
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 0 16px; margin-bottom: 8px;
  background: #0a0a0a;
  border-bottom: 1px solid #141414;
}
#top-title { font-size: 0.75rem; color: #444; letter-spacing: 2px; text-transform: uppercase; }
#top-status { display: flex; align-items: center; gap: 16px; }
.top-item { font-size: 0.65rem; color: #333; letter-spacing: 0.5px; }
.top-item.active { color: #4a7a4a; }
.top-item.running { color: #7a3a3a; animation: blink 1.2s ease-in-out infinite; }
.top-item.hidden { display: none; }
@keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
#dot { position: static; font-size: 0.6rem; color: #2a2a2a; }
```

**Step 3: 添加状态栏更新 JS**

在 `load()` 函数后加：

```javascript
async function loadScheduleStatus() {
  try {
    const s = await fetch('/api/schedule-status').then(r => r.json());

    // 下次采集倒计时
    if (s.next_collectors) {
      const secs = Math.max(0, Math.round((new Date(s.next_collectors) - Date.now()) / 1000));
      const mins = Math.floor(secs / 60);
      document.getElementById('top-collect').textContent = secs > 0
        ? `采集 ${mins}分${secs % 60}秒后`
        : '采集 即将开始';
    }

    // 下次分析倒计时
    if (s.next_analysis) {
      const secs = Math.max(0, Math.round((new Date(s.next_analysis) - Date.now()) / 1000));
      const hrs = Math.floor(secs / 3600);
      const mins = Math.floor((secs % 3600) / 60);
      document.getElementById('top-analyze').textContent = secs > 0
        ? `分析 ${hrs > 0 ? hrs + '时' : ''}${mins}分后`
        : '分析 即将开始';
    }

    // Governor 状态
    const govEl = document.getElementById('top-governor');
    if (s.running_task) {
      govEl.classList.remove('hidden');
      govEl.classList.add('running');
    } else {
      govEl.classList.add('hidden');
      govEl.classList.remove('running');
    }
  } catch (e) {
    console.error('loadScheduleStatus error:', e);
  }
}

loadScheduleStatus();
setInterval(loadScheduleStatus, 15000);
```

**Step 4: 把原来的 `#dot` 从 `<body>` 移除**（已移入 header）

删除：
```html
<div id="dot">◉ 连接中</div>
```

**Step 5: Commit**

```bash
cd D:/Agent/orchestrator
git add dashboard/public/index.html
git commit -m "feat: add sticky status bar with schedule countdown and governor status"
```

---

### Task 5: 前端——任务卡片全中文 + 可展开 + 时间线

**Files:**
- Modify: `orchestrator/dashboard/public/index.html`

**Step 1: 添加 CSS**

在 `<style>` 末尾加：

```css
/* Enhanced task cards */
.task-card { cursor: pointer; transition: background 0.15s; }
.task-card:hover { background: #131313; border-radius: 4px; }
.task-expand { display: none; margin-top: 10px; padding-top: 10px; border-top: 1px solid #161616; }
.task-expand.open { display: block; }
.task-timeline { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 6px; }
.task-time-item { font-size: 0.65rem; color: #333; }
.task-time-label { color: #2a2a2a; }
.task-spec-grid { display: grid; gap: 6px; margin-top: 8px; }
.task-spec-row { font-size: 0.75rem; }
.task-spec-key { color: #2e2e2e; font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.5px; }
.task-spec-val { color: #666; margin-top: 1px; line-height: 1.5; }
/* Running pulse */
.pulse-running {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: #3a7a3a;
  margin-right: 5px; vertical-align: middle;
  animation: pulse-run 1s ease-in-out infinite;
}
@keyframes pulse-run { 0%,100% { opacity:1;transform:scale(1) } 50% { opacity:0.4;transform:scale(0.7) } }
```

**Step 2: 重写 `loadTasks` 函数中的卡片渲染**

优先级、来源、状态全部中文化，加展开逻辑：

```javascript
const PRIORITY_ZH = { high: '高', medium: '中', low: '低' };
const SOURCE_ZH = { auto: '自动', manual: '手动' };
const STATUS_ZH = { pending: '待执行', awaiting_approval: '待确认', running: '执行中', done: '完成', failed: '失败' };

function fmtDuration(startedAt, finishedAt) {
  if (!startedAt) return '';
  const start = new Date(startedAt);
  const end = finishedAt ? new Date(finishedAt) : new Date();
  const secs = Math.round((end - start) / 1000);
  if (secs < 60) return `${secs}秒`;
  return `${Math.floor(secs / 60)}分${secs % 60}秒`;
}

function fmtTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function taskCardHtml(t) {
  const spec = t.spec || {};
  const isRunning = t.status === 'running';
  const specFields = [
    ['问题描述', spec.problem],
    ['行为链', spec.behavior_chain],
    ['观察结果', spec.observation],
    ['预期结果', spec.expected],
    ['重要性', spec.importance],
  ].filter(([, v]) => v);

  const specHtml = specFields.map(([k, v]) => `
    <div class="task-spec-row">
      <div class="task-spec-key">${esc(k)}</div>
      <div class="task-spec-val">${esc(v)}</div>
    </div>
  `).join('');

  const timeline = `
    <div class="task-timeline">
      <span class="task-time-item"><span class="task-time-label">创建 </span>${fmtTime(t.created_at)}</span>
      ${t.approved_at ? `<span class="task-time-item"><span class="task-time-label">确认 </span>${fmtTime(t.approved_at)}</span>` : ''}
      ${t.started_at ? `<span class="task-time-item"><span class="task-time-label">开始 </span>${fmtTime(t.started_at)}</span>` : ''}
      ${t.finished_at ? `<span class="task-time-item"><span class="task-time-label">完成 </span>${fmtTime(t.finished_at)}</span>` : ''}
      ${t.started_at ? `<span class="task-time-item"><span class="task-time-label">用时 </span>${fmtDuration(t.started_at, t.finished_at)}</span>` : ''}
    </div>
  `;

  return `
    <div class="task-card" onclick="toggleTask(${t.id})" id="task-card-${t.id}">
      <div class="task-summary">
        ${isRunning ? '<span class="pulse-running"></span>' : ''}
        ${statusBadge(t.status)}${esc(spec.summary || t.action)}
        ${t.status === 'awaiting_approval'
          ? `<button class="btn-exec" onclick="event.stopPropagation();openModal(${t.id})">查看 + 执行</button>`
          : ''}
      </div>
      <div class="task-meta">
        优先级：${PRIORITY_ZH[t.priority] || t.priority} · 来源：${SOURCE_ZH[t.source] || t.source} · ${(t.created_at || '').slice(0, 10)}
      </div>
      <div class="task-expand" id="task-expand-${t.id}">
        ${timeline}
        ${specHtml ? `<div class="task-spec-grid">${specHtml}</div>` : ''}
        ${t.output ? `<div class="task-output" style="margin-top:8px">${esc(t.output.slice(0, 600))}</div>` : ''}
      </div>
    </div>
  `;
}

function toggleTask(id) {
  const el = document.getElementById(`task-expand-${id}`);
  if (el) el.classList.toggle('open');
}

async function loadTasks() {
  try {
    const tasks = await fetch('/api/tasks').then(r => r.json());
    const el = document.getElementById('tasks-list');
    if (!tasks.length) { el.innerHTML = '<span class="no-data">暂无任务</span>'; return; }
    // preserve open state
    const openIds = new Set([...document.querySelectorAll('.task-expand.open')]
      .map(e => e.id.replace('task-expand-', '')));
    el.innerHTML = tasks.map(taskCardHtml).join('');
    openIds.forEach(id => {
      const el = document.getElementById(`task-expand-${id}`);
      if (el) el.classList.add('open');
    });
  } catch (e) {
    console.error('loadTasks error:', e);
  }
}
```

**Step 3: Commit**

```bash
cd D:/Agent/orchestrator
git add dashboard/public/index.html
git commit -m "feat: enhance task cards with Chinese labels, expand/collapse, timeline, running pulse"
```

---

### Task 6: 前端——实时日志面板（SSE）

**Files:**
- Modify: `orchestrator/dashboard/public/index.html`

**Step 1: 添加日志面板 HTML**

在 `</div><!-- close grid -->` 之后、`<!-- Manual execution modal -->` 之前加：

```html
<!-- Log Panel -->
<div class="card wide" id="log-card" style="margin-top:16px">
  <h2 style="display:flex;justify-content:space-between;align-items:center">
    实时日志
    <span style="display:flex;gap:8px;align-items:center">
      <span id="log-status" class="dim">连接中...</span>
      <button onclick="clearLogs()" style="font-size:0.6rem;padding:1px 6px;border-radius:2px;border:1px solid #1e1e1e;background:#0a0a0a;color:#333;cursor:pointer">清空</button>
    </span>
  </h2>
  <div id="log-list" class="custom-log-scroll" style="max-height:220px;overflow-y:auto;font-family:monospace"></div>
</div>
```

**Step 2: 添加 CSS**

```css
/* Log panel */
.log-line { font-size: 0.7rem; padding: 2px 0; border-bottom: 1px solid #0e0e0e; display: flex; gap: 8px; line-height: 1.5; }
.log-line:last-child { border-bottom: none; }
.log-ts { color: #222; white-space: nowrap; flex-shrink: 0; }
.log-src { color: #2a3a2a; min-width: 60px; }
.log-msg { color: #555; }
.log-msg.ERROR { color: #5a2a2a; }
.log-msg.WARN { color: #5a4a2a; }
.log-msg.INFO { color: #555; }
.custom-log-scroll::-webkit-scrollbar { width: 3px; }
.custom-log-scroll::-webkit-scrollbar-thumb { background: #1a1a1a; border-radius: 2px; }
```

**Step 3: 添加 SSE JS**

```javascript
// ── Log stream (SSE) ─────────────────────────────────────────
let logCount = 0;
const MAX_LOG_LINES = 200;

function appendLogs(logs) {
  const container = document.getElementById('log-list');
  logs.forEach(l => {
    const div = document.createElement('div');
    div.className = 'log-line';
    const ts = (l.created_at || '').slice(11, 19);
    div.innerHTML = `<span class="log-ts">${ts}</span><span class="log-src">${esc(l.source)}</span><span class="log-msg ${l.level}">${esc(l.message)}</span>`;
    container.appendChild(div);
    logCount++;
  });
  // trim old lines
  while (container.children.length > MAX_LOG_LINES) {
    container.removeChild(container.firstChild);
  }
  // auto-scroll to bottom
  container.scrollTop = container.scrollHeight;
}

function clearLogs() {
  document.getElementById('log-list').innerHTML = '';
  logCount = 0;
}

function connectLogStream() {
  const evtSource = new EventSource('/api/logs');
  document.getElementById('log-status').textContent = '已连接';

  evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'backlog' || data.type === 'append') {
      appendLogs(data.logs);
    }
  };

  evtSource.onerror = () => {
    document.getElementById('log-status').textContent = '重连中...';
  };
}

connectLogStream();
```

**Step 4: Commit**

```bash
cd D:/Agent/orchestrator
git add dashboard/public/index.html
git commit -m "feat: add real-time log panel with SSE streaming"
```

---

### Task 7: 重建 Docker 验证

**Step 1: 重建**

```bash
cd D:/Agent/orchestrator
docker compose down
docker compose build --no-cache
docker compose up -d
```

**Step 2: 验证日志表**

```bash
docker exec orchestrator python3 -c "
from src.storage.events_db import EventsDB
db = EventsDB('events.db')
print('tables:', db.get_tables())
db.write_log('Docker 验证日志', 'INFO', 'test')
logs = db.get_logs()
print('log count:', len(logs))
"
```

**Step 3: 验证 SSE 端点**

```bash
curl -N http://localhost:23714/api/logs &
sleep 3
kill %1
```
Expected: 看到 `data: {"type":"backlog",...}` 格式的 SSE 流。

**Step 4: 验证调度状态**

```bash
curl -s http://localhost:23714/api/schedule-status | python3 -m json.tool
```
Expected: `{"next_collectors": ..., "next_analysis": ..., "running_task": false}`

**Step 5: 打开 http://localhost:23714 确认**
- 顶部状态栏可见
- 任务卡片可点击展开，标签全中文
- 日志面板显示实时流
