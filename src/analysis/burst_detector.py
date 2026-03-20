"""
Burst session detector.

Scans Claude session events and detects bursts:
  - Same project, 10+ sessions within a 15-minute window → burst_session event.

Runs after each collection cycle. Uses dedup_key to avoid duplicates.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

BURST_WINDOW_MINUTES = 15
BURST_THRESHOLD = 10


def detect_bursts(db: EventsDB, lookback_hours: int = 24) -> list[dict]:
    """
    Scan recent claude events for burst patterns.

    Returns list of detected bursts:
      [{ project, session_count, approx_tokens, window_start, window_end }, ...]
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT metadata, occurred_at FROM events "
            "WHERE source = 'claude' AND occurred_at >= ? "
            "ORDER BY occurred_at ASC",
            (since,),
        ).fetchall()

    # Group sessions by project
    by_project: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
        except (json.JSONDecodeError, TypeError):
            continue
        project = meta.get("project", "unknown")
        by_project[project].append({
            "occurred_at": row["occurred_at"],
            "approx_tokens": meta.get("approx_tokens", 0),
            "messages": meta.get("messages", 0),
        })

    bursts = []
    window = timedelta(minutes=BURST_WINDOW_MINUTES)

    for project, sessions in by_project.items():
        if len(sessions) < BURST_THRESHOLD:
            continue

        # Sliding window: for each session, count how many fall within next 15 min
        for i, anchor in enumerate(sessions):
            try:
                t0 = datetime.fromisoformat(anchor["occurred_at"])
            except (ValueError, TypeError):
                continue

            t1 = t0 + window
            # Collect all sessions in [t0, t1]
            window_sessions = []
            for j in range(i, len(sessions)):
                try:
                    tj = datetime.fromisoformat(sessions[j]["occurred_at"])
                except (ValueError, TypeError):
                    continue
                if tj > t1:
                    break
                window_sessions.append(sessions[j])

            if len(window_sessions) >= BURST_THRESHOLD:
                total_tokens = sum(s.get("approx_tokens", 0) for s in window_sessions)
                total_messages = sum(s.get("messages", 0) for s in window_sessions)
                burst = {
                    "project": project,
                    "session_count": len(window_sessions),
                    "approx_tokens": total_tokens,
                    "total_messages": total_messages,
                    "window_start": anchor["occurred_at"],
                    "window_end": window_sessions[-1]["occurred_at"],
                }
                bursts.append(burst)
                # Skip past this burst window to avoid overlapping detections
                break  # one burst per project per scan is enough

    return bursts


def record_bursts(db: EventsDB, lookback_hours: int = 24) -> int:
    """
    Detect and record burst sessions as events.
    Returns number of new burst events recorded.
    """
    bursts = detect_bursts(db, lookback_hours=lookback_hours)
    recorded = 0

    for burst in bursts:
        # Dedup key based on project + window start (rounded to minute)
        window_key = burst["window_start"][:16]  # YYYY-MM-DDTHH:MM
        dedup = f"burst_session:{burst['project']}:{window_key}"

        tokens_k = burst["approx_tokens"] // 1000
        title = (
            f"🔥 Burst: {burst['session_count']} sessions on "
            f"{burst['project'][:30]} (~{tokens_k}k tokens)"
        )

        inserted = db.insert_event(
            source="burst_detector",
            category="burst_session",
            title=title[:200],
            duration_minutes=BURST_WINDOW_MINUTES,
            score=min(1.0, burst["session_count"] / 50),
            tags=["burst", "cost-alert", burst["project"][:30]],
            metadata=burst,
            dedup_key=dedup,
            occurred_at=burst["window_start"],
        )
        if inserted:
            recorded += 1
            log.info(
                "Burst detected: %s — %d sessions, ~%dk tokens in %d min",
                burst["project"], burst["session_count"],
                tokens_k, BURST_WINDOW_MINUTES,
            )

    return recorded
