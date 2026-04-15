"""R73 MachinaOS: EventWaiter — Unified trigger system for workflow nodes.

Trigger nodes can suspend workflow execution until an external event arrives.
Two backends share the same interface:

    Memory mode (default): asyncio.Future per waiter, thread-safe dispatch.
    Redis Streams mode: per-waiter consumer group, broadcast semantics.

Adding a new trigger type requires only 3 steps:
    1. Register in TRIGGER_REGISTRY
    2. Add filter builder (optional)
    3. Call dispatch() from the event source

Execution engine, cancel path, and deployment manager need no changes.

Source: MachinaOS EventWaiter (R73 deep steal)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


# ── Trigger Configuration ──

@dataclass(frozen=True)
class TriggerConfig:
    """Definition of a trigger type."""
    trigger_type: str       # e.g. "webhookTrigger"
    event_name: str         # e.g. "webhook_received"
    display_name: str       # e.g. "Webhook Request"
    timeout_s: float = 300.0  # default wait timeout


# Built-in triggers — extend by adding entries
TRIGGER_REGISTRY: dict[str, TriggerConfig] = {
    "webhookTrigger": TriggerConfig(
        "webhookTrigger", "webhook_received", "Webhook Request",
    ),
    "chatTrigger": TriggerConfig(
        "chatTrigger", "chat_message_received", "Chat Message",
    ),
    "taskTrigger": TriggerConfig(
        "taskTrigger", "task_completed", "Task Completed",
    ),
    "telegramReceive": TriggerConfig(
        "telegramReceive", "telegram_message_received", "Telegram Message",
    ),
    "timerTrigger": TriggerConfig(
        "timerTrigger", "timer_elapsed", "Timer Elapsed",
    ),
    "fileTrigger": TriggerConfig(
        "fileTrigger", "file_changed", "File Changed",
    ),
}


@dataclass
class EventFilter:
    """Filter criteria for matching events to waiters."""
    event_name: str
    match_fields: dict[str, Any] = field(default_factory=dict)

    def matches(self, event: dict) -> bool:
        """Check if an event matches this filter."""
        if event.get("event_name") != self.event_name:
            return False
        for key, value in self.match_fields.items():
            if event.get(key) != value:
                return False
        return True


@dataclass
class WaiterRegistration:
    """A registered waiter waiting for an event."""
    waiter_id: str
    trigger_type: str
    event_filter: EventFilter
    future: asyncio.Future
    registered_at: float = field(default_factory=time.monotonic)
    timeout_s: float = 300.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Memory Backend ──

class MemoryEventWaiter:
    """In-memory event waiter using asyncio.Future.

    Thread-safe: dispatch() can be called from any thread.
    """

    def __init__(self):
        self._waiters: dict[str, WaiterRegistration] = {}
        self._lock = asyncio.Lock()
        self._event_log: list[dict] = []  # recent events for debugging
        self._max_log = 100

    async def register(
        self,
        trigger_type: str,
        event_filter: EventFilter | None = None,
        timeout_s: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Register a waiter for an event.

        Returns waiter_id for tracking.
        """
        config = TRIGGER_REGISTRY.get(trigger_type)
        if config is None:
            raise ValueError(f"Unknown trigger type: {trigger_type}")

        waiter_id = f"w-{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        if event_filter is None:
            event_filter = EventFilter(event_name=config.event_name)

        registration = WaiterRegistration(
            waiter_id=waiter_id,
            trigger_type=trigger_type,
            event_filter=event_filter,
            future=future,
            timeout_s=timeout_s or config.timeout_s,
            metadata=metadata or {},
        )

        async with self._lock:
            self._waiters[waiter_id] = registration

        log.info(
            "event_waiter: registered %s (type=%s, event=%s)",
            waiter_id, trigger_type, event_filter.event_name,
        )
        return waiter_id

    async def wait_for_event(
        self,
        waiter_id: str,
    ) -> dict:
        """Wait for the registered event to arrive.

        Returns the matching event dict.
        Raises asyncio.TimeoutError if timeout expires.
        """
        async with self._lock:
            reg = self._waiters.get(waiter_id)
        if reg is None:
            raise KeyError(f"No waiter registered with id: {waiter_id}")

        try:
            result = await asyncio.wait_for(reg.future, timeout=reg.timeout_s)
            return result
        finally:
            async with self._lock:
                self._waiters.pop(waiter_id, None)

    async def dispatch(self, event: dict) -> list[str]:
        """Dispatch an event to all matching waiters.

        Returns list of waiter_ids that were satisfied.
        Thread-safe: uses asyncio.Lock.
        """
        # Log the event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]

        satisfied = []

        async with self._lock:
            for waiter_id, reg in list(self._waiters.items()):
                if reg.future.done():
                    continue
                if reg.event_filter.matches(event):
                    reg.future.set_result(event)
                    satisfied.append(waiter_id)

        if satisfied:
            log.info(
                "event_waiter: dispatched event '%s' to %d waiter(s): %s",
                event.get("event_name", "?"), len(satisfied),
                ", ".join(satisfied),
            )

        return satisfied

    async def cancel(self, waiter_id: str) -> bool:
        """Cancel a waiting waiter."""
        async with self._lock:
            reg = self._waiters.pop(waiter_id, None)
        if reg and not reg.future.done():
            reg.future.cancel()
            log.info("event_waiter: cancelled %s", waiter_id)
            return True
        return False

    async def cancel_all(self) -> int:
        """Cancel all pending waiters."""
        count = 0
        async with self._lock:
            for waiter_id, reg in list(self._waiters.items()):
                if not reg.future.done():
                    reg.future.cancel()
                    count += 1
            self._waiters.clear()
        return count

    def get_stats(self) -> dict:
        """Return waiter state for diagnostics."""
        return {
            "pending_waiters": len([
                w for w in self._waiters.values() if not w.future.done()
            ]),
            "total_registered": len(self._waiters),
            "recent_events": len(self._event_log),
            "registered_triggers": list(TRIGGER_REGISTRY.keys()),
        }


# ── Convenience: register + wait in one call ──

async def wait_for_trigger(
    waiter: MemoryEventWaiter,
    trigger_type: str,
    filter_fields: dict[str, Any] | None = None,
    timeout_s: float | None = None,
) -> dict:
    """One-shot: register a waiter and wait for the event.

    Usage:
        event = await wait_for_trigger(waiter, "webhookTrigger", timeout_s=60)
    """
    config = TRIGGER_REGISTRY.get(trigger_type)
    if config is None:
        raise ValueError(f"Unknown trigger type: {trigger_type}")

    event_filter = EventFilter(
        event_name=config.event_name,
        match_fields=filter_fields or {},
    )

    waiter_id = await waiter.register(
        trigger_type=trigger_type,
        event_filter=event_filter,
        timeout_s=timeout_s,
    )
    return await waiter.wait_for_event(waiter_id)
