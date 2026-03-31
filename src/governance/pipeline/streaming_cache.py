"""Streaming Cache — layer-keyed state cache for pipeline stages.

Stolen from: microsoft/VibeVoice (Round 17)
Pattern: VibeVoiceTokenizerStreamingCache

VibeVoice caches intermediate states keyed by (layer_id, sample_idx),
supporting per-sample soft-reset without clearing other samples.

For Orchestrator: cache keyed by (pipeline_stage, agent_id) enables:
  - Soft-reset one agent's context without affecting others
  - Clear a specific pipeline stage across all agents
  - Fine-grained cache management for context parity
  - Streaming intermediate results during long pipelines

Usage:
    cache = StreamingCache()
    cache.set("scrutiny", "agent-42", {"verdict": "APPROVE", "note": "..."})
    cache.set("execute",  "agent-42", {"turn": 5, "output": "..."})

    # Soft reset scrutiny for agent-42 (structure preserved, values zeroed)
    cache.set_to_zero(stage="scrutiny", agent_ids=["agent-42"])

    # Clear all execute stage data
    cache.clear(stage="execute")

    # Get streaming iterator for an agent
    for stage, data in cache.iter_agent("agent-42"):
        ...
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Iterator

log = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    stage: str
    agent_id: str
    data: Any
    version: int = 0          # Incremented on each update
    is_zeroed: bool = False   # True after set_to_zero (soft reset)


class StreamingCache:
    """Thread-safe layer-keyed cache for pipeline state.

    Keys are (stage, agent_id) tuples. Supports:
      - set/get: standard cache operations
      - set_to_zero: soft-reset entries (data=None, is_zeroed=True)
      - clear: remove entries by stage, agent_id, or both
      - iter_agent: iterate all stages for a given agent
      - iter_stage: iterate all agents for a given stage
    """

    def __init__(self):
        self._cache: dict[tuple[str, str], CacheEntry] = {}
        self._lock = threading.Lock()

    def set(self, stage: str, agent_id: str, data: Any) -> None:
        """Set or update a cache entry."""
        key = (stage, agent_id)
        with self._lock:
            existing = self._cache.get(key)
            version = (existing.version + 1) if existing else 0
            self._cache[key] = CacheEntry(
                stage=stage,
                agent_id=agent_id,
                data=data,
                version=version,
                is_zeroed=False,
            )

    def get(self, stage: str, agent_id: str) -> Any | None:
        """Get cached data. Returns None if not found or zeroed."""
        key = (stage, agent_id)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_zeroed:
                return None
            return entry.data

    def get_entry(self, stage: str, agent_id: str) -> CacheEntry | None:
        """Get the full CacheEntry (including metadata)."""
        with self._lock:
            return self._cache.get((stage, agent_id))

    def set_to_zero(
        self,
        stage: str | None = None,
        agent_ids: list[str] | None = None,
    ) -> int:
        """Soft-reset entries: mark as zeroed without removing structure.

        Like VibeVoice's set_to_zero: the cache entry still exists
        (preserving version counter), but data is cleared and is_zeroed=True.
        This is cheaper than delete+recreate and preserves lineage.

        Args:
            stage: If set, only zero entries in this stage.
            agent_ids: If set, only zero entries for these agents.

        Returns:
            Number of entries zeroed.
        """
        count = 0
        with self._lock:
            for key, entry in self._cache.items():
                if stage and entry.stage != stage:
                    continue
                if agent_ids and entry.agent_id not in agent_ids:
                    continue
                entry.data = None
                entry.is_zeroed = True
                entry.version += 1
                count += 1
        if count:
            log.debug(f"StreamingCache: zeroed {count} entries (stage={stage}, agents={agent_ids})")
        return count

    def clear(
        self,
        stage: str | None = None,
        agent_ids: list[str] | None = None,
    ) -> int:
        """Hard-clear entries (remove from cache entirely).

        Args:
            stage: If set, only clear entries in this stage.
            agent_ids: If set, only clear entries for these agents.
            If both None, clears everything.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            if stage is None and agent_ids is None:
                count = len(self._cache)
                self._cache.clear()
                return count

            to_remove = []
            for key, entry in self._cache.items():
                if stage and entry.stage != stage:
                    continue
                if agent_ids and entry.agent_id not in agent_ids:
                    continue
                to_remove.append(key)

            for key in to_remove:
                del self._cache[key]

            if to_remove:
                log.debug(f"StreamingCache: cleared {len(to_remove)} entries")
            return len(to_remove)

    def iter_agent(self, agent_id: str) -> Iterator[tuple[str, Any]]:
        """Iterate all stages for a given agent. Yields (stage, data)."""
        with self._lock:
            entries = [
                (e.stage, e.data)
                for e in self._cache.values()
                if e.agent_id == agent_id and not e.is_zeroed
            ]
        yield from entries

    def iter_stage(self, stage: str) -> Iterator[tuple[str, Any]]:
        """Iterate all agents for a given stage. Yields (agent_id, data)."""
        with self._lock:
            entries = [
                (e.agent_id, e.data)
                for e in self._cache.values()
                if e.stage == stage and not e.is_zeroed
            ]
        yield from entries

    def has(self, stage: str, agent_id: str) -> bool:
        """Check if a non-zeroed entry exists."""
        with self._lock:
            entry = self._cache.get((stage, agent_id))
            return entry is not None and not entry.is_zeroed

    @property
    def size(self) -> int:
        """Number of active (non-zeroed) entries."""
        with self._lock:
            return sum(1 for e in self._cache.values() if not e.is_zeroed)

    def stats(self) -> dict:
        """Cache statistics for monitoring."""
        with self._lock:
            total = len(self._cache)
            active = sum(1 for e in self._cache.values() if not e.is_zeroed)
            zeroed = total - active
            stages = set(e.stage for e in self._cache.values())
            agents = set(e.agent_id for e in self._cache.values())
        return {
            "total_entries": total,
            "active": active,
            "zeroed": zeroed,
            "stages": sorted(stages),
            "agents": sorted(agents),
        }
