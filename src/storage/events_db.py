import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


_ALLOWED_TASK_COLUMNS = {
    'spec', 'action', 'reason', 'priority', 'source',
    'status', 'output', 'approved_at', 'started_at', 'finished_at',
    'scrutiny_note', 'parent_task_id',
}


_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "events.db")


class EventsDB:
    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # WAL fails on Docker bind-mounts (WSL2 + NTFS), fall back to DELETE
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.OperationalError:
            pass
        return conn

    def _connect_safe(self):
        """Fallback connection that avoids WAL entirely — for Docker bind-mount environments."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    duration_minutes REAL DEFAULT 0,
                    score REAL DEFAULT 0.5,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    dedup_key TEXT UNIQUE,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
                CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);

                CREATE TABLE IF NOT EXISTS daily_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spec TEXT NOT NULL DEFAULT '{}',
                    action TEXT NOT NULL,
                    reason TEXT,
                    priority TEXT DEFAULT 'medium',
                    source TEXT DEFAULT 'auto',
                    status TEXT DEFAULT 'pending',
                    output TEXT,
                    scrutiny_note TEXT,
                    created_at TEXT NOT NULL,
                    approved_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    parent_task_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL DEFAULT 'INFO',
                    source TEXT NOT NULL DEFAULT 'system',
                    message TEXT NOT NULL,
                    run_id TEXT,
                    step TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduler_status (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'periodic',
                    generated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attention_debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    project TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    severity TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'open',
                    context TEXT,
                    resolved_by TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE(session_id, summary)
                );
                CREATE INDEX IF NOT EXISTS idx_debts_status ON attention_debts(status);

                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    instance TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(date, summary)
                );
                CREATE INDEX IF NOT EXISTS idx_experiences_date ON experiences(date);

                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_events_task ON agent_events(task_id);

                CREATE TABLE IF NOT EXISTS collector_reputation (
                    name TEXT PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    department TEXT NOT NULL,
                    task_id INTEGER,
                    mode TEXT NOT NULL DEFAULT 'auto',
                    summary TEXT NOT NULL,
                    files_changed TEXT NOT NULL DEFAULT '[]',
                    commit_hash TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'done',
                    duration_s INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    hash TEXT NOT NULL,
                    prev_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_run_logs_dept ON run_logs(department);
                CREATE INDEX IF NOT EXISTS idx_run_logs_created ON run_logs(created_at);

                CREATE TABLE IF NOT EXISTS sub_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    stage_name TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    output_preview TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sub_runs_task ON sub_runs(task_id);

                CREATE TABLE IF NOT EXISTS task_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    session_data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, agent_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_task ON task_sessions(task_id);

                CREATE TABLE IF NOT EXISTS heartbeats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'alive',
                    progress_pct INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_heartbeats_task ON heartbeats(task_id);

                CREATE TABLE IF NOT EXISTS file_index (
                    path TEXT PRIMARY KEY,
                    routing_hint TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    embedding TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_msg_chat ON chat_messages(chat_id, created_at);

                CREATE TABLE IF NOT EXISTS chat_memory (
                    chat_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_key TEXT NOT NULL,
                    area TEXT NOT NULL DEFAULT 'general',
                    rule TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'error',
                    status TEXT NOT NULL DEFAULT 'pending',
                    recurrence INTEGER NOT NULL DEFAULT 1,
                    department TEXT,
                    task_id INTEGER,
                    created_at TEXT NOT NULL,
                    promoted_at TEXT,
                    retired_at TEXT,
                    UNIQUE(pattern_key)
                );
                CREATE INDEX IF NOT EXISTS idx_learnings_status ON learnings(status);
                CREATE INDEX IF NOT EXISTS idx_learnings_area ON learnings(area);
                CREATE INDEX IF NOT EXISTS idx_learnings_dept ON learnings(department);
            """)
            # Migrations: add columns to existing databases
            for col, typ in [("scrutiny_note", "TEXT"), ("parent_task_id", "INTEGER")]:
                try:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass  # Column already exists
            for col, typ in [("run_id", "TEXT"), ("step", "TEXT")]:
                try:
                    conn.execute(f"ALTER TABLE logs ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass
            # Deferred indexes (depend on migration columns)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_run_id ON logs(run_id)")
            except sqlite3.OperationalError:
                pass

    def get_tables(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row["name"] for row in rows]

    def insert_event(self, source: str, category: str, title: str,
                     duration_minutes: float, score: float, tags: list,
                     metadata: dict, dedup_key: str = None,
                     occurred_at: str = None) -> bool:
        ts = occurred_at or datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO events
                       (source, category, title, duration_minutes, score, tags, metadata, dedup_key, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source, category, title, duration_minutes, score,
                     json.dumps(tags, ensure_ascii=False),
                     json.dumps(metadata, ensure_ascii=False, default=str),
                     dedup_key, ts)
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_recent_events(self, days: int = 7, source: str = None) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            if source:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? AND source = ? ORDER BY occurred_at DESC",
                    (since, source)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE occurred_at >= ? ORDER BY occurred_at DESC",
                    (since,)
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def get_size_bytes(self) -> int:
        path = Path(self.db_path)
        return path.stat().st_size if path.exists() else 0

    def save_daily_summary(self, date: str, summary: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_summaries (date, summary, created_at) VALUES (?, ?, ?)",
                (date, summary, now)
            )

    def save_user_profile(self, profile: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO user_profile (profile_json, updated_at) VALUES (?, ?)",
                (json.dumps(profile, ensure_ascii=False), now)
            )

    def save_insights(self, data: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO insights (data_json, generated_at) VALUES (?, ?)",
                (json.dumps(data, ensure_ascii=False), now)
            )

    def get_latest_insights(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM insights ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["data_json"]) if row else {}

    def get_daily_summaries(self, days: int = 7) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, summary FROM daily_summaries WHERE date >= ? ORDER BY date DESC",
                (since,)
            ).fetchall()
        result = []
        for r in rows:
            try:
                result.append({"date": r["date"], **json.loads(r["summary"])})
            except Exception:
                pass
        return result

    def get_latest_profile(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM user_profile ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["profile_json"]) if row else {}

    def create_task(self, action: str, reason: str, priority: str,
                    spec: dict, source: str = 'auto',
                    parent_task_id: int = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        status = 'pending' if source == 'auto' else 'awaiting_approval'
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tasks (spec, action, reason, priority, source, status, created_at, parent_task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (json.dumps(spec, ensure_ascii=False, default=str), action, reason, priority, source, status, now,
                 parent_task_id)
            )
            return cur.lastrowid

    def update_task(self, task_id: int, **kwargs):
        if not kwargs:
            return
        invalid = set(kwargs) - _ALLOWED_TASK_COLUMNS
        if invalid:
            raise ValueError(f"Invalid task columns: {invalid}")
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

    def get_task(self, task_id: int):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['spec'] = json.loads(d['spec'])
        return d

    def write_log(self, message: str, level: str = 'INFO', source: str = 'system',
                  run_id: str = None, step: str = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO logs (level, source, message, run_id, step, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (level, source, message, run_id, step, now)
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

    def get_running_task(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('running', 'scrutinizing') LIMIT 1"
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d['spec'] = json.loads(d['spec'])
        return d

    def get_running_tasks(self) -> list:
        """返回所有正在运行或审查中的任务。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('running', 'scrutinizing')"
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d['spec'] = json.loads(d['spec'])
            result.append(d)
        return result

    def count_running_tasks(self) -> int:
        """返回正在运行的任务数。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('running', 'scrutinizing')"
            ).fetchone()
        return row[0]

    def save_profile_analysis(self, data: dict, analysis_type: str = 'periodic'):
        now = datetime.now(timezone.utc).isoformat()
        data_copy = dict(data)
        data_copy['generated_at'] = now
        data_copy['type'] = analysis_type
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO profile_analysis (data_json, type, generated_at) VALUES (?, ?, ?)",
                (json.dumps(data_copy, ensure_ascii=False), analysis_type, now)
            )
            conn.execute(
                "DELETE FROM profile_analysis WHERE id NOT IN "
                "(SELECT id FROM profile_analysis ORDER BY id DESC LIMIT 50)"
            )

    def get_profile_analysis(self, analysis_type: str = None) -> dict:
        with self._connect() as conn:
            if analysis_type:
                row = conn.execute(
                    "SELECT data_json FROM profile_analysis WHERE type = ? ORDER BY id DESC LIMIT 1",
                    (analysis_type,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT data_json FROM profile_analysis ORDER BY id DESC LIMIT 1"
                ).fetchone()
        return json.loads(row["data_json"]) if row else {}

    def get_events_by_day(self, days: int = 60) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DATE(occurred_at) as day, COUNT(*) as count "
                "FROM events WHERE occurred_at >= ? GROUP BY DATE(occurred_at) ORDER BY day ASC",
                (since,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_category(self, days: int = 7) -> list:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, SUM(duration_minutes) as total_min, COUNT(*) as count "
                "FROM events WHERE occurred_at >= ? GROUP BY category ORDER BY total_min DESC",
                (since,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Experiences ──

    def add_experience(self, date: str, type: str, summary: str, detail: str, instance: str = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO experiences (date, type, summary, detail, instance, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (date, type, summary, detail, instance, now)
            )
            return cursor.lastrowid

    def get_recent_experiences(self, n: int = 10) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, type, summary, detail, instance FROM experiences "
                "ORDER BY date DESC, id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_experiences_by_type(self, type: str, n: int = 20) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, type, summary, detail, instance FROM experiences "
                "WHERE type = ? ORDER BY date DESC LIMIT ?",
                (type, n)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_experiences(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]

    # ── Agent Events ──

    def add_agent_event(self, task_id: int, event_type: str, data: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_events (task_id, event_type, data, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, json.dumps(data, ensure_ascii=False, default=str), now)
            )
            return cursor.lastrowid

    def get_agent_events(self, task_id: int, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, task_id, event_type, data, created_at FROM agent_events "
                "WHERE task_id = ? ORDER BY id ASC LIMIT ?",
                (task_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_live_agent_events(self, since_id: int = 0, limit: int = 50) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, task_id, event_type, data, created_at FROM agent_events "
                "WHERE id > ? ORDER BY id ASC LIMIT ?",
                (since_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Run Logs (hash-chained) ──

    def get_last_run_hash(self, department: str = None) -> str:
        """获取最后一条 run_log 的 hash，用于构建哈希链。"""
        with self._connect() as conn:
            if department:
                row = conn.execute(
                    "SELECT hash FROM run_logs WHERE department = ? ORDER BY id DESC LIMIT 1",
                    (department,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT hash FROM run_logs ORDER BY id DESC LIMIT 1"
                ).fetchone()
        return row["hash"] if row else ""

    def append_run_log(self, department: str, task_id: int, mode: str,
                       summary: str, files_changed: list, commit_hash: str,
                       status: str, duration_s: int, notes: str,
                       entry_hash: str, prev_hash: str,
                       created_at: str = None) -> int:
        ts = created_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO run_logs "
                "(department, task_id, mode, summary, files_changed, commit_hash, "
                " status, duration_s, notes, hash, prev_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (department, task_id, mode, summary,
                 json.dumps(files_changed, ensure_ascii=False),
                 commit_hash, status, duration_s, notes,
                 entry_hash, prev_hash, ts)
            )
            return cursor.lastrowid

    def get_recent_run_logs(self, department: str, n: int = 5) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_logs WHERE department = ? "
                "ORDER BY id DESC LIMIT ?",
                (department, n)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["files_changed"] = json.loads(d["files_changed"])
            result.append(d)
        result.reverse()
        return result

    def get_all_run_logs(self, department: str = None,
                         limit: int = 100) -> list:
        with self._connect() as conn:
            if department:
                rows = conn.execute(
                    "SELECT * FROM run_logs WHERE department = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (department, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM run_logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["files_changed"] = json.loads(d["files_changed"])
            result.append(d)
        return result

    def get_department_run_stats(self) -> dict:
        """返回每个部门的运行统计：总数、成功率、最近记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT department, COUNT(*) as total, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as success_count "
                "FROM run_logs GROUP BY department"
            ).fetchall()
        stats = {}
        for row in rows:
            d = dict(row)
            dept = d["department"]
            stats[dept] = {
                "total": d["total"],
                "success_count": d["success_count"],
                "success_rate": round(d["success_count"] / d["total"], 2) if d["total"] > 0 else 0,
            }
        return stats

    # ── Sub-runs (per-stage tracking) ──

    def create_sub_run(self, task_id: int, stage_name: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sub_runs (task_id, stage_name, status, started_at, created_at) "
                "VALUES (?, ?, 'running', ?, ?)",
                (task_id, stage_name, now, now)
            )
            return cursor.lastrowid

    def finish_sub_run(self, sub_run_id: int, status: str,
                       duration_ms: int = 0, cost_usd: float = 0,
                       output_preview: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sub_runs SET status = ?, finished_at = ?, "
                "duration_ms = ?, cost_usd = ?, output_preview = ? WHERE id = ?",
                (status, now, duration_ms, cost_usd, output_preview[:500], sub_run_id)
            )

    def get_sub_runs(self, task_id: int) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sub_runs WHERE task_id = ? ORDER BY id ASC",
                (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Task Sessions (cross-heartbeat context recovery) ──

    def save_session(self, task_id: int, agent_id: str, session_data: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_sessions "
                "(task_id, agent_id, session_data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, agent_id, json.dumps(session_data, ensure_ascii=False, default=str),
                 now, now)
            )

    def get_session(self, task_id: int, agent_id: str = "") -> dict:
        with self._connect() as conn:
            if agent_id:
                row = conn.execute(
                    "SELECT session_data FROM task_sessions "
                    "WHERE task_id = ? AND agent_id = ?",
                    (task_id, agent_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT session_data FROM task_sessions WHERE task_id = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (task_id,)
                ).fetchone()
        return json.loads(row["session_data"]) if row else {}

    # ── Heartbeats ──

    def record_heartbeat(self, task_id: int, agent_id: str = "",
                         status: str = "alive", progress_pct: int = 0,
                         message: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO heartbeats (task_id, agent_id, status, progress_pct, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, agent_id, status, progress_pct, message, now)
            )
            return cursor.lastrowid

    def get_last_heartbeat(self, task_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM heartbeats WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,)
            ).fetchone()
        return dict(row) if row else {}

    # ── File Index (CAFI) ──

    def upsert_file_index(self, path: str, routing_hint: str,
                          tags: list, embedding: list = None):
        now = datetime.now(timezone.utc).isoformat()
        emb_json = json.dumps(embedding) if embedding else None
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO file_index (path, routing_hint, tags, embedding, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, routing_hint, json.dumps(tags), emb_json, now)
            )

    def query_file_index(self, tags: list = None, limit: int = 20) -> list:
        with self._connect() as conn:
            if tags:
                # 简单 tag 匹配（JSON 字符串包含检查）
                placeholders = " OR ".join(["tags LIKE ?"] * len(tags))
                params = [f"%{t}%" for t in tags] + [limit]
                rows = conn.execute(
                    f"SELECT path, routing_hint, tags FROM file_index "
                    f"WHERE {placeholders} ORDER BY updated_at DESC LIMIT ?",
                    params
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path, routing_hint, tags FROM file_index "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ── Learnings ──

    def add_learning(
        self,
        pattern_key: str,
        rule: str,
        *,
        area: str = "general",
        context: str = "",
        source_type: str = "error",
        department: str = None,
        task_id: int = None,
    ) -> int:
        """Record a learning. If pattern_key exists, bump recurrence instead."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, recurrence, status FROM learnings WHERE pattern_key = ?",
                (pattern_key,),
            ).fetchone()
            if existing:
                new_count = existing["recurrence"] + 1
                conn.execute(
                    "UPDATE learnings SET recurrence = ?, context = CASE WHEN ? != '' THEN ? ELSE context END WHERE id = ?",
                    (new_count, context, context, existing["id"]),
                )
                return existing["id"]
            cursor = conn.execute(
                "INSERT INTO learnings (pattern_key, area, rule, context, source_type, status, recurrence, department, task_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?)",
                (pattern_key, area, rule, context, source_type, department, task_id, now),
            )
            return cursor.lastrowid

    def promote_learning(self, learning_id: int) -> None:
        """Promote a learning to boot.md-eligible status."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'promoted', promoted_at = ? WHERE id = ?",
                (now, learning_id),
            )

    def retire_learning(self, learning_id: int) -> None:
        """Retire a learning (no longer relevant)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE learnings SET status = 'retired', retired_at = ? WHERE id = ?",
                (now, learning_id),
            )

    def get_learnings(self, status: str = None, area: str = None, department: str = None, limit: int = 50) -> list:
        """Query learnings with optional filters."""
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if area:
            clauses.append("area = ?")
            params.append(area)
        if department:
            clauses.append("department = ?")
            params.append(department)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, pattern_key, area, rule, context, source_type, status, recurrence, department, task_id, created_at, promoted_at "
                f"FROM learnings {where} ORDER BY recurrence DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_promoted_learnings(self) -> list:
        """Get all promoted learnings for boot.md compilation."""
        return self.get_learnings(status="promoted", limit=30)

    def get_learnings_for_dispatch(self, department: str = None, area: str = None) -> list:
        """Get active+promoted learnings relevant to a dispatch context."""
        clauses = ["status IN ('pending', 'promoted')"]
        params = []
        if department:
            clauses.append("(department = ? OR department IS NULL)")
            params.append(department)
        if area:
            clauses.append("area = ?")
            params.append(area)
        where = "WHERE " + " AND ".join(clauses)
        params.append(20)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT pattern_key, rule, recurrence, department FROM learnings {where} "
                f"ORDER BY recurrence DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
