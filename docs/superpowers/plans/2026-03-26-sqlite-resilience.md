# SQLite Resilience — 消除 database-is-locked 死锁

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 SQLite 在 Docker NTFS bind-mount + DELETE journal 模式下的 "database is locked" 死锁，让系统在 15+ 并发写入者下稳定运行。

**Architecture:** 三层修复：(1) EventsDB 连接池加 retry-with-backoff 让锁等待可恢复；(2) Chat DB 加连接池+缓存 ALTER TABLE 检查消除热路径上的重锁；(3) Dashboard busy_timeout 对齐 + 把 spawn python 的短命写操作改为 Node.js 直写。

**Tech Stack:** Python sqlite3, better-sqlite3 (Node.js), threading

**根因分析：**
- `_ConnPool.connect()` 在 `database is locked` 时 recycle 连接但 **不重试**——调用方直接拿到异常
- Chat DB 每次 `save_message()` 都新建连接 + 两次 ALTER TABLE 探测，无池化无序列化
- Dashboard `better-sqlite3` busy_timeout 只有 5s（Python 侧 30s），超时后 Node 释放锁时 Python 连接已被标记为 error
- Dashboard 7 处 `spawn('python3')` 创建独立 EventsDB 实例，绕过主进程的 threading.Lock

---

### Task 1: EventsDB _ConnPool — 加 retry-with-backoff

**Files:**
- Modify: `src/storage/events_db.py:46-68`

这是最高优先级修复。当前 `connect()` 遇到 `database is locked` 只 recycle 连接然后 re-raise。加 3 次重试 + 指数退避。

- [ ] **Step 1: 修改 `_ConnPool.connect()` 加重试逻辑**

```python
# src/storage/events_db.py — 替换整个 connect 方法

import time as _time  # 加到文件顶部 imports

# _ConnPool 类内：
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5  # seconds

@contextmanager
def connect(self):
    """Yield the shared connection under the serialisation lock.

    Retries up to _MAX_RETRIES times on 'database is locked' with
    exponential backoff before giving up.
    """
    last_exc = None
    for attempt in range(self._MAX_RETRIES + 1):
        if attempt > 0:
            delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
            log.info(f"events_db: retry {attempt}/{self._MAX_RETRIES} after {delay:.1f}s")
            _time.sleep(delay)
        with self.lock:
            if self._conn is None:
                self._conn = self._raw_connect()
            try:
                with self._conn:  # sqlite3 auto-commit / rollback
                    yield self._conn
                    return  # success — exit retry loop
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "database is locked" in str(exc) or "disk I/O error" in str(exc):
                    log.warning(f"events_db: {exc} (attempt {attempt + 1}/{self._MAX_RETRIES + 1})")
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    if attempt < self._MAX_RETRIES:
                        continue  # retry
                raise
    raise last_exc  # all retries exhausted
```

- [ ] **Step 2: 验证——在容器内测试并发写入**

Run: `docker compose exec orchestrator python3 -c "
import threading, time
from src.storage.events_db import EventsDB
db = EventsDB('/orchestrator/data/events.db')
errors = []
def writer(i):
    try:
        db.write_log(f'concurrency test {i}', 'INFO', 'test')
    except Exception as e:
        errors.append(str(e))
threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
for t in threads: t.start()
for t in threads: t.join()
print(f'OK: 20 writes, {len(errors)} errors')
"`

Expected: `OK: 20 writes, 0 errors`

- [ ] **Step 3: Commit**

```bash
git add src/storage/events_db.py
git commit -m "fix(db): add retry-with-backoff to _ConnPool.connect() on database-locked"
```

---

### Task 2: Chat DB — 连接池 + ALTER TABLE 缓存

**Files:**
- Modify: `src/channels/chat/db.py` (全文重写)

当前问题：每次 `save_message()` 都 `sqlite3.connect()` 新建连接 + 两次 ALTER TABLE 探测。高频 chat 场景下这是锁竞争热点。

- [ ] **Step 1: 重写 chat/db.py — 加连接池和 migration 缓存**

