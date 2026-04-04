"""ProactiveEngine — scan signals, throttle, generate, push."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from src.proactive import config as cfg
from src.proactive.signals import Signal, SignalDetector
from src.proactive.throttle import ThrottleGate
from src.proactive.messages import MessageGenerator

if TYPE_CHECKING:
    from src.channels.base import ChannelMessage
    from src.channels.registry import ChannelRegistry
    from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

class ProactiveEngine:
    """Main loop: detect → throttle → generate → push."""

    def __init__(self, db, registry, llm_router):
        self.db = db
        self.registry = registry
        self.detector = SignalDetector(db)
        self.throttle = ThrottleGate()
        self.generator = MessageGenerator(llm_router)

    def scan_cycle(self):
        """Single scan cycle — called by scheduler every N minutes."""
        signals = self.detector.detect_all()
        if not signals:
            return
        log.debug(f"proactive: detected {len(signals)} signals")
        llm_calls = 0
        for signal in signals:
            if signal.tier in ("B", "C") and llm_calls >= cfg.MAX_LLM_PER_SCAN:
                self._log_signal(signal, action="throttled", reason="llm_cap")
                continue
            if not self.throttle.should_send(signal):
                self._log_signal(signal, action="throttled", reason="throttle_gate")
                continue
            message = self.generator.generate(signal)
            if signal.tier in ("B", "C"):
                llm_calls += 1
            try:
                from src.channels.base import ChannelMessage
                self.registry.broadcast(ChannelMessage(
                    text=message,
                    event_type=f"proactive.{signal.id}",
                    priority="HIGH" if signal.tier == "A" else "NORMAL",
                ))
                self.throttle.record_sent(signal)
                self._log_signal(signal, message=message, action="sent")
                log.info(f"proactive: pushed {signal.id} ({signal.title})")
            except Exception as e:
                log.warning(f"proactive: broadcast failed for {signal.id}: {e}")
                self._log_signal(signal, message=message, action="failed", reason=str(e))

    def _log_signal(self, signal, message=None, action="sent", reason=""):
        try:
            self.db.log_proactive(
                signal_id=signal.id, tier=signal.tier, severity=signal.severity,
                data=signal.data, message=message, action=action, reason=reason,
            )
        except Exception as e:
            log.warning(f"proactive: failed to log {signal.id}: {e}")

# ── Singleton ──
_instance: ProactiveEngine | None = None

def get_proactive_engine() -> ProactiveEngine | None:
    return _instance

def set_proactive_engine(engine: ProactiveEngine):
    global _instance
    _instance = engine
