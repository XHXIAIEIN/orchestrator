"""Deferred Retrievers — stolen from Parlant.

Registers lazy data loaders that only execute when their data is
actually needed. Avoids wasting tokens/latency loading context
during routing that the executor might never use.

Usage:
    ctx = DeferredContext()
    ctx.register("git_log", lambda: get_recent_commits(limit=20))
    ctx.register("test_results", lambda: run_tests_summary())

    # Later, in executor:
    log = ctx.get("git_log")      # NOW it runs get_recent_commits()
    # test_results never loaded if not needed → saved tokens + time
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

log = logging.getLogger(__name__)


@dataclass
class RetrievalRecord:
    """Tracks a deferred retrieval's lifecycle."""
    key: str
    loader: Callable
    loaded: bool = False
    value: Any = None
    load_time_ms: int = 0
    error: Optional[str] = None
    accessed_count: int = 0


class DeferredContext:
    """Lazy-loading context container. Data only loads when accessed."""

    def __init__(self):
        self._retrievers: dict[str, RetrievalRecord] = {}
        self._stats = {"registered": 0, "loaded": 0, "skipped": 0, "errors": 0}

    def register(self, key: str, loader: Callable, override: bool = False):
        """Register a deferred retriever.

        Args:
            key: Unique key for this data.
            loader: Callable that returns the data when invoked.
            override: If True, replace existing retriever for this key.
        """
        if key in self._retrievers and not override:
            log.debug(f"deferred: key '{key}' already registered, skipping")
            return
        self._retrievers[key] = RetrievalRecord(key=key, loader=loader)
        self._stats["registered"] += 1

    def get(self, key: str, default: Any = None) -> Any:
        """Get data, loading it lazily on first access.

        Returns default if key not registered or loader fails.
        """
        record = self._retrievers.get(key)
        if record is None:
            return default

        record.accessed_count += 1

        if record.loaded:
            return record.value

        # Load now
        t0 = time.time()
        try:
            record.value = record.loader()
            record.loaded = True
            record.load_time_ms = int((time.time() - t0) * 1000)
            self._stats["loaded"] += 1
            log.debug(f"deferred: loaded '{key}' ({record.load_time_ms}ms)")
            return record.value
        except Exception as e:
            record.error = str(e)
            record.load_time_ms = int((time.time() - t0) * 1000)
            self._stats["errors"] += 1
            log.warning(f"deferred: failed to load '{key}': {e}")
            return default

    def has(self, key: str) -> bool:
        """Check if a key is registered (without loading it)."""
        return key in self._retrievers

    def is_loaded(self, key: str) -> bool:
        """Check if a key has been loaded."""
        record = self._retrievers.get(key)
        return record.loaded if record else False

    def preload(self, *keys: str):
        """Force-load specific keys now."""
        for key in keys:
            self.get(key)

    def materialize_all(self) -> dict[str, Any]:
        """Load all registered retrievers and return as dict."""
        result = {}
        for key in self._retrievers:
            result[key] = self.get(key)
        return result

    def get_loaded_keys(self) -> list[str]:
        """Return keys that have been loaded."""
        return [k for k, r in self._retrievers.items() if r.loaded]

    def get_unloaded_keys(self) -> list[str]:
        """Return keys that were registered but never loaded."""
        return [k for k, r in self._retrievers.items() if not r.loaded]

    def get_stats(self) -> dict:
        unloaded = len(self.get_unloaded_keys())
        self._stats["skipped"] = unloaded
        return {
            **self._stats,
            "total_keys": len(self._retrievers),
            "tokens_saved_estimate": unloaded * 500,  # rough estimate
        }
