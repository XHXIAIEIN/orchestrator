"""InputCapture -- record user mouse/keyboard events for trajectory injection.

Runs pynput listeners in daemon threads.  Events are debounced and aggregated
into standard action dicts (same schema as ALLOWED_ACTIONS), then drained by
the engine between perception-action steps.

Debounce rules (borrowed from bytebot):
  - click:  250 ms window, deduplicate, keep highest clickCount
  - typing: 500 ms idle → flush accumulated chars as one type_text action
  - scroll: aggregate up to 4 consecutive scrolls into one action
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Debounce windows (seconds)
_CLICK_DEBOUNCE = 0.25
_TYPE_DEBOUNCE = 0.50
_SCROLL_AGGREGATE = 4  # max scroll events to merge


@dataclass
class InputCapture:
    """Capture user input events and convert to action dicts.

    Usage::

        cap = InputCapture()
        cap.start()
        # ... engine loop ...
        user_actions = cap.drain()   # returns list[dict], clears buffer
        cap.stop()
    """

    _buffer: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _mouse_listener: object = None
    _keyboard_listener: object = None
    _running: bool = False

    # -- typing aggregation state --
    _typing_chars: list[str] = field(default_factory=list)
    _typing_last: float = 0.0
    _typing_timer: threading.Timer | None = None

    # -- click dedup state --
    _last_click_time: float = 0.0
    _last_click_pos: tuple[int, int] = (0, 0)
    _last_click_count: int = 0
    _click_timer: threading.Timer | None = None

    # -- scroll aggregation state --
    _scroll_acc: int = 0
    _scroll_pos: tuple[int, int] = (0, 0)
    _scroll_count: int = 0
    _scroll_timer: threading.Timer | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start listening for user input events."""
        if self._running:
            return
        try:
            from pynput import mouse, keyboard

            self._mouse_listener = mouse.Listener(
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            )
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press,
            )
            self._mouse_listener.daemon = True
            self._keyboard_listener.daemon = True
            self._mouse_listener.start()
            self._keyboard_listener.start()
            self._running = True
            log.info("input_capture: started")
        except ImportError:
            log.warning("input_capture: pynput not available -- disabled")
        except Exception as exc:
            log.warning("input_capture: failed to start: %s", exc)

    def stop(self) -> None:
        """Stop listening and flush pending aggregations."""
        self._running = False
        self._flush_typing()
        self._flush_click()
        self._flush_scroll()

        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._mouse_listener = None
        self._keyboard_listener = None
        log.info("input_capture: stopped")

    def drain(self) -> list[dict]:
        """Return all buffered user actions and clear the buffer."""
        # Flush any pending aggregations first
        self._flush_typing()
        self._flush_click()
        self._flush_scroll()

        with self._lock:
            actions = list(self._buffer)
            self._buffer.clear()
        return actions

    # ------------------------------------------------------------------ #
    # Mouse handlers
    # ------------------------------------------------------------------ #

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed:
            return

        now = time.time()
        pos = (int(x), int(y))

        with self._lock:
            # Same position within debounce window → increment click count
            if (now - self._last_click_time < _CLICK_DEBOUNCE
                    and pos == self._last_click_pos):
                self._last_click_count += 1
                self._last_click_time = now
                # Reset the flush timer
                if self._click_timer:
                    self._click_timer.cancel()
                self._click_timer = threading.Timer(
                    _CLICK_DEBOUNCE, self._flush_click)
                self._click_timer.daemon = True
                self._click_timer.start()
                return

            # New click -- flush previous if any
            self._flush_click_locked()

            self._last_click_pos = pos
            self._last_click_count = 1
            self._last_click_time = now

            btn_name = "left"
            if hasattr(button, "name"):
                btn_name = button.name  # "left" / "right" / "middle"

            # Store button for flush
            self._last_click_button = btn_name

            self._click_timer = threading.Timer(
                _CLICK_DEBOUNCE, self._flush_click)
            self._click_timer.daemon = True
            self._click_timer.start()

    def _flush_click(self) -> None:
        with self._lock:
            self._flush_click_locked()

    def _flush_click_locked(self) -> None:
        """Must be called with self._lock held."""
        if self._last_click_count == 0:
            return

        x, y = self._last_click_pos
        count = self._last_click_count
        btn = getattr(self, "_last_click_button", "left")

        if count >= 2:
            action = {"action": "double_click", "x": x, "y": y}
        elif btn == "right":
            action = {"action": "right_click", "x": x, "y": y}
        else:
            action = {"action": "click", "x": x, "y": y, "button": btn}

        self._buffer.append(action)
        self._last_click_count = 0

        if self._click_timer:
            self._click_timer.cancel()
            self._click_timer = None

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        with self._lock:
            self._scroll_pos = (int(x), int(y))
            self._scroll_acc += dy
            self._scroll_count += 1

            if self._scroll_count >= _SCROLL_AGGREGATE:
                self._flush_scroll_locked()
                return

            # Reset timer
            if self._scroll_timer:
                self._scroll_timer.cancel()
            self._scroll_timer = threading.Timer(0.3, self._flush_scroll)
            self._scroll_timer.daemon = True
            self._scroll_timer.start()

    def _flush_scroll(self) -> None:
        with self._lock:
            self._flush_scroll_locked()

    def _flush_scroll_locked(self) -> None:
        if self._scroll_acc == 0:
            return

        x, y = self._scroll_pos
        self._buffer.append({
            "action": "scroll",
            "x": x, "y": y,
            "clicks": self._scroll_acc,
        })
        self._scroll_acc = 0
        self._scroll_count = 0

        if self._scroll_timer:
            self._scroll_timer.cancel()
            self._scroll_timer = None

    # ------------------------------------------------------------------ #
    # Keyboard handler
    # ------------------------------------------------------------------ #

    def _on_key_press(self, key) -> None:
        try:
            char = key.char
        except AttributeError:
            # Special key (Enter, Ctrl, etc.) -- flush typing, emit hotkey
            self._flush_typing()
            key_name = key.name if hasattr(key, "name") else str(key)
            with self._lock:
                self._buffer.append({
                    "action": "hotkey",
                    "keys": [key_name],
                })
            return

        if char is None:
            return

        now = time.time()
        with self._lock:
            self._typing_chars.append(char)
            self._typing_last = now

            # Reset the typing flush timer
            if self._typing_timer:
                self._typing_timer.cancel()
            self._typing_timer = threading.Timer(
                _TYPE_DEBOUNCE, self._flush_typing)
            self._typing_timer.daemon = True
            self._typing_timer.start()

    def _flush_typing(self) -> None:
        with self._lock:
            if not self._typing_chars:
                return
            text = "".join(self._typing_chars)
            self._typing_chars.clear()
            self._buffer.append({
                "action": "type_text",
                "text": text,
            })
            if self._typing_timer:
                self._typing_timer.cancel()
                self._typing_timer = None
