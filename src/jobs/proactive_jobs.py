"""Proactive job entry points — thin wrappers for scheduler registration."""
from __future__ import annotations

import logging

from src.channels.base import ChannelMessage
from src.proactive.digest import DigestBuilder
from src.proactive.engine import ProactiveEngine
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

# Module-level singleton — ThrottleGate holds in-memory state (_sent_log, _queued)
# that must persist across scan cycles. DO NOT create a new engine per call.
_engine: ProactiveEngine | None = None


def _get_registry():
    """Lazy import to avoid circular dependency at module level."""
    from src.channels.registry import get_channel_registry
    return get_channel_registry()


def _get_engine(db: EventsDB) -> ProactiveEngine:
    """Return the singleton ProactiveEngine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = ProactiveEngine(db=db, channel_registry=_get_registry())
    return _engine


def proactive_scan(db: EventsDB) -> None:
    """Run one proactive signal scan cycle."""
    engine = _get_engine(db)
    sent, throttled = engine.run_scan()
    if sent or throttled:
        db.write_log(
            f"Proactive scan: sent={sent} throttled={throttled}",
            "INFO", "proactive",
        )


def proactive_daily_digest(db: EventsDB) -> None:
    """Build and broadcast daily digest."""
    builder = DigestBuilder(db)
    text = builder.build_daily()
    if text is None:
        logger.info("Daily digest: nothing to report")
        return
    registry = _get_registry()
    registry.broadcast(ChannelMessage(
        text=text,
        event_type="proactive.digest.daily",
        priority="NORMAL",
        department="proactive",
    ))
    db.write_log("Daily digest sent", "INFO", "proactive")


def proactive_weekly_digest(db: EventsDB) -> None:
    """Build and broadcast weekly digest."""
    builder = DigestBuilder(db)
    text = builder.build_weekly()
    if text is None:
        logger.info("Weekly digest: nothing to report")
        return
    registry = _get_registry()
    registry.broadcast(ChannelMessage(
        text=text,
        event_type="proactive.digest.weekly",
        priority="NORMAL",
        department="proactive",
    ))
    db.write_log("Weekly digest sent", "INFO", "proactive")
