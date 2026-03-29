"""Unified Concurrency Pool — stolen from Firecrawl.

Shared concurrency limiter across all subsystems (agents, collectors, etc.).
Slots are registered on acquire and released on completion, with TTL
auto-cleanup for abandoned slots.

Usage:
    pool = get_concurrency_pool()
    slot = pool.acquire("collector:git", ttl=60)
    if slot:
        try:
            do_work()
        finally:
            pool.release(slot)
    else:
        # Pool full, back off
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 8
DEFAULT_TTL = 300  # 5 minutes


@dataclass
class Slot:
    """A concurrency slot."""
    id: str
    owner: str           # who acquired it (e.g. "collector:git", "agent:task_42")
    acquired_at: float = field(default_factory=time.time)
    ttl: int = DEFAULT_TTL
    metadata: dict = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return (time.time() - self.acquired_at) > self.ttl


class ConcurrencyPool:
    """Thread-safe concurrency limiter with TTL auto-cleanup."""

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT):
        self.max_concurrent = max_concurrent
        self._slots: dict[str, Slot] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._stats = {"acquired": 0, "released": 0, "expired": 0, "rejected": 0}

    def acquire(self, owner: str, ttl: int = DEFAULT_TTL,
                metadata: dict = None) -> Optional[Slot]:
        """Try to acquire a slot. Returns Slot on success, None if pool full."""
        with self._lock:
            # Clean expired slots first
            self._cleanup_expired()

            if len(self._slots) >= self.max_concurrent:
                self._stats["rejected"] += 1
                log.warning(
                    f"concurrency_pool: rejected {owner} "
                    f"({len(self._slots)}/{self.max_concurrent} slots used)"
                )
                return None

            self._counter += 1
            slot_id = f"slot_{self._counter}_{owner}"
            slot = Slot(
                id=slot_id,
                owner=owner,
                ttl=ttl,
                metadata=metadata or {},
            )
            self._slots[slot_id] = slot
            self._stats["acquired"] += 1

            log.debug(f"concurrency_pool: acquired {slot_id} ({len(self._slots)}/{self.max_concurrent})")
            return slot

    def release(self, slot: Slot) -> bool:
        """Release a slot. Returns True if found and released."""
        with self._lock:
            if slot.id in self._slots:
                del self._slots[slot.id]
                self._stats["released"] += 1
                log.debug(f"concurrency_pool: released {slot.id} ({len(self._slots)}/{self.max_concurrent})")
                return True
            return False

    def release_by_owner(self, owner: str) -> int:
        """Release all slots owned by a specific owner. Returns count released."""
        with self._lock:
            to_remove = [sid for sid, s in self._slots.items() if s.owner == owner]
            for sid in to_remove:
                del self._slots[sid]
                self._stats["released"] += 1
            return len(to_remove)

    def _cleanup_expired(self):
        """Remove expired slots. Must be called under lock."""
        expired = [sid for sid, s in self._slots.items() if s.expired]
        for sid in expired:
            owner = self._slots[sid].owner
            del self._slots[sid]
            self._stats["expired"] += 1
            log.info(f"concurrency_pool: expired slot {sid} (owner={owner})")

    @property
    def active_count(self) -> int:
        with self._lock:
            self._cleanup_expired()
            return len(self._slots)

    @property
    def available(self) -> int:
        return max(0, self.max_concurrent - self.active_count)

    def list_active(self) -> list[dict]:
        """List all active slots."""
        with self._lock:
            self._cleanup_expired()
            return [
                {"id": s.id, "owner": s.owner,
                 "age_s": round(time.time() - s.acquired_at, 1),
                 "ttl": s.ttl}
                for s in self._slots.values()
            ]

    def get_stats(self) -> dict:
        with self._lock:
            self._cleanup_expired()
            return {
                "max_concurrent": self.max_concurrent,
                "active": len(self._slots),
                "available": self.max_concurrent - len(self._slots),
                **self._stats,
            }


# Singleton
_pool: Optional[ConcurrencyPool] = None


def get_concurrency_pool(max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> ConcurrencyPool:
    global _pool
    if _pool is None:
        _pool = ConcurrencyPool(max_concurrent)
    return _pool
