"""Checkpoint Sink — persists ExecutionStream checkpoint events to EventsDB.

Stolen from Claude Code v2.1.88 queryCheckpoint pattern.
Bridges the streaming checkpoint events into durable storage for
post-hoc latency analysis.
"""
import logging
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class CheckpointSink:
    """Consumes ExecutionEvent checkpoint events and writes them to DB.

    Usage:
        sink = CheckpointSink(db)
        async for event in stream.execute(task_id):
            sink.maybe_persist(event)
            # ... handle other events
    """

    def __init__(self, db: EventsDB, session_id: str = ""):
        self._db = db
        self._session_id = session_id

    def maybe_persist(self, event) -> bool:
        """If event is a checkpoint, persist to DB. Returns True if persisted."""
        if getattr(event, 'event_type', None) != "checkpoint":
            return False
        try:
            name = event.data.get("name", "unknown")
            timestamp_ms = int(event.timestamp * 1000)
            self._db.add_checkpoint(
                task_id=event.task_id,
                name=name,
                timestamp_ms=timestamp_ms,
                session_id=self._session_id,
            )
            return True
        except Exception as e:
            log.warning(f"CheckpointSink: failed to persist checkpoint: {e}")
            return False
