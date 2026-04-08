"""
Content-Hash Incremental Cache — skip unchanged content.

R45c steal from graphify. SHA256(content + source_path) fingerprints
documents. If the hash hasn't changed since last upsert, skip the
expensive embedding + Qdrant write entirely.

Key design choices (from graphify):
    - Path MUST be part of the hash: same content in different files
      are different documents (prevents collision on boilerplate).
    - Atomic write: SQLite transaction ensures hash update only persists
      if the operation succeeds.
    - Two-tier check: content_hash (text changes) vs metadata_hash
      (tags/labels changes). Content change = re-embed. Metadata-only
      change = update Qdrant payload without re-embedding.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.storage.pool import get_pool

logger = logging.getLogger(__name__)

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent / "data" / "content_hash.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_hashes (
    collection  TEXT NOT NULL,
    point_key   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_hash TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection, point_key)
);
"""


class ContentHashCache:
    """Track content hashes to skip unchanged documents during upsert."""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._pool = get_pool(db_path, row_factory=sqlite3.Row, log_prefix="hash_cache")
        with self._pool.connect() as conn:
            conn.executescript(_SCHEMA)

    @staticmethod
    def compute_hash(text: str, source: str = "") -> str:
        """SHA256(text + source). Source is part of the hash to prevent
        collision on identical content in different locations."""
        payload = f"{source}\x00{text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_metadata_hash(metadata: dict) -> str:
        """Hash of sorted metadata keys/values (excluding text and sqlite_id)."""
        import json
        # Only hash stable metadata, exclude volatile fields
        stable = {k: v for k, v in sorted(metadata.items())
                  if k not in ("text", "sqlite_id", "updated_at", "created_at")}
        return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def check(self, collection: str, point_key: str, text: str, source: str = "",
              metadata: dict | None = None) -> str:
        """Check if content has changed since last upsert.

        Returns:
            "unchanged" — content AND metadata identical, skip entirely
            "metadata_only" — content same but metadata changed, update payload only
            "changed" — content changed, needs full re-embed + upsert
            "new" — never seen before, needs full processing
        """
        new_content_hash = self.compute_hash(text, source)
        new_meta_hash = self.compute_metadata_hash(metadata or {})

        with self._pool.connect() as conn:
            row = conn.execute(
                "SELECT content_hash, metadata_hash FROM content_hashes "
                "WHERE collection = ? AND point_key = ?",
                (collection, point_key),
            ).fetchone()

            if not row:
                return "new"

            if row["content_hash"] != new_content_hash:
                return "changed"

            if row["metadata_hash"] != new_meta_hash:
                return "metadata_only"

            return "unchanged"

    def update(self, collection: str, point_key: str, text: str,
               source: str = "", metadata: dict | None = None) -> None:
        """Record the current content hash after successful upsert."""
        content_hash = self.compute_hash(text, source)
        meta_hash = self.compute_metadata_hash(metadata or {})
        now = datetime.now().isoformat()

        with self._pool.connect() as conn:
            conn.execute(
                "INSERT INTO content_hashes (collection, point_key, content_hash, metadata_hash, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(collection, point_key) DO UPDATE SET "
                "content_hash = excluded.content_hash, "
                "metadata_hash = excluded.metadata_hash, "
                "updated_at = excluded.updated_at",
                (collection, point_key, content_hash, meta_hash, now),
            )

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._pool.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM content_hashes").fetchone()[0]
            by_collection = conn.execute(
                "SELECT collection, COUNT(*) as cnt FROM content_hashes GROUP BY collection"
            ).fetchall()
            return {
                "total_entries": total,
                "by_collection": {row["collection"]: row["cnt"] for row in by_collection},
            }

    def invalidate(self, collection: str, point_key: str) -> None:
        """Remove a hash entry (forces re-processing next time)."""
        with self._pool.connect() as conn:
            conn.execute(
                "DELETE FROM content_hashes WHERE collection = ? AND point_key = ?",
                (collection, point_key),
            )
