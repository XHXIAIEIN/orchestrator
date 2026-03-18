"""
Debt Resolver — bridge between attention_debts and Governor tasks.

Protocol dept discovers problems -> DebtResolver evaluates -> Governor dispatches execution.

Status flow: open -> tasked -> resolved (success) or open (failure rollback)
"""
import logging
from datetime import datetime, timezone, timedelta
from src.storage.events_db import EventsDB
from src.project_registry import resolve_project

log = logging.getLogger(__name__)

MAX_TASKS_PER_RUN = 3
MAX_DEBT_AGE_DAYS = 14


def resolve_debts(db: EventsDB) -> dict:
    """Evaluate open debts, convert actionable ones into Governor tasks."""
    with db._connect() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_DEBT_AGE_DAYS)).isoformat()
        debts = conn.execute(
            """SELECT * FROM attention_debts
               WHERE status = 'open' AND severity = 'high' AND created_at >= ?
               ORDER BY created_at DESC""",
            (cutoff,)
        ).fetchall()

    results = {"evaluated": len(debts), "tasked": 0, "skipped": 0, "reasons": []}

    if not debts:
        return results

    tasked = 0
    for row in debts:
        if tasked >= MAX_TASKS_PER_RUN:
            break

        debt = dict(row)
        project = debt.get("project", "")
        summary = debt.get("summary", "")
        context = debt.get("context", "")
        debt_id = debt.get("id")

        # Check if project is operable
        project_dir = resolve_project(project)
        if not project_dir:
            results["skipped"] += 1
            results["reasons"].append(f"debt #{debt_id}: project '{project}' not registered")
            continue

        # Check if task queue is full
        running = db.count_running_tasks()
        if running >= 3:
            results["reasons"].append("task queue full")
            break

        # Create Governor task
        dept = _classify_department(summary, context)
        task_id = db.create_task(
            action=f"resolve attention debt #{debt_id}: {summary[:80]}",
            reason=f"High severity issue found by DebtScanner ({debt.get('created_at', '')[:10]})",
            priority="medium",
            spec={
                "department": dept,
                "project": project,
                "cwd": project_dir,
                "problem": summary,
                "observation": context[:500],
                "expected": "Problem resolved or confirmed no longer relevant",
                "summary": f"Debt resolution: {summary[:50]}",
                "debt_id": debt_id,
            },
            source="debt_resolver",
        )

        # Mark debt as tasked (prevent duplicate conversion)
        with db._connect() as conn:
            conn.execute(
                "UPDATE attention_debts SET status = 'tasked', resolved_by = ? WHERE id = ?",
                (f"task#{task_id}", debt_id)
            )

        log.info(f"DebtResolver: debt #{debt_id} -> task #{task_id} ({dept}): {summary[:50]}")
        db.write_log(f"debt #{debt_id} -> task #{task_id} ({project})", "INFO", "debt_resolver")

        tasked += 1
        results["tasked"] += 1

    return results


def _classify_department(summary: str, context: str) -> str:
    """Classify which department should handle the debt based on content."""
    text = f"{summary} {context}".lower()

    if any(k in text for k in ["bug", "error", "fix", "crash", "implement", "feature",
                                "报错", "不工作", "修复", "实现", "功能"]):
        return "engineering"

    if any(k in text for k in ["performance", "timeout", "slow", "memory", "disk",
                                "性能", "超时", "慢", "内存", "磁盘", "采集"]):
        return "operations"

    if any(k in text for k in ["security", "credential", "permission", "key",
                                "安全", "密钥", "权限"]):
        return "security"

    return "engineering"


def check_resolved_debts(db: EventsDB) -> int:
    """Check if tasked debts' corresponding tasks are done, update debt status."""
    with db._connect() as conn:
        tasked_debts = conn.execute(
            "SELECT id, resolved_by FROM attention_debts WHERE status = 'tasked'"
        ).fetchall()

    resolved = 0
    for row in tasked_debts:
        debt = dict(row)
        task_ref = debt.get("resolved_by", "")
        if not task_ref or not task_ref.startswith("task#"):
            continue

        try:
            task_id = int(task_ref.replace("task#", ""))
            task = db.get_task(task_id)
            if not task:
                continue

            if task.get("status") == "done":
                with db._connect() as conn:
                    conn.execute(
                        "UPDATE attention_debts SET status = 'resolved', resolved_at = ? WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(), debt["id"])
                    )
                resolved += 1
            elif task.get("status") == "failed":
                # Task failed — reopen the debt
                with db._connect() as conn:
                    conn.execute(
                        "UPDATE attention_debts SET status = 'open', resolved_by = NULL WHERE id = ?",
                        (debt["id"],)
                    )
        except (ValueError, TypeError):
            continue

    return resolved
