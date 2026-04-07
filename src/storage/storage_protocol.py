"""StorageProtocol — ABC for storage backends (R43 — LangGraph steal).

Defines the contract that any storage backend must satisfy.
Includes both generic key-value operations and structured checkpoint methods.
Use tests/test_storage_conformance.py to verify implementations.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from src.governance.checkpoint_recovery import StructuredCheckpoint


@runtime_checkable
class StorageProtocol(Protocol):
    """Abstract storage backend contract.

    Any class implementing this protocol can be used as a storage backend
    for the orchestrator. The conformance test suite validates all methods.
    """

    def put(self, key: str, value: Any) -> None:
        """Store a value by key. Overwrites if exists."""
        ...

    def get(self, key: str) -> Any:
        """Retrieve a value by key. Raises KeyError if not found."""
        ...

    def list(self, prefix: str = "") -> list[str]:
        """List all keys matching the given prefix."""
        ...

    def delete(self, key: str) -> None:
        """Delete a key. No-op if not found."""
        ...

    def put_checkpoint(self, cp: StructuredCheckpoint) -> None:
        """Store a structured checkpoint."""
        ...

    def get_checkpoint(self, task_id: str) -> Optional[StructuredCheckpoint]:
        """Get the latest checkpoint for a task. Returns None if not found."""
        ...

    def list_checkpoints(self, task_id: str | None = None) -> list[StructuredCheckpoint]:
        """List checkpoints, optionally filtered by task_id. Ordered by timestamp desc."""
        ...

    def delete_checkpoints(self, task_id: str) -> None:
        """Delete all checkpoints for a given task."""
        ...
