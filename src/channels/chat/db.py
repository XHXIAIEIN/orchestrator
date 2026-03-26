"""Chat DB persistence — message storage, memory, counts."""
import json
import logging
import sqlite3
from datetime import datetime, timezone

from src.channels import config as ch_cfg

log = logging.getLogger(__name__)


def db_conn(db_path: str) -> sqlite3.Connection:
    """Connect with DELETE journal mode (matches EventsDB — WAL breaks on Docker NTFS bind-mounts)."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_chat_client_column(conn: sqlite3.Connection):
    """确保 chat_messages 表有 chat_client 字段（兼容旧表）。"""
    try:
        conn.execute("SELECT chat_client FROM chat_messages LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN chat_client TEXT DEFAULT ''")
        conn.commit()


def _ensure_media_paths_column(conn: sqlite3.Connection):
    """确保 chat_messages 表有 media_paths 字段（JSON 数组）。"""
    try:
        conn.execute("SELECT media_paths FROM chat_messages LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN media_paths TEXT DEFAULT ''")
        conn.commit()


def save_message(db_path: str, chat_id: str, role: str, content: str,
                 chat_client: str = "", media_paths: list[str] | None = None):
    """存一条消息。含硬上限保护。media_paths: 关联的媒体文件路径列表。"""
    conn = db_conn(db_path)
    _ensure_chat_client_column(conn)
    _ensure_media_paths_column(conn)
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
    conn.close()


def load_recent(db_path: str, chat_id: str, limit: int = 20) -> list[dict]:
    """从 DB 加载最近 N 轮对话。包含 media_paths（如果有）。"""
    conn = db_conn(db_path)
    _ensure_media_paths_column(conn)
    rows = conn.execute(
        "SELECT role, content, media_paths FROM chat_messages "
        "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
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
    conn = db_conn(db_path)
    row = conn.execute(
        "SELECT summary FROM chat_memory WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def save_memory(db_path: str, chat_id: str, summary: str):
    """保存摘要记忆。"""
    conn = db_conn(db_path)
    conn.execute(
        "INSERT INTO chat_memory (chat_id, summary, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET summary = ?, updated_at = ?",
        (chat_id, summary, datetime.now(timezone.utc).isoformat(),
         summary, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def count_messages(db_path: str, chat_id: str) -> int:
    conn = db_conn(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
    ).fetchone()[0]
    conn.close()
    return count
