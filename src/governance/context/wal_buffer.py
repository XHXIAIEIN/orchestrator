# src/governance/context/wal_buffer.py
"""WAL Buffer — Context Danger Zone Log.

Source: ClawHub proactive-agent (Round 14)

When context usage reaches 60%, start appending human messages + agent
summaries to a working buffer file.  After compaction clears the context
window, the buffer provides a recovery bridge so the next prompt can
re-ingest the key points that were lost.

Lifecycle:
    1. Context hits 60% → activate buffer, clear previous entries
    2. Each turn: append human message + 1-2 sentence agent summary
    3. Compaction fires → buffer survives on disk
    4. Session resumes → load buffer into context preamble
    5. Context hits 60% again → cycle repeats

The buffer is intentionally simple (markdown, append-only) so it works
even when the LLM is unavailable or token-constrained.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Activation threshold: fraction of context window
DANGER_ZONE_THRESHOLD = 0.60
# Max buffer entries before rotating (prevent unbounded growth)
MAX_BUFFER_ENTRIES = 50

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_BUFFER_PATH = REPO_ROOT / "data" / "working-buffer.md"


@dataclass
class BufferEntry:
    """A single turn captured in the WAL buffer."""
    timestamp: float
    role: str  # "human" or "agent"
    content: str

    def to_markdown(self) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        label = "Human" if self.role == "human" else "Agent (summary)"
        return f"[{ts}] **{label}**: {self.content}"


@dataclass
class WALBuffer:
    """Write-Ahead Log for context danger zone.

    Usage:
        buf = WALBuffer()

        # Each turn, check if we should be buffering
        if buf.should_activate(current_tokens, max_tokens):
            buf.activate()

        if buf.active:
            buf.append("human", user_message)
            buf.append("agent", agent_summary)

        # After compaction, recover
        recovery_text = buf.recover()
    """

    buffer_path: Path = field(default_factory=lambda: DEFAULT_BUFFER_PATH)
    active: bool = False
    entries: list[BufferEntry] = field(default_factory=list)
    threshold: float = DANGER_ZONE_THRESHOLD

    def should_activate(self, current_tokens: int, max_tokens: int) -> bool:
        """Check if context usage has crossed the danger zone threshold."""
        if max_tokens <= 0:
            return False
        ratio = current_tokens / max_tokens
        return ratio >= self.threshold

    def activate(self) -> None:
        """Start a new buffer cycle, clearing previous entries."""
        self.active = True
        self.entries.clear()
        log.info("wal_buffer: activated (context in danger zone)")

    def deactivate(self) -> None:
        """Stop buffering (e.g., after recovery is consumed)."""
        self.active = False

    def append(self, role: str, content: str) -> None:
        """Append a turn to the buffer."""
        if not self.active:
            return
        if not content or not content.strip():
            return

        # Truncate very long messages to keep buffer lean
        truncated = content[:500] + "..." if len(content) > 500 else content

        self.entries.append(BufferEntry(
            timestamp=time.time(),
            role=role,
            content=truncated.strip(),
        ))

        # Rotate if too many entries (keep most recent)
        if len(self.entries) > MAX_BUFFER_ENTRIES:
            self.entries = self.entries[-MAX_BUFFER_ENTRIES:]

        self._flush()

    def _flush(self) -> None:
        """Persist buffer to disk."""
        try:
            self.buffer_path.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "# Working Buffer (Danger Zone Log)",
                f"<!-- Status: ACTIVE | Entries: {len(self.entries)} -->",
                "",
            ]
            for entry in self.entries:
                lines.append(entry.to_markdown())
            self.buffer_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            log.warning(f"wal_buffer: flush failed: {e}")

    def recover(self) -> str | None:
        """Load buffer content for post-compaction recovery.

        Returns markdown text suitable for injection into context preamble,
        or None if no buffer exists.
        """
        path = self.buffer_path
        if not path.exists():
            return None

        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text or "Entries: 0" in text:
                return None

            recovery = (
                "## Context Recovery (from WAL Buffer)\n\n"
                "The following is a summary of the conversation before "
                "context compaction. Use it to maintain continuity.\n\n"
                f"{text}\n"
            )
            log.info(f"wal_buffer: recovered {len(self.entries)} entries")
            return recovery
        except Exception as e:
            log.warning(f"wal_buffer: recovery failed: {e}")
            return None

    def clear(self) -> None:
        """Clear buffer (after successful recovery consumption)."""
        self.entries.clear()
        self.active = False
        if self.buffer_path.exists():
            try:
                self.buffer_path.write_text(
                    "# Working Buffer (Danger Zone Log)\n"
                    "<!-- Status: INACTIVE | Entries: 0 -->\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

    @classmethod
    def load_from_disk(cls, buffer_path: Path | None = None) -> WALBuffer:
        """Load existing buffer state from disk."""
        path = buffer_path or DEFAULT_BUFFER_PATH
        buf = cls(buffer_path=path)
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                buf.active = "ACTIVE" in text and "INACTIVE" not in text
            except Exception:
                pass
        return buf
