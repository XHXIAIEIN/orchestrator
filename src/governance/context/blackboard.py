"""R74 ChatDev: BlackboardMemory — Shared append-log for sub-agent coordination.

Sub-agents share state via a time-ordered append log with role-based
read/write permissions:

    Actor:             read=True,  write=False  (reads experience)
    Reflection Writer: read=False, write=True   (writes lessons)
    Evaluator:         read=True,  write=True   (reads + appends)

Permission enforcement prevents cross-contamination between roles.
Retrieval is time-ordered (most recent first), not semantic.

Integration points:
    - executor_session.py: inject blackboard contents before agent turn
    - governor pipeline: shared state across multi-agent orchestration

Source: ChatDev 2.0 BlackboardMemory (R74 deep steal)
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RolePermission:
    """Read/write permission for a role on a blackboard."""
    role: str
    read: bool = True
    write: bool = False


@dataclass
class BlackboardEntry:
    """A single entry on the blackboard."""
    content: str
    author_role: str
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            object.__setattr__(self, "content_hash",
                hashlib.md5(self.content.encode()).hexdigest()[:12])


class BlackboardMemory:
    """Append-log shared state for sub-agent coordination.

    Usage:
        bb = BlackboardMemory("reflexion_blackboard")
        bb.grant("actor", read=True, write=False)
        bb.grant("reflection_writer", read=False, write=True)
        bb.grant("evaluator", read=True, write=True)

        # Writer adds lessons:
        bb.write("reflection_writer", "Approach X failed because Y")

        # Actor reads experience:
        entries = bb.read("actor", top_k=5)

        # Duplicate detection: same content won't be added twice
        bb.write("reflection_writer", "Approach X failed because Y")  # no-op
    """

    def __init__(
        self,
        name: str,
        max_entries: int = 200,
        dedup: bool = True,
    ):
        self.name = name
        self.max_entries = max_entries
        self.dedup = dedup
        self._entries: list[BlackboardEntry] = []
        self._permissions: dict[str, RolePermission] = {}
        self._seen_hashes: set[str] = set()
        self._write_count = 0
        self._read_count = 0

    def grant(self, role: str, read: bool = True, write: bool = False) -> None:
        """Set permissions for a role."""
        self._permissions[role] = RolePermission(role=role, read=read, write=write)
        log.debug(
            "blackboard[%s]: granted %s (read=%s, write=%s)",
            self.name, role, read, write,
        )

    def write(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Append an entry to the blackboard.

        Returns True if written, False if denied or duplicate.
        """
        perm = self._permissions.get(role)
        if perm is None or not perm.write:
            log.warning(
                "blackboard[%s]: write denied for role '%s'",
                self.name, role,
            )
            return False

        entry = BlackboardEntry(
            content=content,
            author_role=role,
            metadata=metadata or {},
        )

        # Dedup check
        if self.dedup and entry.content_hash in self._seen_hashes:
            log.debug(
                "blackboard[%s]: duplicate suppressed (hash=%s)",
                self.name, entry.content_hash,
            )
            return False

        self._entries.append(entry)
        self._seen_hashes.add(entry.content_hash)
        self._write_count += 1

        # LRU eviction
        if len(self._entries) > self.max_entries:
            evicted = self._entries[:-self.max_entries]
            self._entries = self._entries[-self.max_entries:]
            for e in evicted:
                self._seen_hashes.discard(e.content_hash)

        return True

    def read(
        self,
        role: str,
        top_k: int = 10,
        author_filter: str | None = None,
    ) -> list[BlackboardEntry]:
        """Read most recent entries from the blackboard.

        Returns newest first (reversed chronological order).
        """
        perm = self._permissions.get(role)
        if perm is None or not perm.read:
            log.warning(
                "blackboard[%s]: read denied for role '%s'",
                self.name, role,
            )
            return []

        self._read_count += 1

        entries = self._entries
        if author_filter:
            entries = [e for e in entries if e.author_role == author_filter]

        # Return most recent top_k
        if top_k >= len(entries):
            return list(reversed(entries))
        return list(reversed(entries[-top_k:]))

    def read_all(self, role: str) -> list[BlackboardEntry]:
        """Read all entries (for serialization/export)."""
        return self.read(role, top_k=len(self._entries))

    def clear(self) -> int:
        """Clear all entries. Returns count of removed entries."""
        count = len(self._entries)
        self._entries.clear()
        self._seen_hashes.clear()
        return count

    def format_for_prompt(self, role: str, top_k: int = 5) -> str:
        """Format recent entries as text for prompt injection.

        Returns empty string if role has no read access.
        """
        entries = self.read(role, top_k=top_k)
        if not entries:
            return ""

        lines = [f"## Shared Board: {self.name}\n"]
        for i, entry in enumerate(entries, 1):
            lines.append(f"{i}. [{entry.author_role}] {entry.content}")
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Return blackboard state for diagnostics."""
        return {
            "name": self.name,
            "entries": len(self._entries),
            "max_entries": self.max_entries,
            "unique_hashes": len(self._seen_hashes),
            "write_count": self._write_count,
            "read_count": self._read_count,
            "roles": {
                role: {"read": p.read, "write": p.write}
                for role, p in self._permissions.items()
            },
        }


# ── Pre-configured blackboard factory ──

def create_reflexion_blackboard() -> BlackboardMemory:
    """Create a blackboard configured for the reflexion pattern.

    Roles:
        actor: reads past lessons, does not write
        evaluator: reads drafts, writes verdicts
        reflection_writer: writes lessons learned, does not read
        synthesizer: reads everything for final output
    """
    bb = BlackboardMemory("reflexion", max_entries=50)
    bb.grant("actor", read=True, write=False)
    bb.grant("evaluator", read=True, write=True)
    bb.grant("reflection_writer", read=False, write=True)
    bb.grant("synthesizer", read=True, write=False)
    return bb
