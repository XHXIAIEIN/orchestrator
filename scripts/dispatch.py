"""CLI bridge: Claude Code → Governor dispatch pipeline.

Usage:
    # Natural language (goes through IntentGateway):
    python scripts/dispatch.py "修复 Steam 采集器"

    # Raw mode (skip IntentGateway, direct to Governor):
    python scripts/dispatch.py --raw --dept engineering --action "Answer Clawvard exam" "full task description here"

    # Wait for completion:
    python scripts/dispatch.py --wait --timeout 300 "练习 Clawvard tooling"
"""
import json
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent / "data" / "events.db")


def dispatch_raw(text: str, department: str, action: str, priority: str,
                 cognitive_mode: str, db: EventsDB) -> dict:
    """Skip IntentGateway — create + execute task via Governor directly."""
    from src.governance.governor import Governor

    spec = {
        "department": department,
        "intent": "execute",
        "problem": text,
        "expected": "Complete the task and return results",
        "summary": action,
        "cognitive_mode": cognitive_mode,
        "source": "cli_raw",
        "observation": f"CLI 直派：{action}",
        "importance": f"用户直接指派，优先级 {priority}",
    }

    governor = Governor(db=db)
    task = governor._dispatch_task(spec, action=action,
                                   reason="CLI 直派（跳过 IntentGateway）",
                                   priority=priority, source="cli")

    if task is None:
        return {"status": "dispatch_failed", "tier": "raw"}

    return {
        "task_id": task["id"],
        "status": task.get("status", "created"),
        "action": action,
        "department": department,
        "priority": priority,
        "cognitive_mode": cognitive_mode,
        "tier": "raw",
    }


def dispatch_natural(text: str, context: dict, db: EventsDB) -> dict:
    """Go through IntentGateway classification."""
    from src.gateway.dispatcher import dispatch_from_text
    return dispatch_from_text(text, context=context, db=db)


def wait_for_task(task_id: int, db: EventsDB, timeout: int = 300):
    """Poll until task completes or times out."""
    deadline = time.time() + timeout
    status = "unknown"
    while time.time() < deadline:
        task = db.get_task(task_id)
        status = task.get("status", "unknown") if task else "not_found"
        if status in ("done", "failed", "scrutiny_failed", "review_rejected"):
            print(f"\n--- Task #{task_id} finished: {status} ---")
            if task.get("output"):
                print(task["output"][:3000])
            return
        time.sleep(5)
    print(f"\n--- Timeout: task #{task_id} still {status} after {timeout}s ---")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dispatch task via Governor pipeline")
    parser.add_argument("text", help="Task description")
    parser.add_argument("--raw", action="store_true",
                        help="Skip IntentGateway, create task directly")
    parser.add_argument("--dept", default="engineering",
                        help="Department (raw mode only, default: engineering)")
    parser.add_argument("--action", default=None,
                        help="Short action label (raw mode only, default: first 80 chars of text)")
    parser.add_argument("--priority", default="high",
                        choices=["low", "medium", "high", "critical"],
                        help="Task priority (default: high)")
    parser.add_argument("--mode", default="react",
                        choices=["direct", "react", "hypothesis", "designer"],
                        help="Cognitive mode (default: react)")
    parser.add_argument("--approve", action="store_true",
                        help="Auto-approve task (skip approval gate)")
    parser.add_argument("--wait", action="store_true",
                        help="Poll until task completes")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Max wait seconds (default 300)")
    parser.add_argument("--context", type=str, default=None,
                        help="JSON context string (natural mode only)")
    args = parser.parse_args()

    db = EventsDB(DB_PATH)

    if args.raw:
        action = args.action or args.text[:80]
        result = dispatch_raw(args.text, args.dept, action, args.priority, args.mode, db)
    else:
        context = json.loads(args.context) if args.context else None
        result = dispatch_natural(args.text, context, db)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    task_id = result.get("task_id")
    if not task_id:
        return

    # Auto-approve if requested
    if args.approve and result.get("status") in ("created", "awaiting_approval", "pending"):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.update_task(task_id, approved_at=now, status="running")
        from src.governance.governor import Governor
        governor = Governor(db=db)
        governor.execute_task_async(task_id)
        print(f"Auto-approved task #{task_id}, now running")

    if args.wait:
        wait_for_task(task_id, db, args.timeout)


if __name__ == "__main__":
    main()
