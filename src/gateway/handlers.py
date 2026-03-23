"""
Gateway Handlers — execute classified requests without agent loops.

NO_TOKEN handlers query DB/filesystem directly.
DIRECT handlers make a single LLM call.
"""
import json
import logging
from pathlib import Path

from src.storage.events_db import EventsDB
from src.governance.audit.run_logger import load_recent_runs, verify_chain

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def _get_db() -> EventsDB:
    return EventsDB(DB_PATH)


# ── NO_TOKEN handlers ──

def handle_system_status(**kwargs) -> dict:
    db = _get_db()
    scheduler = db.get_scheduler_status()
    running = db.count_running_tasks()
    size = db.get_size_bytes()
    return {
        "type": "no_token",
        "handler": "system_status",
        "data": {
            "scheduler": scheduler,
            "running_tasks": running,
            "db_size_mb": round(size / 1024 / 1024, 1),
        },
    }


def handle_recent_tasks(**kwargs) -> dict:
    db = _get_db()
    tasks = db.get_tasks(limit=10)
    return {
        "type": "no_token",
        "handler": "recent_tasks",
        "data": [
            {
                "id": t["id"],
                "action": t["action"],
                "status": t["status"],
                "department": t["spec"].get("department", "?") if isinstance(t.get("spec"), dict) else "?",
                "created_at": t.get("created_at", ""),
            }
            for t in tasks
        ],
    }


def handle_task_count(**kwargs) -> dict:
    db = _get_db()
    tasks = db.get_tasks(limit=1000)
    by_status = {}
    for t in tasks:
        s = t.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "type": "no_token",
        "handler": "task_count",
        "data": {"total": len(tasks), "by_status": by_status},
    }


def handle_collector_status(**kwargs) -> dict:
    db = _get_db()
    import sqlite3
    try:
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT name, data, updated_at FROM collector_reputation"
            ).fetchall()
        reps = []
        for r in rows:
            d = json.loads(r["data"])
            d["name"] = r["name"]
            d["updated_at"] = r["updated_at"]
            reps.append(d)
        return {"type": "no_token", "handler": "collector_status", "data": reps}
    except Exception:
        return {"type": "no_token", "handler": "collector_status", "data": []}


def handle_department_stats(**kwargs) -> dict:
    db = _get_db()
    stats = db.get_department_run_stats()
    return {"type": "no_token", "handler": "department_stats", "data": stats}


def handle_daily_summary(**kwargs) -> dict:
    db = _get_db()
    summaries = db.get_daily_summaries(days=3)
    return {"type": "no_token", "handler": "daily_summary", "data": summaries}


def handle_run_logs(**kwargs) -> dict:
    depts = ["engineering", "operations", "protocol", "security", "quality", "personnel"]
    data = {}
    for dept in depts:
        runs = load_recent_runs(dept, n=5)
        if runs:
            data[dept] = runs
    return {"type": "no_token", "handler": "run_logs", "data": data}


def handle_verify_chain(**kwargs) -> dict:
    result = verify_chain()
    return {"type": "no_token", "handler": "verify_chain", "data": result}


def handle_debt_list(**kwargs) -> dict:
    db = _get_db()
    import sqlite3
    try:
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT id, project, summary, severity, status, created_at "
                "FROM attention_debts WHERE status = 'open' ORDER BY id DESC LIMIT 20"
            ).fetchall()
        return {"type": "no_token", "handler": "debt_list", "data": [dict(r) for r in rows]}
    except Exception:
        return {"type": "no_token", "handler": "debt_list", "data": []}


# ── Handler registry ──

NO_TOKEN_HANDLERS = {
    "system_status": handle_system_status,
    "recent_tasks": handle_recent_tasks,
    "task_count": handle_task_count,
    "collector_status": handle_collector_status,
    "department_stats": handle_department_stats,
    "daily_summary": handle_daily_summary,
    "run_logs": handle_run_logs,
    "verify_chain": handle_verify_chain,
    "debt_list": handle_debt_list,
}


def execute_no_token(handler_name: str, params: dict = None) -> dict:
    """Execute a NO_TOKEN handler by name."""
    handler = NO_TOKEN_HANDLERS.get(handler_name)
    if not handler:
        return {"type": "error", "message": f"Unknown handler: {handler_name}"}
    try:
        return handler(**(params or {}))
    except Exception as e:
        log.error(f"gateway handler {handler_name} failed: {e}")
        return {"type": "error", "handler": handler_name, "message": str(e)}
