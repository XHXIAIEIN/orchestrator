"""Windowed Stream Processor — process agent output in sliding windows.

Stolen from: microsoft/VibeVoice (Round 17)
Pattern: Windowed Streaming Generation

VibeVoice feeds text in windows of 5 tokens, immediately generating 6 speech
tokens per window. This text-window → action-window interleaving drastically
reduces time-to-first-output.

For Orchestrator: instead of waiting for a sub-agent to finish entirely,
process its output in windows. Each window triggers downstream actions
(DB writes, notifications, format conversions) immediately.

Window types:
  - ToolCallWindow:  A completed tool call result
  - VerdictWindow:   A VERDICT/STATUS/RESULT line
  - TextWindow:      N characters of accumulated text
  - FinalWindow:     The last chunk (is_final=True)

Usage:
    processor = WindowedStreamProcessor(
        window_size=5,  # trigger every 5 meaningful chunks
        on_window=lambda w: db.write_partial_result(task_id, w),
    )

    async for message in agent_session:
        processor.feed(message)
        # on_window fires automatically when a window is complete

    processor.flush()  # Process any remaining buffered content
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Default window sizes (analogous to VibeVoice's TTS_TEXT_WINDOW_SIZE=5)
DEFAULT_TEXT_WINDOW_SIZE = 5        # trigger every N text chunks
DEFAULT_TOOL_WINDOW_SIZE = 1        # trigger on every tool call (immediate)
DEFAULT_CHAR_ACCUMULATION = 1500    # trigger when accumulated chars exceed this


@dataclass
class StreamWindow:
    """A single processing window."""
    window_type: str       # "tool_call" | "verdict" | "text" | "final"
    index: int             # Window sequence number
    content: str           # Window content
    metadata: dict = field(default_factory=dict)
    is_final: bool = False


# Callback type: receives a StreamWindow, returns optional action result
WindowCallback = Callable[[StreamWindow], Any]


class WindowedStreamProcessor:
    """Process streaming agent output in fixed-size windows.

    Mirrors VibeVoice's generate() loop:
    - Feed input chunks (text blocks, tool calls, verdicts)
    - When a window boundary is reached, fire the callback
    - Flush remaining content at the end
    """

    def __init__(
        self,
        on_window: WindowCallback | None = None,
        text_window_size: int = DEFAULT_TEXT_WINDOW_SIZE,
        char_threshold: int = DEFAULT_CHAR_ACCUMULATION,
    ):
        self._on_window = on_window
        self._text_window_size = text_window_size
        self._char_threshold = char_threshold

        # State
        self._text_buffer: list[str] = []
        self._char_count = 0
        self._window_index = 0
        self._windows: list[StreamWindow] = []
        self._finished = False

    def feed_text(self, text: str) -> StreamWindow | None:
        """Feed a text chunk. Returns a window if threshold reached."""
        if self._finished:
            return None

        self._text_buffer.append(text)
        self._char_count += len(text)

        # Check for verdict/status lines — these get their own window immediately
        verdict = _extract_verdict(text)
        if verdict:
            return self._emit_window("verdict", verdict)

        # Check text window threshold
        if (len(self._text_buffer) >= self._text_window_size or
                self._char_count >= self._char_threshold):
            return self._flush_text_buffer()

        return None

    def feed_tool_call(self, tool_name: str, result_preview: str = "") -> StreamWindow | None:
        """Feed a tool call result. Always emits a window immediately.

        Tool calls are high-signal events — like VibeVoice treating each
        speech token group as immediately playable output.
        """
        if self._finished:
            return None

        # Flush any pending text first
        self._flush_text_buffer()

        content = f"[{tool_name}]"
        if result_preview:
            content += f" {result_preview[:300]}"

        return self._emit_window("tool_call", content, metadata={"tool": tool_name})

    def flush(self) -> StreamWindow | None:
        """Flush remaining buffered content as the final window."""
        if self._finished:
            return None

        self._finished = True

        if self._text_buffer:
            return self._flush_text_buffer(is_final=True)

        # Even with no buffer, emit a final window for bookkeeping
        return self._emit_window("final", "", is_final=True)

    def _flush_text_buffer(self, is_final: bool = False) -> StreamWindow | None:
        """Flush accumulated text buffer into a window."""
        if not self._text_buffer:
            return None

        content = "\n".join(self._text_buffer)
        self._text_buffer.clear()
        self._char_count = 0

        return self._emit_window("text", content, is_final=is_final)

    def _emit_window(
        self,
        window_type: str,
        content: str,
        is_final: bool = False,
        metadata: dict | None = None,
    ) -> StreamWindow:
        """Create and emit a window, firing the callback."""
        window = StreamWindow(
            window_type=window_type,
            index=self._window_index,
            content=content,
            metadata=metadata or {},
            is_final=is_final,
        )
        self._window_index += 1
        self._windows.append(window)

        if self._on_window:
            try:
                self._on_window(window)
            except Exception as e:
                log.warning(f"WindowedStream: callback failed for window #{window.index}: {e}")

        return window

    @property
    def windows(self) -> list[StreamWindow]:
        """All emitted windows so far."""
        return list(self._windows)

    @property
    def window_count(self) -> int:
        return self._window_index

    @property
    def is_finished(self) -> bool:
        return self._finished


def _extract_verdict(text: str) -> str | None:
    """Extract verdict/status lines from text chunk."""
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.upper().startswith(p) for p in (
            "VERDICT:", "STATUS:", "RESULT:", "DONE:", "ERROR:", "FAILED:",
            "判定:", "状态:", "结果:", "完成:", "错误:", "失败:",
        )):
            return stripped
    return None
