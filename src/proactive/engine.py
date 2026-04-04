"""ProactiveEngine — scan loop that wires SignalDetector → ThrottleGate → MessageGenerator → Channel."""
from __future__ import annotations

import logging
from typing import Any

from src.channels.base import ChannelMessage
from src.proactive.messages import MessageGenerator
from src.proactive.signals import Signal, SignalDetector
from src.proactive.throttle import ThrottleGate
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

# Tier → ChannelMessage priority
_PRIORITY_MAP: dict[str, str] = {
    "A": "CRITICAL",
    "B": "HIGH",
    "C": "NORMAL",
    "D": "LOW",
}


class ProactiveEngine:
    """Orchestrates the proactive scan cycle.

    Each ``run_scan()`` call:
    1. Detects all signals via ``SignalDetector``
    2. Drains previously queued signals from ThrottleGate
    3. For each signal, checks ThrottleGate
    4. Generates a message via MessageGenerator
    5. Broadcasts via ChannelRegistry
    6. Persists outcome to ``proactive_log``
    """

    def __init__(
        self,
        db: EventsDB,
        channel_registry: Any,
        llm_router: Any | None = None,
    ) -> None:
        self._db = db
        self._registry = channel_registry
        self._detector = SignalDetector(db)
        self._throttle = ThrottleGate()
        self._messenger = MessageGenerator(llm_router)

    # ── public API ────────────────────────────────────────────────────────────

    def run_scan(self) -> tuple[int, int]:
        """Run one scan cycle. Returns (sent_count, throttled_count)."""
        signals = self._detector.detect_all()

        # Drain signals queued from previous cycles (time-window / rate cap)
        queued = self._throttle.drain_queued()
        signals.extend(queued)

        sent = 0
        throttled = 0

        for sig in signals:
            if self._throttle.should_send(sig):
                ok = self._try_send(sig)
                if ok:
                    sent += 1
                    self._throttle.record_sent(sig)
            else:
                throttled += 1
                self._db.log_proactive(
                    signal_id=sig.id,
                    tier=sig.tier,
                    severity=sig.severity,
                    data=sig.data,
                    message="",
                    action="throttled",
                    reason="throttle_gate",
                )

        if sent or throttled:
            logger.info("Proactive scan: sent=%d throttled=%d", sent, throttled)
        return sent, throttled

    # ── internals ─────────────────────────────────────────────────────────────

    def _try_send(self, sig: Signal) -> bool:
        """Generate message, broadcast, and log. Returns True on success."""
        try:
            text = self._messenger.generate(sig)
            msg = ChannelMessage(
                text=text,
                event_type=f"proactive.{sig.id}",
                priority=self._map_priority(sig.tier, sig.severity),
                department="proactive",
            )
            self._registry.broadcast(msg)
            self._db.log_proactive(
                signal_id=sig.id,
                tier=sig.tier,
                severity=sig.severity,
                data=sig.data,
                message=text,
                action="sent",
            )
            return True
        except Exception:
            logger.exception("Failed to send signal %s", sig.id)
            self._db.log_proactive(
                signal_id=sig.id,
                tier=sig.tier,
                severity=sig.severity,
                data=sig.data,
                message="",
                action="send_failed",
                reason="broadcast_exception",
            )
            return False

    @staticmethod
    def _map_priority(tier: str, severity: str) -> str:
        """Map signal tier to ChannelMessage priority level."""
        return _PRIORITY_MAP.get(tier, "NORMAL")