```python
"""Chat DB persistence — message storage, memory, counts."""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone

from src.channels import config as ch_cfg

log = logging.getLogger(__name__)

# ── Connection pool (per db_path singleton) ──────────────────────────────────

_pool_lock = threading.Lock()
_pools: dict[str, "_ChatConnPool"] = {}


class _ChatConnPool:
    """Single-connection pool with threading lock — same pattern as EventsDB."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._migrated = False  # ALTER TABLE 只需要跑一次

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def get_conn(self) -> sqlite3.Connection:
        """Get or create the shared connection. Caller must hold self.lock."""
        if self._conn is None:
            self._conn = self._raw_connect()
        return self._conn

    def ensure_migrated(self, conn: sqlite3.Connection):
        """Run ALTER TABLE migrations once per pool lifetime."""
        if self._migrated:
            return
        for col, default in [("chat_client", "''"), ("media_paths", "''")]:
            try:
                conn.execute(f"SELECT {col} FROM chat_messages LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {col} TEXT DEFAULT {default}")
                conn.commit()
        self._migrated = True

    def recycle(self):
        """Close and reset connection on error."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


def _get_pool(db_path: str) -> "_ChatConnPool":
    with _pool_lock:
        if db_path not in _pools:
            _pools[db_path] = _ChatConnPool(db_path)
        return _pools[db_path]


# ── Public API (unchanged signatures) ───────────────────────────────────────

def save_message(db_path: str, chat_id: str, role: str, content: str,
                 chat_client: str = "", media_paths: list[str] | None = None):
    """存一条消息。含硬上限保护。media_paths: 关联的媒体文件路径列表。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        try:
            pool.ensure_migrated(conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()[0]
            if count >= ch_cfg.MAX_DB_MESSAGES:
                excess = count - ch_cfg.MAX_DB_MESSAGES + ch_cfg.DB_PRUNE_EXTRA
                conn.execute(
                    "DELETE FROM chat_messages WHERE id IN "
                    "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id ASC LIMIT ?)",
                    (chat_id, excess),
                )
            media_json = json.dumps(media_paths) if media_paths else ""
            conn.execute(
                "INSERT INTO chat_messages (chat_id, role, content, created_at, chat_client, media_paths) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, role, content, datetime.now(timezone.utc).isoformat(), chat_client, media_json),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc):
                pool.recycle()
            raise


def load_recent(db_path: str, chat_id: str, limit: int = 20) -> list[dict]:
    """从 DB 加载最近 N 轮对话。包含 media_paths（如果有）。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        pool.ensure_migrated(conn)
        rows = conn.execute(
            "SELECT role, content, media_paths FROM chat_messages "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    results = []
    for r in reversed(rows):
        msg = {"role": r[0], "content": r[1]}
        if r[2]:
            try:
                msg["media_paths"] = json.loads(r[2])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(msg)
    return results


def load_memory(db_path: str, chat_id: str) -> str:
    """加载摘要记忆。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        row = conn.execute(
            "SELECT summary FROM chat_memory WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return row[0] if row else ""


def save_memory(db_path: str, chat_id: str, summary: str):
    """保存摘要记忆。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        try:
            conn.execute(
                "INSERT INTO chat_memory (chat_id, summary, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET summary = ?, updated_at = ?",
                (chat_id, summary, datetime.now(timezone.utc).isoformat(),
                 summary, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc):
                pool.recycle()
            raise


def count_messages(db_path: str, chat_id: str) -> int:
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        return conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
```

- [ ] **Step 2: Commit**

```bash
git add src/channels/chat/db.py
git commit -m "fix(chat-db): add connection pooling + cache ALTER TABLE migrations"
```

---

### Task 3: Dashboard — busy_timeout 对齐 30s

**Files:**
- Modify: `dashboard/server.js:55`

Dashboard 的 `busy_timeout = 5000` 远低于 Python 侧的 30000ms。当 Python 持锁写入时 Node.js 5 秒就放弃，然后 Node 的下一次读取又抢锁，形成恶性循环。

- [ ] **Step 1: 修改 busy_timeout**

```javascript
// dashboard/server.js:55
// 旧：_db.pragma('busy_timeout = 5000');
// 新：
_db.pragma('busy_timeout = 30000');
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/server.js
git commit -m "fix(dashboard): align busy_timeout to 30s matching Python side"
```

---

### Task 4: Dashboard — 把 create_task spawn 改为 better-sqlite3 直写

**Files:**
- Modify: `dashboard/server.js:183-218`

`POST /api/tasks` 是 dashboard 最频繁的写操作。当前 spawn python3 创建独立 EventsDB 实例，绕过主进程的连接池。改为 better-sqlite3 直写，消除跨进程锁竞争。

- [ ] **Step 1: 用 better-sqlite3 替换 spawn**

```javascript
// dashboard/server.js — 替换 POST /api/tasks handler
app.post('/api/tasks', (req, res) => {
  const { action, reason, priority, spec } = req.body || {};
  if (!action) return res.status(400).json({ error: 'action is required' });

  const db = ensureDb();
  if (!db) return res.status(500).json({ error: 'database not available' });

  try {
    const now = new Date().toISOString();
    const result = db.prepare(`
      INSERT INTO tasks (action, reason, priority, spec, status, source, created_at)
      VALUES (?, ?, ?, ?, 'pending', 'manual', ?)
    `).run(
      action,
      reason || '',
      priority || 'medium',
      JSON.stringify(spec || {}),
      now
    );
    res.json({ id: Number(result.lastInsertRowid) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/server.js
git commit -m "fix(dashboard): replace spawn-python with direct sqlite write for create_task"
```

---

### Task 5: 老 chat.py 兼容清理（容器内残留）

**Files:**
- Check: `src/channels/chat.py` (git status 显示 deleted)

git status 显示 `D src/channels/chat.py`，但容器内还在用旧文件（13 小时前构建）。traceback 显示 `src/channels/chat.py:166 _ensure_chat_client_column` 报错。

确认新代码（`src/channels/chat/` 目录）的 import 路径已经被所有调用方使用。

- [ ] **Step 1: 确认所有 import 已迁移到新路径**

Run: `grep -r "from src.channels.chat import" src/ --include="*.py" | grep -v __pycache__ | grep -v "chat/"` 和 `grep -r "from src.channels import chat" src/ --include="*.py" | grep -v __pycache__`

Expected: 无结果（所有 import 都应该指向 `src.channels.chat.xxx` 而非旧的 `src.channels.chat`）

- [ ] **Step 2: 重建容器使新代码生效**

```bash
docker compose build --no-cache && docker compose up -d
```

- [ ] **Step 3: 观察 5 分钟日志确认无 locked 错误**

```bash
docker compose logs -f --tail=0 2>&1 | head -50
```

Expected: 无 `database is locked` 错误

- [ ] **Step 4: Commit（如果有 import 修改）**

---

## 未来可选优化（不在本次范围）

1. **Dashboard 所有 spawn python 写操作 → 直写**：approval、scenario run 等 7 处 spawn 都可以改，但它们频率低，优先级不高
2. **SQLite → PostgreSQL**：如果并发继续增长（>20 个写入者），SQLite 的文件级锁根本不够用。但目前 9.5MB 的 DB 没必要
3. **Watchdog 自愈**：加一个定时检测连续 N 次 DB locked 后自动 recycle 所有连接池的守护线程
