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


def _cheap_candidate_filter(db: EventsDB, since: str) -> set[str]:
    """R60 MinerU P0-3: Stage 1 — cheap SQL aggregate pre-filter.

    Uses COUNT GROUP BY to find projects with >= BURST_THRESHOLD events
    in the lookback window. This eliminates ~90% of projects before we
    load any row data, saving memory and CPU on the sliding window scan.
    """
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT json_extract(metadata, '$.project') AS project, COUNT(*) AS cnt "
            "FROM events "
            "WHERE source = 'claude' AND occurred_at >= ? "
            "GROUP BY project "
            "HAVING cnt >= ?",
            (since, BURST_THRESHOLD),
        ).fetchall()
    candidates = {row["project"] for row in rows if row["project"]}
    if candidates:
        log.debug("burst_detector stage 1: %d candidate projects (of total queried)", len(candidates))
    return candidates


def detect_bursts(db: EventsDB, lookback_hours: int = 24) -> list[dict]:
    """
    Scan recent claude events for burst patterns.

    R60 MinerU: Two-stage progressive detection —
      Stage 1 (cheap): SQL COUNT aggregate filters out projects below threshold.
      Stage 2 (expensive): Full sliding window scan only on candidate projects.

    Returns list of detected bursts:
      [{ project, session_count, approx_tokens, window_start, window_end }, ...]
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    # Stage 1: cheap pre-filter
    candidates = _cheap_candidate_filter(db, since)
    if not candidates:
        return []

    # Stage 2: load rows only for candidate projects — full sliding window
    placeholders = ",".join("?" for _ in candidates)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT metadata, occurred_at FROM events "
            f"WHERE source = 'claude' AND occurred_at >= ? "
            f"AND json_extract(metadata, '$.project') IN ({placeholders}) "
            f"ORDER BY occurred_at ASC",
            (since, *candidates),
        ).fetchall()

    # Group sessions by project
    by_project: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
        except (json.JSONDecodeError, TypeError):
            continue
        project = meta.get("project", "unknown")
        if project not in candidates:
            continue
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
