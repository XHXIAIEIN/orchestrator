"""DB mixin for evolution_log table."""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class EvolutionMixin:
    """Mixin providing evolution log read/write methods."""

    def log_evolution(
        self,
        signal_id: str,
        action_type: str,
        risk_level: str,
        status: str,
        detail: dict[str, Any] | None = None,
        score_before: float | None = None,
        score_after: float | None = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO evolution_log
                   (signal_id, action_type, risk_level, status, detail, score_before, score_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (signal_id, action_type, risk_level, status,
                 json.dumps(detail or {}, ensure_ascii=False),
                 score_before, score_after),
            )
            return cur.lastrowid

    def get_evolution_history(
        self,
        limit: int = 50,
        action_type: str | None = None,
    ) -> list[dict]:
        q = "SELECT * FROM evolution_log"
        params: list = []
        if action_type:
            q += " WHERE action_type = ?"
            params.append(action_type)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]
