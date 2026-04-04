"""Evolution loop job entry points — thin wrappers for scheduler registration."""
from __future__ import annotations

import logging

from src.evolution.loop import EvolutionEngine
from src.storage.events_db import EventsDB

logger = logging.getLogger(__name__)

# Module-level singleton — keeps state between cycles
_engine: EvolutionEngine | None = None


def _get_registry():
    """Lazy import to avoid circular dependency."""
    try:
        from src.channels.registry import get_channel_registry
        return get_channel_registry()
    except Exception:
        return None


def _get_engine(db: EventsDB) -> EvolutionEngine:
    global _engine
    if _engine is None:
        _engine = EvolutionEngine(db=db, channel_registry=_get_registry())
    return _engine


def evolution_cycle(db: EventsDB) -> None:
    """Run one evolution cycle (detect -> classify -> act -> evaluate -> learn)."""
    engine = _get_engine(db)
    results = engine.run_cycle()
    if results:
        executed = sum(1 for r in results if r.executed)
        blocked = sum(1 for r in results if not r.executed)
        db.write_log(
            f"Evolution cycle: {len(results)} signals -> {executed} executed, {blocked} blocked",
            "INFO", "evolution",
        )


def steal_patrol(db: EventsDB) -> None:
    """Weekly steal patrol — scan watchlist repos for new patterns."""
    from src.evolution.actions import StealPatrolAction
    action = StealPatrolAction()
    result = action.execute(db, signal_data={})
    if result.detail:
        db.write_log(
            f"Steal patrol: {result.status.value} — {result.detail}",
            "INFO", "evolution",
        )
