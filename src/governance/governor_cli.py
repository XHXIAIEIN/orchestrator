#!/usr/bin/env python3
"""CLI bridge called by Node dashboard to approve and execute manual tasks."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.governor import Governor
from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "events.db")


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "approve":
        print(json.dumps({"error": "usage: governor_cli.py approve <task_id>"}))
        sys.exit(1)

    try:
        task_id = int(sys.argv[2])
    except ValueError:
        print(json.dumps({"error": "task_id must be an integer"}))
        sys.exit(1)

    db = EventsDB(DB_PATH)
    task = db.get_task(task_id)
    if not task:
        print(json.dumps({"error": f"task {task_id} not found"}))
        sys.exit(1)
    if task["status"] != "awaiting_approval":
        print(json.dumps({"error": f"task {task_id} status is '{task['status']}', expected 'awaiting_approval'"}))
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    db.update_task(task_id, approved_at=now)

    governor = Governor(db=db)
    result = governor.execute_task(task_id)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
