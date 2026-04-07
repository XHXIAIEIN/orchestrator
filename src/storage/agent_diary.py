"""
Specialist Agent Diaries — per-department persistent memory.

Stolen from MemPalace R44 P1#9. Each department (三省六部) gets its own
diary "wing" for cross-session persistence. Diaries store decisions,
patterns, and lessons specific to that department's domain.

Departments: 工部(engineering), 礼部(protocol), 刑部(review),
             户部(operations), 吏部(personnel), 兵部(security)
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.storage.pool import get_pool

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "events.db")

# Standard departments (三省六部)
DEPARTMENTS = {
    "engineering": "工部",
    "protocol": "礼部",
    "review": "刑部",
    "operations": "户部",
    "personnel": "吏部",
    "security": "兵部",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_diaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    department  TEXT NOT NULL,
    entry_type  TEXT NOT NULL DEFAULT 'note',
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    session_id  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_diary_dept ON agent_diaries(department);
CREATE INDEX IF NOT EXISTS idx_diary_type ON agent_diaries(entry_type);
CREATE INDEX IF NOT EXISTS idx_diary_created ON agent_diaries(created_at);
"""


class AgentDiary:
    """Per-department diary with read/write operations."""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._pool = get_pool(db_path, row_factory=sqlite3.Row, log_prefix="diary")
        with self._pool.connect() as conn:
            conn.executescript(_SCHEMA)

    def write(
        self,
        department: str,
        content: str,
        entry_type: str = "note",
        metadata: dict | None = None,
        session_id: str = "",
    ) -> int:
        """Write a diary entry for a department.

        entry_type: 'note' | 'decision' | 'pattern' | 'lesson' | 'error'
        Returns entry ID.
        """
        dept = self._normalize_dept(department)
        meta = json.dumps(metadata or {}, ensure_ascii=False)

        with self._pool.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_diaries (department, entry_type, content, metadata, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (dept, entry_type, content, meta, session_id, datetime.now().isoformat()),
            )
            return cursor.lastrowid or 0

    def read(
        self,
        department: str,
        limit: int = 20,
        entry_type: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        """Read diary entries for a department.

        Args:
            department: Department name (Chinese or English).
            limit: Max entries to return.
            entry_type: Filter by type (optional).
            since: ISO date, only entries after this date (optional).
        """
        dept = self._normalize_dept(department)

        query = "SELECT * FROM agent_diaries WHERE department = ?"
        params: list = [dept]

        if entry_type:
            query += " AND entry_type = ?"
            params.append(entry_type)
        if since:
            query += " AND created_at >= ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._pool.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "department": r["department"],
                    "entry_type": r["entry_type"],
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"] or "{}"),
                    "session_id": r["session_id"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def read_all_departments(self, limit_per_dept: int = 5) -> dict[str, list[dict]]:
        """Read recent entries from all departments. Returns {dept: [entries]}."""
        result = {}
        for dept_en in DEPARTMENTS:
            entries = self.read(dept_en, limit=limit_per_dept)
            if entries:
                result[dept_en] = entries
        return result

    def summary(self, department: str, limit: int = 10) -> str:
        """Generate a compact text summary of recent diary entries for a department."""
        entries = self.read(department, limit=limit)
        if not entries:
            dept = self._normalize_dept(department)
            return f"{dept}: (no diary entries)"

        lines = [f"## {self._normalize_dept(department)} Diary"]
        for e in entries:
            date_short = e["created_at"][:10]
            lines.append(f"- [{date_short}] ({e['entry_type']}) {e['content'][:100]}")
        return "\n".join(lines)

    def stats(self) -> dict[str, int]:
        """Count entries per department."""
        with self._pool.connect() as conn:
            rows = conn.execute(
                "SELECT department, COUNT(*) as cnt FROM agent_diaries GROUP BY department"
            ).fetchall()
            return {r["department"]: r["cnt"] for r in rows}

    @staticmethod
    def _normalize_dept(name: str) -> str:
        """Normalize department name to English key."""
        # Check if it's already an English key
        if name in DEPARTMENTS:
            return name
        # Check Chinese name → English key
        reverse = {v: k for k, v in DEPARTMENTS.items()}
        if name in reverse:
            return reverse[name]
        # Fuzzy: check if Chinese name is substring
        for cn, en in reverse.items():
            if cn in name or en in name:
                return en
        return name.lower()
