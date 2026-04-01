"""Coordinator Scratchpad — file-based shared context for cross-worker communication.

Stolen from Claude Code v2.1.88 coordinatorMode.ts scratchpad pattern.
Workers (sub-agents) write findings, context, and intermediate results to
a shared scratchpad directory. The coordinator reads and integrates these
into downstream prompts.

Unlike direct inter-agent messaging, this is async and durable — workers
don't need to be running simultaneously. Files persist until explicit cleanup
or TTL expiry.
"""
import json
import logging
import time
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# Default scratchpad root — inside the project's data directory
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "scratchpad"

# Default TTL: scratchpad entries expire after 1 hour
DEFAULT_TTL_SECONDS = 3600


class ScratchpadEntry:
    """A single scratchpad file with metadata."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem

    @property
    def content(self) -> str:
        """Read file content."""
        try:
            return self.path.read_text(encoding="utf-8")
        except Exception:
            return ""

    @property
    def age_seconds(self) -> float:
        """Seconds since last modification."""
        try:
            return time.time() - self.path.stat().st_mtime
        except Exception:
            return float("inf")

    @property
    def metadata(self) -> dict:
        """Parse YAML frontmatter if present, else empty dict."""
        text = self.content
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end > 0:
                try:
                    import yaml
                    return yaml.safe_load(text[4:end]) or {}
                except Exception:
                    pass
        return {}

    def __repr__(self) -> str:
        return f"ScratchpadEntry({self.name}, age={self.age_seconds:.0f}s)"


class ScratchpadManager:
    """Manages a scratchpad directory for a task execution context.

    Each task gets its own subdirectory: {root}/{task_id}/
    Workers write entries as files. Coordinator reads and distributes.

    Usage::

        pad = ScratchpadManager(task_id=42)

        # Worker writes findings
        pad.write("worker-1-findings", "Found 3 API endpoints that need updating...")

        # Worker writes structured data
        pad.write("worker-2-analysis", json.dumps({"files": [...], "risk": "low"}), suffix=".json")

        # Coordinator reads all entries
        for entry in pad.list_entries():
            print(f"{entry.name}: {entry.content[:100]}")

        # Build context string for downstream prompts
        context = pad.build_context(max_chars=4000)
    """

    def __init__(self, task_id: int, root: Path | str = _DEFAULT_ROOT,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._root = Path(root)
        self._task_dir = self._root / str(task_id)
        self._ttl = ttl_seconds
        self.task_id = task_id

    def write(self, name: str, content: str, suffix: str = ".md") -> Path:
        """Write a scratchpad entry.

        Args:
            name: Entry name (used as filename stem)
            content: File content
            suffix: File extension (default .md)

        Returns:
            Path to the written file
        """
        self._task_dir.mkdir(parents=True, exist_ok=True)
        path = self._task_dir / f"{name}{suffix}"
        path.write_text(content, encoding="utf-8")
        log.debug(f"Scratchpad: wrote {path.name} ({len(content)} chars) for task #{self.task_id}")
        return path

    def read(self, name: str, suffix: str = ".md") -> str:
        """Read a specific entry by name. Returns empty string if not found."""
        path = self._task_dir / f"{name}{suffix}"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def list_entries(self, *, include_expired: bool = False) -> list[ScratchpadEntry]:
        """List all scratchpad entries for this task.

        By default, excludes entries older than TTL.
        """
        if not self._task_dir.exists():
            return []

        entries = []
        for path in sorted(self._task_dir.iterdir()):
            if path.is_file():
                entry = ScratchpadEntry(path)
                if include_expired or entry.age_seconds < self._ttl:
                    entries.append(entry)
        return entries

    def build_context(self, max_chars: int = 4000) -> str:
        """Build a combined context string from all active entries.

        Used by coordinator to inject shared context into downstream prompts.
        Entries are sorted by modification time (newest last).
        Truncates to max_chars if total exceeds limit.
        """
        entries = self.list_entries()
        if not entries:
            return ""

        parts = [f"## Shared Context (scratchpad, task #{self.task_id})\n"]
        total = len(parts[0])

        for entry in entries:
            header = f"### {entry.name}\n"
            content = entry.content
            section = f"{header}{content}\n\n"

            if total + len(section) > max_chars:
                remaining = max_chars - total - len(header) - 20
                if remaining > 100:
                    section = f"{header}{content[:remaining]}...[truncated]\n\n"
                else:
                    break

            parts.append(section)
            total += len(section)

        return "".join(parts)

    def cleanup(self, *, force: bool = False) -> int:
        """Remove expired entries (or all if force=True).

        Returns number of files removed.
        """
        if not self._task_dir.exists():
            return 0

        removed = 0
        for path in list(self._task_dir.iterdir()):
            if path.is_file():
                if force or ScratchpadEntry(path).age_seconds >= self._ttl:
                    path.unlink()
                    removed += 1

        # Remove task directory if empty
        try:
            if self._task_dir.exists() and not any(self._task_dir.iterdir()):
                self._task_dir.rmdir()
        except Exception:
            pass

        if removed > 0:
            log.info(f"Scratchpad: cleaned up {removed} entries for task #{self.task_id}")

        return removed

    def exists(self) -> bool:
        """Check if this task has any scratchpad entries."""
        return self._task_dir.exists() and any(self._task_dir.iterdir())


def cleanup_all_expired(root: Path | str = _DEFAULT_ROOT, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """Cleanup expired entries across ALL task scratchpads.

    Useful as a periodic maintenance task.
    """
    root = Path(root)
    if not root.exists():
        return 0

    total_removed = 0
    for task_dir in root.iterdir():
        if task_dir.is_dir() and task_dir.name.isdigit():
            pad = ScratchpadManager(int(task_dir.name), root=root, ttl_seconds=ttl_seconds)
            total_removed += pad.cleanup()

    return total_removed
