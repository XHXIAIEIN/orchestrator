"""Dead Letter Queue — Null Object + Factory (R40-P4).

Failed nodes are stored in a DLQ for later retry or inspection.
When DLQ is disabled, NullDLQHandler silently accepts all calls
with zero overhead — no `if dlq_enabled` checks anywhere.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class DLQProtocol(Protocol):
    def add_failed_node(self, node_id: str, error_info: dict) -> bool: ...
    def get_failed_nodes(self) -> list[dict]: ...
    def retry_node(self, node_id: str) -> bool: ...
    def clear(self) -> None: ...


class NullDLQHandler:
    """No-op DLQ handler for when DLQ is disabled. Zero overhead."""
    def add_failed_node(self, node_id: str, error_info: dict) -> bool:
        return True
    def get_failed_nodes(self) -> list[dict]:
        return []
    def retry_node(self, node_id: str) -> bool:
        return False
    def clear(self) -> None:
        pass


@dataclass
class _FailedEntry:
    node_id: str
    error_info: dict
    attempt_count: int = 0
    first_failed_at: float = field(default_factory=time.time)
    last_failed_at: float = field(default_factory=time.time)


class DLQHandler:
    """In-memory Dead Letter Queue for failed execution nodes."""
    def __init__(self, max_retries: int = 3) -> None:
        self._entries: dict[str, _FailedEntry] = {}
        self._retry_counts: dict[str, int] = {}
        self._max_retries = max_retries

    def add_failed_node(self, node_id: str, error_info: dict) -> bool:
        if node_id in self._entries:
            entry = self._entries[node_id]
            entry.attempt_count += 1
            entry.last_failed_at = time.time()
            entry.error_info = error_info
        else:
            self._entries[node_id] = _FailedEntry(
                node_id=node_id, error_info=error_info, attempt_count=1,
            )
        log.info(f"DLQ: added {node_id} (attempt {self._entries[node_id].attempt_count})")
        return True

    def get_failed_nodes(self) -> list[dict]:
        return [
            {"node_id": e.node_id, "error_info": e.error_info,
             "attempt_count": e.attempt_count,
             "first_failed_at": e.first_failed_at,
             "last_failed_at": e.last_failed_at}
            for e in self._entries.values()
        ]

    def retry_node(self, node_id: str) -> bool:
        entry = self._entries.get(node_id)
        if not entry:
            return False
        retries_used = self._retry_counts.get(node_id, 0)
        if retries_used >= self._max_retries:
            log.warning(f"DLQ: {node_id} exceeded max retries ({self._max_retries})")
            return False
        self._retry_counts[node_id] = retries_used + 1
        del self._entries[node_id]
        return True

    def clear(self) -> None:
        self._entries.clear()


def create_dlq_handler(enabled: bool = True, **kwargs) -> DLQProtocol:
    """Factory — returns DLQHandler or NullDLQHandler based on config."""
    if enabled:
        return DLQHandler(**kwargs)
    return NullDLQHandler()
