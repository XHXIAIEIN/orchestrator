"""R48 (Hermes v0.8): No-Evict-on-Fail Anti-Loop.

Cached agents that fail stay cached — quick error return instead of
expensive re-creation. Only a SUCCESSFUL fallback evicts a failed entry.
Prevents: fail → evict → recreate → fail → evict loops.
"""
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class AgentCacheEntry:
    """A cached agent entry with failure state tracking."""
    agent_id: str
    config: dict
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    run_failed: bool = False
    failure_reason: str = ""
    use_count: int = 0

    def touch(self):
        self.last_used = time.monotonic()
        self.use_count += 1


class AgentCache:
    """Thread-safe agent registry with no-evict-on-fail protection.

    Eviction policy:
    - LRU eviction applies ONLY to healthy entries (run_failed=False)
    - Failed entries are shielded from LRU — they stay to return fast errors
    - Manual evict() refuses to remove failed entries (use force_evict() to override)
    - evict_on_successful_fallback() is the only blessed path for removing a failed entry
    """

    def __init__(self, max_size: int = 128):
        self._cache: dict[str, AgentCacheEntry] = {}
        self._lock = Lock()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    # ── Core access ──

    def get_or_create(self, agent_id: str, factory: Callable[[], Any]) -> tuple[Any, AgentCacheEntry]:
        """Return cached agent or create a new one via factory.

        If the cached entry is in a failed state, returns (None, entry) so
        the caller can handle the failure without triggering re-creation.

        Returns:
            (agent_instance_or_None, cache_entry)
        """
        with self._lock:
            if agent_id in self._cache:
                entry = self._cache[agent_id]
                entry.touch()
                self._hits += 1
                if entry.run_failed:
                    log.debug(
                        "agent_cache: hit failed entry %s — returning error fast "
                        "(reason: %s)", agent_id, entry.failure_reason
                    )
                    return None, entry
                log.debug("agent_cache: hit %s (use_count=%d)", agent_id, entry.use_count)
                return entry.config.get("_instance"), entry

            self._misses += 1
            # Need to create — enforce max_size via LRU on healthy entries only
            self._evict_lru_if_needed()

            instance = factory()
            entry = AgentCacheEntry(
                agent_id=agent_id,
                config={"_instance": instance},
            )
            entry.touch()
            self._cache[agent_id] = entry
            log.debug("agent_cache: created %s (cache_size=%d)", agent_id, len(self._cache))
            return instance, entry

    # ── State management ──

    def mark_failed(self, agent_id: str, reason: str = ""):
        """Mark an agent as failed. It stays in cache to return fast errors."""
        with self._lock:
            if agent_id in self._cache:
                self._cache[agent_id].run_failed = True
                self._cache[agent_id].failure_reason = reason
                log.warning("agent_cache: marked %s as failed: %s", agent_id, reason)
            else:
                log.debug("agent_cache: mark_failed called on unknown agent %s", agent_id)

    def mark_success(self, agent_id: str):
        """Clear failed state on a recovered agent."""
        with self._lock:
            if agent_id in self._cache:
                self._cache[agent_id].run_failed = False
                self._cache[agent_id].failure_reason = ""
                log.debug("agent_cache: cleared failure state for %s", agent_id)

    # ── Eviction ──

    def evict(self, agent_id: str) -> bool:
        """Evict an agent, but REFUSE to evict failed entries.

        Returns True if evicted, False if blocked (entry is failed).
        Use force_evict() to bypass this safety check.
        """
        with self._lock:
            entry = self._cache.get(agent_id)
            if entry is None:
                return False
            if entry.run_failed:
                log.warning(
                    "agent_cache: evict(%s) blocked — entry is in failed state. "
                    "Use force_evict() to override or evict_on_successful_fallback().",
                    agent_id,
                )
                return False
            del self._cache[agent_id]
            log.debug("agent_cache: evicted %s", agent_id)
            return True

    def force_evict(self, agent_id: str) -> bool:
        """Evict regardless of failed state. For manual cleanup only.

        Returns True if the entry existed and was removed.
        """
        with self._lock:
            if agent_id in self._cache:
                was_failed = self._cache[agent_id].run_failed
                del self._cache[agent_id]
                log.info(
                    "agent_cache: force_evicted %s (was_failed=%s)", agent_id, was_failed
                )
                return True
            return False

    def evict_on_successful_fallback(self, original_id: str, fallback_id: str) -> bool:
        """The blessed path for removing a failed entry after fallback succeeded.

        Evicts original_id only if fallback_id is present and healthy in cache.
        This closes the anti-loop: we know the replacement works before we
        remove the old (failed) guard entry.

        Returns True if original was evicted.
        """
        with self._lock:
            fallback = self._cache.get(fallback_id)
            if fallback is None or fallback.run_failed:
                log.warning(
                    "agent_cache: evict_on_successful_fallback — fallback %s is not "
                    "healthy, keeping original %s in cache.",
                    fallback_id, original_id,
                )
                return False

            original = self._cache.get(original_id)
            if original is None:
                return False

            del self._cache[original_id]
            log.info(
                "agent_cache: evicted failed entry %s after successful fallback to %s",
                original_id, fallback_id,
            )
            return True

    # ── Stats ──

    def get_stats(self) -> dict:
        """Return cache health snapshot."""
        with self._lock:
            total = len(self._cache)
            failed = sum(1 for e in self._cache.values() if e.run_failed)
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            return {
                "cache_size": total,
                "failed_count": failed,
                "healthy_count": total - failed,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
            }

    # ── Internal LRU helper ──

    def _evict_lru_if_needed(self):
        """Evict the least-recently-used HEALTHY entry if over max_size.

        Must be called under self._lock. Failed entries are never candidates.
        """
        if len(self._cache) < self._max_size:
            return

        healthy = [(k, e) for k, e in self._cache.items() if not e.run_failed]
        if not healthy:
            log.warning(
                "agent_cache: at max_size=%d but all entries are failed — "
                "cannot evict. Cache will exceed limit.", self._max_size
            )
            return

        lru_id, _ = min(healthy, key=lambda kv: kv[1].last_used)
        del self._cache[lru_id]
        log.debug("agent_cache: LRU evicted %s to make room", lru_id)


# ── Singleton ──

_instance: Optional[AgentCache] = None
_instance_lock = Lock()


def get_agent_cache(max_size: int = 128) -> AgentCache:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AgentCache(max_size=max_size)
    return _instance


def reset_agent_cache():
    """Reset singleton (for testing only)."""
    global _instance
    with _instance_lock:
        _instance = None
