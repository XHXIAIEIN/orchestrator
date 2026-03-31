"""Session and memory tracking methods for EventsDB.

Bridges the gap between CLI sessions (Claude Code) and bot sessions (TG/WX).
Both now register in the same `sessions` table for unified tracking.
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class SessionsMixin:
    """Track CLI/bot sessions and index memory files."""

    # ── Sessions ──

    def register_session(self, session_id: str, source: str = "cli") -> int:
        """Register a new session. Called by session-start hook."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO sessions "
                "(session_id, started_at, status, source, created_at) "
                "VALUES (?, ?, 'active', ?, ?)",
                (session_id, now, source, now),
            )
            return cur.lastrowid

    def close_session(self, session_id: str, summary: str = "",
                      topics: list[str] | None = None,
                      experience_ids: list[int] | None = None) -> None:
        """Close a session. Called by session-stop hook."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=?, status='closed', summary=?, "
                "topics=?, experience_ids=? WHERE session_id=? AND status='active'",
                (now, summary,
                 json.dumps(topics or [], ensure_ascii=False),
                 json.dumps(experience_ids or []),
                 session_id),
            )

    def get_active_session(self) -> dict | None:
        """Get the currently active session (if any)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE status='active' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """Get recent sessions (any status)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Memory Index ──

    def sync_memory_dir(self, memory_dir: str) -> dict:
        """Scan memory directory and sync file metadata into DB.

        Returns: {"added": N, "updated": N, "removed": N}
        """
        memory_path = Path(memory_dir)
        if not memory_path.is_dir():
            return {"added": 0, "updated": 0, "removed": 0}

        now = datetime.now(timezone.utc).isoformat()
        stats = {"added": 0, "updated": 0, "removed": 0}

        # Scan all .md files (skip MEMORY.md index itself)
        disk_files: dict[str, Path] = {}
        for f in memory_path.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            disk_files[str(f)] = f

        with self._connect() as conn:
            # Get existing entries
            existing = {}
            for row in conn.execute("SELECT path, content_hash FROM memory_entries").fetchall():
                existing[row["path"]] = row["content_hash"]

            # Upsert files on disk
            for fpath, p in disk_files.items():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                except Exception:
                    continue

                # Parse frontmatter
                name, description, mtype = p.stem, "", "project"
                l0, l1 = "", ""
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for line in parts[1].strip().split("\n"):
                            line = line.strip()
                            if line.startswith("name:"):
                                name = line.split(":", 1)[1].strip()
                            elif line.startswith("description:"):
                                description = line.split(":", 1)[1].strip()
                            elif line.startswith("type:"):
                                mtype = line.split(":", 1)[1].strip()
                            elif line.startswith("l0:"):
                                l0 = line.split(":", 1)[1].strip()
                            elif line.startswith("l1:"):
                                l1 = line.split(":", 1)[1].strip()

                mtime = datetime.fromtimestamp(
                    p.stat().st_mtime, tz=timezone.utc
                ).isoformat()

                if fpath not in existing:
                    conn.execute(
                        "INSERT INTO memory_entries "
                        "(path, name, description, type, content_hash, last_modified, synced_at, l0, l1) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (fpath, name, description, mtype, content_hash, mtime, now, l0, l1),
                    )
                    stats["added"] += 1
                elif existing[fpath] != content_hash:
                    conn.execute(
                        "UPDATE memory_entries SET name=?, description=?, type=?, "
                        "content_hash=?, last_modified=?, synced_at=?, l0=?, l1=? WHERE path=?",
                        (name, description, mtype, content_hash, mtime, now, l0, l1, fpath),
                    )
                    stats["updated"] += 1

            # Remove entries for deleted files
            for fpath in existing:
                if fpath not in disk_files:
                    conn.execute("DELETE FROM memory_entries WHERE path=?", (fpath,))
                    stats["removed"] += 1

        return stats

    def get_memory_entries(self, mtype: str | None = None) -> list[dict]:
        """Get all memory entries, optionally filtered by type."""
        with self._connect() as conn:
            if mtype:
                rows = conn.execute(
                    "SELECT * FROM memory_entries WHERE type=? ORDER BY name",
                    (mtype,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_entries ORDER BY type, name"
                ).fetchall()
            return [dict(r) for r in rows]

    def search_memory(self, query: str) -> list[dict]:
        """Search memory entries by name or description."""
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries "
                "WHERE name LIKE ? OR description LIKE ? ORDER BY name",
                (pattern, pattern),
            ).fetchall()
            return [dict(r) for r in rows]

    def migrate_memory_l0_l1(self):
        """Add l0, l1 columns to memory_entries if missing."""
        with self._connect() as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()]
            if "l0" not in cols:
                conn.execute("ALTER TABLE memory_entries ADD COLUMN l0 TEXT NOT NULL DEFAULT ''")
                conn.execute("ALTER TABLE memory_entries ADD COLUMN l1 TEXT NOT NULL DEFAULT ''")
                log.info("Migrated memory_entries: added l0, l1 columns")

    # ── Unified Experience Writer ──

    def add_experience_unified(self, date: str, etype: str, summary: str,
                               detail: str, instance: str = None,
                               jsonl_path: str | None = None) -> int:
        """Write experience to DB + optionally to JSONL backup.

        Single function replaces the dual-write in session-stop.sh.
        Returns experience ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO experiences "
                "(date, type, summary, detail, instance, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (date, etype, summary, detail, instance, now),
            )
            exp_id = cur.lastrowid

        # Write to structured_memory (6-dimensional store)
        try:
            from src.governance.context.structured_memory import (
                StructuredMemoryStore, Dimension, ActivityMemory,
            )
            store = StructuredMemoryStore()
            store.add(Dimension.ACTIVITY, ActivityMemory(
                summary=summary,
                detail=detail,
                emotion=etype,
                event_date=date,
                tags=[etype] if etype else [],
            ))
        except Exception as e:
            log.warning(f"structured_memory write failed: {e}")

        # DEPRECATED: remove after structured_memory migration verified
        # JSONL backup (append-only)
        if jsonl_path:
            try:
                entry = json.dumps({
                    "date": date, "type": etype,
                    "summary": summary, "detail": detail,
                    "instance": instance,
                }, ensure_ascii=False)
                os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception as e:
                log.warning(f"JSONL backup failed: {e}")

        return exp_id
