"""Input Event Backflow — unified event model for all channel inputs.

Any channel input (Telegram message, WeChat message, terminal command,
desktop keyboard event) → normalized event → central dispatcher.

Inspired by Carbonyl's ANSI DCS → Chromium event injection.
"""

from dataclasses import dataclass, field
import time
from typing import Callable, Any
from enum import Enum


class EventSource(Enum):
    TELEGRAM = "telegram"
    WECHAT = "wechat"
    TERMINAL = "terminal"
    DESKTOP = "desktop"
    WEBHOOK = "webhook"
    INTERNAL = "internal"


class EventType(Enum):
    MESSAGE = "message"
    COMMAND = "command"
    CALLBACK = "callback"
    FILE = "file"
    REACTION = "reaction"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"


@dataclass
class InputEvent:
    """Normalized input event from any channel."""
    source: EventSource
    event_type: EventType
    content: str
    sender_id: str = ""
    channel_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    raw: Any = None  # Original event object

    @property
    def is_command(self) -> bool:
        return self.event_type == EventType.COMMAND or self.content.startswith("/")


class EventDispatcher:
    """Central dispatcher for backflow events from all channels.

    Channels register as event sources. Handlers register for event patterns.
    All input flows through one dispatcher for unified processing.
    """

    def __init__(self):
        self._handlers: list[tuple[dict, Callable]] = []  # (filter, handler)
        self._middleware: list[Callable] = []
        self._event_log: list[InputEvent] = []
        self._max_log = 1000

    def on(
        self,
        source: EventSource | None = None,
        event_type: EventType | None = None,
        command: str | None = None,
    ) -> Callable:
        """Decorator to register an event handler.

        Usage:
            @dispatcher.on(source=EventSource.TELEGRAM, event_type=EventType.COMMAND)
            def handle_tg_command(event: InputEvent):
                ...
        """
        filter_spec = {}
        if source:
            filter_spec["source"] = source
        if event_type:
            filter_spec["event_type"] = event_type
        if command:
            filter_spec["command"] = command

        def decorator(fn):
            self._handlers.append((filter_spec, fn))
            return fn
        return decorator

    def add_middleware(self, fn: Callable[[InputEvent], InputEvent | None]):
        """Add middleware that can transform or filter events."""
        self._middleware.append(fn)

    def dispatch(self, event: InputEvent) -> list[Any]:
        """Dispatch an event to all matching handlers."""
        # Run middleware
        for mw in self._middleware:
            event = mw(event)
            if event is None:
                return []  # Filtered out

        # Log
        self._event_log.append(event)
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]

        # Find matching handlers
        results = []
        for filter_spec, handler in self._handlers:
            if self._matches(event, filter_spec):
                try:
                    result = handler(event)
                    results.append(result)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Handler failed: {e}")

        return results

    def _matches(self, event: InputEvent, filter_spec: dict) -> bool:
        """Check if an event matches a filter specification."""
        if "source" in filter_spec and event.source != filter_spec["source"]:
            return False
        if "event_type" in filter_spec and event.event_type != filter_spec["event_type"]:
            return False
        if "command" in filter_spec:
            if not event.content.startswith(f"/{filter_spec['command']}"):
                return False
        return True

    def get_recent(self, n: int = 20, source: EventSource | None = None) -> list[InputEvent]:
        """Get recent events, optionally filtered by source."""
        events = self._event_log
        if source:
            events = [e for e in events if e.source == source]
        return events[-n:]
