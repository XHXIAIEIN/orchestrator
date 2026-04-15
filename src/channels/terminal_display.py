"""Terminal Display — structured ANSI output for status dashboards.

Lightweight alternative to a full TUI framework. Renders status panels,
tables, and progress bars directly to terminal with ANSI codes.

R60 MinerU P1-5: LiveAwareLogSink — loguru-compatible sink that
coordinates with live display rendering. Clears live lines before
emitting log text, re-renders after. Prevents log/display interleaving.
"""

import logging
import os
import sys
import threading


class TerminalDisplay:
    """Render structured status panels in the terminal."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"

    def __init__(self, width: int | None = None):
        self._width = width or os.get_terminal_size().columns

    def panel(self, title: str, content: str, border_color: str = "") -> str:
        """Render a bordered panel."""
        color = border_color or self.CYAN
        w = self._width - 2
        lines = content.split("\n")

        result = []
        result.append(f"{color}┌{'─' * w}┐{self.RESET}")
        result.append(f"{color}│{self.RESET} {self.BOLD}{title}{self.RESET}{' ' * (w - len(title) - 1)}{color}│{self.RESET}")
        result.append(f"{color}├{'─' * w}┤{self.RESET}")
        for line in lines:
            padding = w - len(self._strip_ansi(line)) - 1
            if padding < 0:
                padding = 0
            result.append(f"{color}│{self.RESET} {line}{' ' * padding}{color}│{self.RESET}")
        result.append(f"{color}└{'─' * w}┘{self.RESET}")
        return "\n".join(result)

    def table(self, headers: list[str], rows: list[list[str]]) -> str:
        """Render a simple table."""
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(self._strip_ansi(str(cell))))

        result = []
        # Header
        header_line = " │ ".join(
            f"{self.BOLD}{h:<{col_widths[i]}}{self.RESET}" for i, h in enumerate(headers)
        )
        result.append(header_line)
        result.append("─┼─".join("─" * w for w in col_widths))
        # Rows
        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                w = col_widths[i] if i < len(col_widths) else 10
                cells.append(f"{str(cell):<{w}}")
            result.append(" │ ".join(cells))
        return "\n".join(result)

    def progress_bar(self, label: str, value: float, width: int = 30) -> str:
        """Render a progress bar. value is 0.0-1.0."""
        filled = int(value * width)
        empty = width - filled

        if value >= 0.8:
            color = self.RED
        elif value >= 0.5:
            color = self.YELLOW
        else:
            color = self.GREEN

        bar = f"{color}{'█' * filled}{'░' * empty}{self.RESET}"
        pct = f"{value * 100:.0f}%"
        return f"{label}: {bar} {pct}"

    def status_line(self, items: dict[str, str]) -> str:
        """Render a status line with key-value pairs."""
        parts = []
        for key, val in items.items():
            parts.append(f"{self.DIM}{key}:{self.RESET} {val}")
        return " │ ".join(parts)

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """Remove ANSI escape codes for length calculation."""
        import re
        return re.sub(r'\033\[[0-9;]*m', '', text)

    def clear(self):
        """Clear terminal screen."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


class LiveAwareLogSink:
    """R60 MinerU P1-5: log sink that coordinates with live terminal display.

    MinerU pattern (LiveAwareStderrSink): every log write brackets around
    the live display — clear rendered lines before writing, re-render after.
    This prevents log messages from appearing inside the live status panel.

    Compatible with both loguru (as a sink callable) and stdlib logging
    (as a stream object with write/flush).

    Usage with loguru:
        sink = LiveAwareLogSink(sys.stderr)
        logger.remove()
        logger.add(sink, level="INFO")

    Usage with stdlib logging:
        sink = LiveAwareLogSink(sys.stderr)
        handler = logging.StreamHandler(sink)
        logging.root.addHandler(handler)
    """

    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self.lock = threading.RLock()  # RLock: render may trigger log
        self._rendered_lines: int = 0
        self._live_builder = None  # callable that returns list[str]

    def set_live_builder(self, builder) -> None:
        """Register a callable that returns the current live display lines."""
        with self.lock:
            self._live_builder = builder

    def _clear_live(self) -> None:
        """Erase previously rendered live display lines (ANSI cursor control)."""
        if self._rendered_lines <= 0:
            return
        # Move cursor up N lines, erase each
        self.stream.write(f"\033[{self._rendered_lines}A\r")
        for i in range(self._rendered_lines):
            self.stream.write("\033[2K")  # erase line
            if i + 1 < self._rendered_lines:
                self.stream.write("\033[1B\r")  # move down
        # Return to where we started
        if self._rendered_lines > 1:
            self.stream.write(f"\033[{self._rendered_lines - 1}A\r")
        self._rendered_lines = 0

    def _render_live(self) -> None:
        """Re-render the live display below the log output."""
        if not self._live_builder:
            return
        try:
            lines = self._live_builder()
        except Exception:
            return
        if not lines:
            return
        self.stream.write("\n".join(lines))
        self.stream.write("\n")
        self.stream.flush()
        self._rendered_lines = len(lines)

    def write(self, message: str) -> None:
        """Write a log message, bracketed by live display clear/render."""
        with self.lock:
            self._clear_live()
            self.stream.write(message)
            self.stream.flush()
            self._render_live()

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())
