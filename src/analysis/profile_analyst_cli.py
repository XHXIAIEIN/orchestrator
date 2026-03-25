#!/usr/bin/env python3
"""CLI bridge called by Node dashboard to trigger on-demand profile analysis."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analysis.profile_analyst import ProfileAnalyst
from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "events.db")

VALID_TYPES = ("periodic", "daily")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_TYPES:
        print(json.dumps({"error": f"usage: profile_analyst_cli.py [{'|'.join(VALID_TYPES)}]"}))
        sys.exit(1)

    analysis_type = sys.argv[1]
    try:
        db = EventsDB(DB_PATH)
        analyst = ProfileAnalyst(db=db)
        analyst.run(analysis_type=analysis_type)
        generated_at = datetime.now(timezone.utc).isoformat()
        print(json.dumps({"status": "ok", "generated_at": generated_at}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
