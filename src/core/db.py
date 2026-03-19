import sqlite3
import json
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path: str = "orchestrator.db"):
        self.db_path = db_path
        self._init_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    initial_input TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS problems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    definition TEXT NOT NULL,
                    clarity_level TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
            """)

    def get_tables(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return [row["name"] for row in rows]

    def create_session(self, initial_input: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sessions (initial_input, created_at) VALUES (?, ?)",
                (initial_input, datetime.now(timezone.utc).isoformat())
            )
            return cursor.lastrowid

    def save_message(self, session_id: int, role: str, content: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now(timezone.utc).isoformat())
            )

    def get_messages(self, session_id: int) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def save_problem(self, session_id: int, definition: str, clarity_level: str, tags: list):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO problems (session_id, definition, clarity_level, tags, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, definition, clarity_level, json.dumps(tags, ensure_ascii=False), datetime.now(timezone.utc).isoformat())
            )

    def get_problems(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM problems ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d["tags"])
                result.append(d)
            return result
