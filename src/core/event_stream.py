"""EventStream — bounded deque with sequence numbers for cursor-based polling.

Stolen from ChatDev 2.0's server/artifact_events.py (ArtifactEventQueue).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    event_type: str
    data: dict[str, Any]
    sequence: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {"sequence": self.sequence, "event_type": self.event_type,
                "data": self.data, "timestamp": self.timestamp}


class EventStream:
    def __init__(self, max_events: int = 2000):
        self._max_events = max_events
        self._events: deque[StreamEvent] = deque()
        self._last_sequence: int = 0
        self._total_appended: int = 0
        self._condition = threading.Condition()

    def append(self, event: StreamEvent):
        with self._condition:
            self._last_sequence += 1
            self._total_appended += 1
            event.sequence = self._last_sequence
            event.timestamp = event.timestamp or time.time()
            self._events.append(event)
            while len(self._events) > self._max_events:
                self._events.popleft()
            self._condition.notify_all()

    def get_after(self, after: int = 0, limit: int = 500,
                  event_types: set[str] | None = None) -> tuple[list[StreamEvent], int]:
        with self._condition:
            result = []
            for event in self._events:
                if event.sequence <= after:
                    continue
                if event_types and event.event_type not in event_types:
                    continue
                result.append(event)
                if len(result) >= limit:
                    break
            new_cursor = result[-1].sequence if result else after
            return result, new_cursor

    def wait_for_events(self, after: int = 0, timeout: float = 30.0,
                        event_types: set[str] | None = None,
                        limit: int = 500) -> tuple[list[StreamEvent], int, bool]:
        deadline = time.time() + timeout
        with self._condition:
            while True:
                events, cursor = self.get_after(after, limit, event_types)
                if events:
                    return events, cursor, False
                remaining = deadline - time.time()
                if remaining <= 0:
                    return [], after, True
                self._condition.wait(timeout=min(remaining, 1.0))

    def stats(self) -> dict:
        with self._condition:
            min_seq = self._events[0].sequence if self._events else 0
            return {"current_size": len(self._events), "max_events": self._max_events,
                    "last_sequence": self._last_sequence, "min_sequence": min_seq,
                    "total_appended": self._total_appended}
