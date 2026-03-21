"""
部门执行记忆：DB-first 哈希链日志，JSONL 降级 fallback。

每条记录包含 SHA-256 哈希，prev_hash 指向上一条，形成不可篡改账本。
"""
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _compute_hash(entry: dict, prev_hash: str) -> str:
    """计算当前条目的哈希值：SHA-256(prev_hash + canonical JSON)。"""
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    payload = f"{prev_hash}:{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_db():
    """懒加载 EventsDB，避免循环导入。"""
    try:
        from pathlib import Path as _Path
        from src.storage.events_db import EventsDB
        db_path = str(_Path(__file__).parent.parent.parent / "data" / "events.db")
        return EventsDB(db_path)
    except Exception:
        return None


def _fallback_jsonl(department: str, entry: dict):
    """DB 不可用时降级写 JSONL 文件。"""
    try:
        log_path = Path("departments") / department / "run-log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[run_logger] JSONL fallback also failed: {e}", file=sys.stderr)


def append_run_log(department: str, task_id: int, mode: str, summary: str,
                   files_changed: list = None, commit: str = "",
                   status: str = "done", duration_s: int = 0,
                   notes: str = ""):
    """写入一条执行记录，DB-first + JSONL fallback。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "mode": mode,
        "summary": summary,
        "files_changed": files_changed or [],
        "commit": commit,
        "status": status,
        "duration_s": duration_s,
        "notes": notes,
    }

    db = _get_db()
    if db is not None:
        try:
            prev_hash = db.get_last_run_hash(department)
            entry_hash = _compute_hash(entry, prev_hash)

            db.append_run_log(
                department=department,
                task_id=task_id,
                mode=mode,
                summary=summary,
                files_changed=files_changed or [],
                commit_hash=commit,
                status=status,
                duration_s=duration_s,
                notes=notes,
                entry_hash=entry_hash,
                prev_hash=prev_hash,
                created_at=entry["ts"],
            )
            return
        except Exception as e:
            log.warning(f"run_logger: DB write failed, falling back to JSONL: {e}")

    _fallback_jsonl(department, entry)


def load_recent_runs(department: str, n: int = 5) -> list[dict]:
    """读取最近 N 条执行记录，优先从 DB 读取。"""
    db = _get_db()
    if db is not None:
        try:
            rows = db.get_recent_run_logs(department, n)
            # 统一输出格式（兼容旧 JSONL 字段名）
            return [
                {
                    "ts": r.get("created_at", ""),
                    "task_id": r.get("task_id"),
                    "mode": r.get("mode", ""),
                    "summary": r.get("summary", ""),
                    "files_changed": r.get("files_changed", []),
                    "commit": r.get("commit_hash", ""),
                    "status": r.get("status", ""),
                    "duration_s": r.get("duration_s", 0),
                    "notes": r.get("notes", ""),
                }
                for r in rows
            ]
        except Exception as e:
            log.warning(f"run_logger: DB read failed, falling back to JSONL: {e}")

    # Fallback: 读 JSONL
    log_path = Path("departments") / department / "run-log.jsonl"
    if not log_path.exists():
        return []

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    recent = lines[-n:] if len(lines) > n else lines

    runs = []
    for line in recent:
        if line.strip():
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return runs


def format_runs_for_context(runs: list[dict]) -> str:
    if not runs:
        return ""

    lines = ["## 最近执行记录"]
    for r in runs:
        lines.append(f"- [{r.get('ts','')}] {r.get('summary','')} → {r.get('status','')}"
                     + (f" (note: {r.get('notes','')})" if r.get('notes') else ""))
    return "\n".join(lines)


def verify_chain(department: str = None) -> dict:
    """验证哈希链完整性。返回 {"valid": bool, "total": int, "breaks": [...]}。"""
    db = _get_db()
    if db is None:
        return {"valid": False, "total": 0, "breaks": [], "error": "DB unavailable"}

    rows = db.get_all_run_logs(department=department, limit=10000)
    rows.reverse()  # 从旧到新

    breaks = []
    prev_hash = ""

    for row in rows:
        entry = {
            "ts": row.get("created_at", ""),
            "task_id": row.get("task_id"),
            "mode": row.get("mode", ""),
            "summary": row.get("summary", ""),
            "files_changed": row.get("files_changed", []),
            "commit": row.get("commit_hash", ""),
            "status": row.get("status", ""),
            "duration_s": row.get("duration_s", 0),
            "notes": row.get("notes", ""),
        }

        expected_hash = _compute_hash(entry, prev_hash)
        stored_hash = row.get("hash", "")
        stored_prev = row.get("prev_hash", "")

        if stored_prev != prev_hash or stored_hash != expected_hash:
            breaks.append({
                "id": row.get("id"),
                "department": row.get("department"),
                "expected_prev": prev_hash,
                "stored_prev": stored_prev,
                "expected_hash": expected_hash,
                "stored_hash": stored_hash,
            })

        prev_hash = stored_hash

    return {
        "valid": len(breaks) == 0,
        "total": len(rows),
        "breaks": breaks,
    }
