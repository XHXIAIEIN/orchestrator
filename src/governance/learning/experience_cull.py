# src/governance/learning/experience_cull.py
"""Usage-based experience culling — auto-retire stale learnings.

Stolen from claude-cognitive's usage-based experience management.

Problem: learnings table grows forever. Old rules that never match become
noise in dispatch context, wasting tokens and diluting signal.

Solution:
1. Track hits: every time a learning is matched during dispatch, bump hit_count + last_hit_at
2. Periodic cull: learnings with low recurrence + old last_hit_at → auto retire
3. Promotion gate: only promote learnings that have proven their value (hit_count > threshold)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# Minimum days since last hit before considering retirement
STALE_DAYS = 30
# Minimum hit count to be considered "proven"
MIN_HITS_FOR_PROVEN = 3
# Maximum age (days) for a never-hit learning before auto-retire
MAX_UNHIT_AGE_DAYS = 14
# Minimum hit count to be eligible for promotion
MIN_HITS_FOR_PROMOTION = 5


@dataclass
class CullReport:
    """Results of a culling run."""
    retired: list[dict]       # learnings that were retired
    at_risk: list[dict]       # learnings approaching retirement
    promoted: list[dict]      # learnings promoted due to high usage
    total_active: int = 0

    def format(self) -> str:
        lines = [f"Experience Cull Report — {self.total_active} active learnings"]
        if self.retired:
            lines.append(f"  🗑 Retired {len(self.retired)}:")
            for l in self.retired[:5]:
                lines.append(f"    - {l['pattern_key']} (hits={l.get('hit_count', 0)}, age={l.get('age_days', '?')}d)")
        if self.at_risk:
            lines.append(f"  ⚠ At risk {len(self.at_risk)}:")
            for l in self.at_risk[:5]:
                lines.append(f"    - {l['pattern_key']} (hits={l.get('hit_count', 0)}, last_hit={l.get('days_since_hit', '?')}d ago)")
        if self.promoted:
            lines.append(f"  ⬆ Auto-promoted {len(self.promoted)}:")
            for l in self.promoted[:5]:
                lines.append(f"    - {l['pattern_key']} (hits={l.get('hit_count', 0)})")
        return "\n".join(lines)


def record_hit(db, learning_id: int) -> None:
    """Record that a learning was matched during dispatch.

    Requires hit_count and last_hit_at columns on learnings table.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db._connect() as conn:
            conn.execute(
                "UPDATE learnings SET hit_count = COALESCE(hit_count, 0) + 1, last_hit_at = ? WHERE id = ?",
                (now, learning_id),
            )
    except Exception as e:
        log.debug(f"Failed to record hit for learning #{learning_id}: {e}")


def run_cull(db) -> CullReport:
    """Analyze all active learnings and retire stale ones.

    Call periodically (e.g., daily or after each governor cycle).
    """
    now = datetime.now(timezone.utc)
    report = CullReport(retired=[], at_risk=[], promoted=[])

    try:
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT id, pattern_key, recurrence, status, created_at, "
                "COALESCE(hit_count, 0) as hit_count, last_hit_at, "
                "COALESCE(ttl_days, 0) as ttl_days, expires_at "
                "FROM learnings WHERE status IN ('pending', 'promoted')"
            ).fetchall()
    except Exception as e:
        log.error(f"Experience cull query failed: {e}")
        return report

    active = [dict(r) for r in rows]
    report.total_active = len(active)

    to_retire = []
    to_promote = []

    for l in active:
        created = _parse_iso(l.get("created_at", ""))
        last_hit = _parse_iso(l.get("last_hit_at", ""))
        expires = _parse_iso(l.get("expires_at", ""))
        hit_count = l.get("hit_count", 0)

        age_days = (now - created).days if created else 0
        days_since_hit = (now - last_hit).days if last_hit else age_days

        l["age_days"] = age_days
        l["days_since_hit"] = days_since_hit

        # Rule 0: TTL expiry — temporary facts past their expiration date
        if expires and now > expires:
            l["_retire_reason"] = "ttl_expired"
            to_retire.append(l)
            continue

        # Rule 1: Never-hit learning older than MAX_UNHIT_AGE_DAYS → retire
        if hit_count == 0 and age_days > MAX_UNHIT_AGE_DAYS:
            to_retire.append(l)
            continue

        # Rule 2: Low-hit learning with stale last_hit → retire
        if hit_count < MIN_HITS_FOR_PROVEN and days_since_hit > STALE_DAYS:
            to_retire.append(l)
            continue

        # Rule 3: At-risk (approaching retirement)
        if hit_count < MIN_HITS_FOR_PROVEN and days_since_hit > STALE_DAYS * 0.7:
            report.at_risk.append(l)

        # Rule 4: High-usage pending learning → auto-promote
        if l["status"] == "pending" and hit_count >= MIN_HITS_FOR_PROMOTION:
            to_promote.append(l)

    # Execute retirements
    for l in to_retire:
        try:
            db.retire_learning(l["id"])
            report.retired.append(l)
            log.info(f"Retired stale learning: {l['pattern_key']} (hits={l.get('hit_count', 0)}, age={l.get('age_days', 0)}d)")
        except Exception as e:
            log.debug(f"Failed to retire learning #{l['id']}: {e}")

    # Execute promotions
    for l in to_promote:
        try:
            db.promote_learning(l["id"])
            report.promoted.append(l)
            log.info(f"Auto-promoted learning: {l['pattern_key']} (hits={l.get('hit_count', 0)})")
        except Exception as e:
            log.debug(f"Failed to promote learning #{l['id']}: {e}")

    if report.retired or report.promoted:
        log.info(report.format())

    return report


def _parse_iso(s: str) -> datetime | None:
    """Parse ISO datetime string, return None on failure."""
    if not s:
        return None
    try:
        # Handle both with and without timezone
        if "+" in s or s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
