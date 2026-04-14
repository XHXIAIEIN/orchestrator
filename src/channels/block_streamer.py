"""R49 (Qwen Code): BlockStreamer — progressive multi-message delivery.

Accumulates text chunks from streaming responses and emits completed
"blocks" (paragraphs/sections) as separate channel messages while
the agent is still working.

Emission triggers:
 1. Buffer >= maxChars → force-split at best break point
 2. Buffer >= minChars AND paragraph boundary (\\n\\n) exists → emit
 3. Idle timer fires (no chunk for idle_s) AND buffer >= minChars → emit
 4. flush() called (response complete) → emit everything remaining

All sends are serialized — the next block waits for the previous send.

Stolen from: Qwen Code packages/channels/base/src/BlockStreamer.ts
"""
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

# Default thresholds (from Qwen Code production values)
DEFAULT_MIN_CHARS = 400
DEFAULT_MAX_CHARS = 1000
DEFAULT_IDLE_S = 1.5


class BlockStreamer:
    """Progressive block-based message delivery for channel adapters.

    Usage:
        streamer = BlockStreamer(send_fn=lambda text: tg_send(chat_id, text))
        for chunk in agent_stream:
            streamer.push(chunk)
        await streamer.flush()  # or streamer.flush_sync()
    """

    def __init__(
        self,
        send_fn: Callable[[str], None],
        min_chars: int = DEFAULT_MIN_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
        idle_s: float = DEFAULT_IDLE_S,
    ):
        self._send_fn = send_fn
        self._min_chars = min_chars
        self._max_chars = max_chars
        self._idle_s = idle_s

        self._buffer = ""
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()  # serializes sends
        self._idle_timer: threading.Timer | None = None
        self.block_count = 0

    def push(self, chunk: str) -> None:
        """Feed a new text chunk from the agent stream."""
        with self._lock:
            self._buffer += chunk
            self._cancel_idle_timer()
            self._check_emit()

            if self._buffer and self._idle_s > 0:
                self._idle_timer = threading.Timer(self._idle_s, self._on_idle)
                self._idle_timer.daemon = True
                self._idle_timer.start()

    def flush_sync(self) -> None:
        """Flush all remaining buffered text. Blocks until all sends complete."""
        with self._lock:
            self._cancel_idle_timer()
            if self._buffer:
                self._emit_block(self._buffer)
                self._buffer = ""
        # Wait for all pending sends to complete
        with self._send_lock:
            pass

    # ── Internal ─────────────────────────────────────────────────────────

    def _check_emit(self) -> None:
        """Check triggers and emit blocks. Called with self._lock held."""
        # Trigger 1: Force-split if buffer exceeds maxChars
        while len(self._buffer) >= self._max_chars:
            bp = self._find_break_point(self._buffer, self._max_chars)
            self._emit_block(self._buffer[:bp])
            self._buffer = self._buffer[bp:]

        # Trigger 2: Emit at paragraph boundary if we have enough text
        if len(self._buffer) >= self._min_chars:
            bp = self._find_block_boundary(self._buffer)
            if bp > 0:
                self._emit_block(self._buffer[:bp])
                self._buffer = self._buffer[bp:]

    def _on_idle(self) -> None:
        """Idle timer expired — emit buffer if large enough."""
        with self._lock:
            self._idle_timer = None
            if len(self._buffer) >= self._min_chars:
                self._emit_block(self._buffer)
                self._buffer = ""

    def _emit_block(self, text: str) -> None:
        """Queue a block for serialized sending. Called with self._lock held."""
        trimmed = text.strip()
        if not trimmed:
            return
        self.block_count += 1
        block_num = self.block_count

        def _do_send():
            with self._send_lock:
                try:
                    self._send_fn(trimmed)
                except Exception as e:
                    log.warning("block_streamer: send failed (block %d): %s", block_num, e)

        # Fire-and-forget in a thread (serialized by _send_lock)
        t = threading.Thread(target=_do_send, name=f"block-send-{block_num}", daemon=True)
        t.start()

    def _find_block_boundary(self, text: str) -> int:
        """Find last paragraph boundary (\\n\\n) at or after minChars.

        Returns position after the boundary, or -1 if none found.
        """
        last = text.rfind("\n\n")
        if last < 0 or last < self._min_chars:
            return -1
        return last + 2

    @staticmethod
    def _find_break_point(text: str, max_pos: int) -> int:
        """Find best break point at or before max_pos.

        Priority: paragraph break > newline > space > hard cut.
        """
        sub = text[:max_pos]
        para = sub.rfind("\n\n")
        if para > 0:
            return para + 2
        nl = sub.rfind("\n")
        if nl > 0:
            return nl + 1
        sp = sub.rfind(" ")
        if sp > 0:
            return sp + 1
        return max_pos

    def _cancel_idle_timer(self) -> None:
        """Cancel pending idle timer. Called with self._lock held."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
