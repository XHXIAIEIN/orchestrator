"""Store Collections — generic data structure abstractions over SQLite.

Provides Collection[T], Queue[T], and KeyValue[K,V] with SQLite backend.
Business logic uses these abstractions; backend can be swapped later.
"""

import json
import sqlite3
import time
import threading
from typing import TypeVar, Generic, Iterator, Any

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


class Collection:
    """Ordered collection of JSON-serializable items with optional tags."""

    def __init__(self, db_path: str, name: str = "default"):
        self._db_path = db_path
        self._name = name
        self._lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    data TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    UNIQUE(collection, id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_coll_name
                ON collections(collection, created_at)
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def add(self, item: Any, tags: list[str] | None = None) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO collections (collection, data, tags, created_at) VALUES (?, ?, ?, ?)",
                (self._name, json.dumps(item), ",".join(tags or []), time.time()),
            )
            return cur.lastrowid

    def get(self, n: int = 10, offset: int = 0) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, data, tags, created_at FROM collections WHERE collection = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (self._name, n, offset),
            ).fetchall()
            return [{"id": r[0], "data": json.loads(r[1]), "tags": r[2].split(",") if r[2] else [], "created_at": r[3]} for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM collections WHERE collection = ?", (self._name,)
            ).fetchone()[0]

    def delete(self, item_id: int):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM collections WHERE id = ? AND collection = ?", (item_id, self._name))


class Queue:
    """FIFO queue backed by SQLite. Supports priority."""

    def __init__(self, db_path: str, name: str = "default"):
        self._db_path = db_path
        self._name = name
        self._lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue TEXT NOT NULL,
                    data TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    consumed_at REAL DEFAULT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def push(self, item: Any, priority: int = 0) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO queues (queue, data, priority, created_at) VALUES (?, ?, ?, ?)",
                (self._name, json.dumps(item), priority, time.time()),
            )
            return cur.lastrowid

    def pop(self) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, data, priority FROM queues WHERE queue = ? AND consumed_at IS NULL ORDER BY priority DESC, created_at ASC LIMIT 1",
                (self._name,),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE queues SET consumed_at = ? WHERE id = ?", (time.time(), row[0]))
            return {"id": row[0], "data": json.loads(row[1]), "priority": row[2]}

    def peek(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, data, priority FROM queues WHERE queue = ? AND consumed_at IS NULL ORDER BY priority DESC, created_at ASC LIMIT 1",
                (self._name,),
            ).fetchone()
            if not row:
                return None
            return {"id": row[0], "data": json.loads(row[1]), "priority": row[2]}

    def size(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM queues WHERE queue = ? AND consumed_at IS NULL", (self._name,)
            ).fetchone()[0]


class KeyValue:
    """Key-value store backed by SQLite."""

    def __init__(self, db_path: str, namespace: str = "default"):
        self._db_path = db_path
        self._namespace = namespace
        self._lock = threading.Lock()
        self._ensure_table()

    def _ensure_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def set(self, key: str, value: Any):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_store (namespace, key, value, updated_at) VALUES (?, ?, ?, ?)",
                (self._namespace, key, json.dumps(value), time.time()),
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM kv_store WHERE namespace = ? AND key = ?",
                (self._namespace, key),
            ).fetchone()
            return json.loads(row[0]) if row else default

    def delete(self, key: str):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM kv_store WHERE namespace = ? AND key = ?", (self._namespace, key))

    def keys(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key FROM kv_store WHERE namespace = ?", (self._namespace,)
            ).fetchall()
            return [r[0] for r in rows]
