"""DigestBuilder — aggregate proactive_log into daily / weekly HTML digests."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

_TIER_LABELS = {"A": "🔴 Critical", "B": "🟡 Important", "C": "🔵 Info", "D": "⚪ Digest"}
_TIER_ORDER = ["A", "B", "C", "D"]


class DigestBuilder:
    """Build human-readable digest strings from proactive_log history."""

    def __init__(self, db: EventsDB) -> None:
        self._db = db

    # ── public API ────────────────────────────────────────────────────────────

    def build_daily(self) -> str | None:
        """Build a 24h digest. Returns None if nothing to report."""
        rows = self._query_logs(hours=24)
        if not rows:
            return None
        return self._format_digest(rows, period="日报")

    def build_weekly(self) -> str | None:
        """Build a 7-day digest. Returns None if nothing to report."""
        rows = self._query_logs(hours=168)
        if not rows:
            return None
        return self._format_digest(rows, period="周报")

    # ── internals ─────────────────────────────────────────────────────────────

    def _query_logs(self, hours: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._db._connect() as conn:
            rows = conn.execute(
                "SELECT signal_id, tier, severity, message, action, created_at "
                "FROM proactive_log WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _format_digest(self, rows: list[dict], period: str) -> str:
        sent = [r for r in rows if r["action"] == "sent"]
        throttled = [r for r in rows if r["action"] == "throttled"]

        lines: list[str] = [f"<b>📊 Orchestrator {period}</b>"]
        lines.append(f"sent: {len(sent)} | throttled: {len(throttled)}")
        lines.append("")

        # Group sent signals by tier
        by_tier: dict[str, list[dict]] = {}
        for r in sent:
            by_tier.setdefault(r["tier"], []).append(r)

        for tier in _TIER_ORDER:
            group = by_tier.get(tier, [])
            if not group:
                continue
            label = _TIER_LABELS.get(tier, tier)
            lines.append(f"<b>{label} ({len(group)})</b>")
            # Count by signal_id
            id_counts = Counter(r["signal_id"] for r in group)
            for sid, cnt in id_counts.most_common():
                sample = next(r for r in group if r["signal_id"] == sid)
                msg_preview = (sample.get("message") or sid)[:80]
                suffix = f" ×{cnt}" if cnt > 1 else ""
                lines.append(f"  • {msg_preview}{suffix}")
            lines.append("")

        if throttled:
            lines.append(f"<i>🔇 Throttled: {len(throttled)}</i>")

        return "\n".join(lines)
