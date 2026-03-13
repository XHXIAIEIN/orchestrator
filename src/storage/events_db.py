import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


_ALLOWED_TASK_COLUMNS = {
    'spec', 'action', 'reason', 'priority', 'source',
    'status', 'output', 'approved_at', 'started_at', 'finished_at',
    'scrutiny_note',
}


class EventsDB:
    def __init__(self, db_path: str = "events.db"):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
                    finished_at TEXT
                );

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

                CREATE TABLE IF NOT EXISTS profile_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'periodic',
                    generated_at TEXT NOT NULL
                );
            """)
            # Migration: add scrutiny_note column to existing databases
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN scrutiny_note TEXT")
            except Exception:
                pass  # Column already exists

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
                    spec: dict, source: str = 'auto') -> int:
        now = datetime.now(timezone.utc).isoformat()
        status = 'pending' if source == 'auto' else 'awaiting_approval'
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tasks (spec, action, reason, priority, source, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (json.dumps(spec, ensure_ascii=False, default=str), action, reason, priority, source, status, now)
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
