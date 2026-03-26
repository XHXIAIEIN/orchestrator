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
        self._migrated = False  # ALTER TABLE only needs to run once

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.OperationalError:
            pass
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


def load_all_messages(db_path: str, chat_id: str) -> list[tuple]:
    """加载某 chat_id 的全部消息（用于摘要压缩）。返回 (role, content) 元组列表。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        return conn.execute(
            "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id ASC",
            (chat_id,),
        ).fetchall()


def prune_old_messages(db_path: str, chat_id: str, keep_recent: int):
    """删除旧消息，只保留最近 keep_recent 条。"""
    pool = _get_pool(db_path)
    with pool.lock:
        conn = pool.get_conn()
        try:
            conn.execute(
                "DELETE FROM chat_messages WHERE chat_id = ? AND id NOT IN "
                "(SELECT id FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?)",
                (chat_id, chat_id, keep_recent),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc):
                pool.recycle()
            raise
