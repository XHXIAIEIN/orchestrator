"""Filesystem Mutex Lock — mkdir atomicity + stale detection.

Stolen from DocMason (R45b-P2). Cross-platform file-system lock using
mkdir(exist_ok=False) as the atomic primitive. Works on both POSIX and
Windows without fcntl.

Usage:
    from src.core.fs_lock import workspace_lease, LeaseConflictError

    with workspace_lease(lock_dir, "my-resource") as lease:
        # exclusive access guaranteed
        do_work()
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

log = logging.getLogger(__name__)

# Grace period: after mkdir succeeds but before lease.json is written,
# another process might see the dir as "stale". This grace prevents
# false-positive stale detection on freshly created locks.
_FRESH_LEASE_WRITE_GRACE_SECONDS = 1.0


class LeaseConflictError(Exception):
    """Raised when a lock cannot be acquired within the timeout."""

    def __init__(self, resource: str, holder: dict | None = None):
        self.resource = resource
        self.holder = holder
        msg = f"Could not acquire lease for '{resource}'"
        if holder:
            msg += f" (held by {holder.get('owner', '?')} since {holder.get('created_at', '?')})"
        super().__init__(msg)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_dir(base: Path, resource: str) -> Path:
    """Compute lock directory path from resource name."""
    # Sanitize resource name for filesystem safety
    safe = resource.replace("/", "__").replace(":", "_").replace(" ", "_")
    return base / ".locks" / safe


def _read_lease(target: Path) -> dict | None:
    """Read lease.json from lock directory, returns None if missing/corrupt."""
    lease_file = target / "lease.json"
    if not lease_file.exists():
        return None
    try:
        return json.loads(lease_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _stale_lease(target: Path, stale_after_seconds: float) -> bool:
    """Check if an existing lock directory is stale.

    Two-pass detection:
    1. Read lease.json → check created_at timestamp
    2. If lease.json missing → check directory mtime (with grace period)
    """
    lease = _read_lease(target)
    if lease and "created_at" in lease:
        try:
            created = datetime.fromisoformat(lease["created_at"])
            age = (datetime.now(timezone.utc) - created).total_seconds()
            return age > stale_after_seconds
        except (ValueError, TypeError):
            pass

    # No lease.json or unparseable → fall back to directory mtime
    try:
        mtime = target.stat().st_mtime
        age = time.time() - mtime
        # Grace period: directory just created, lease.json not yet written
        if age < _FRESH_LEASE_WRITE_GRACE_SECONDS:
            return False
        return age > stale_after_seconds
    except OSError:
        return True  # Can't stat → treat as stale


@contextmanager
def workspace_lease(
    base: Path,
    resource: str,
    *,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.05,
    stale_after_seconds: float = 600.0,
    metadata: dict[str, Any] | None = None,
) -> Generator[dict, None, None]:
    """Acquire an exclusive filesystem lease on a named resource.

    Args:
        base: Base directory for lock storage (e.g., project data dir).
        resource: Logical resource name (e.g., "shared-job:daily-report").
        timeout_seconds: Max wait time before raising LeaseConflictError.
        poll_interval_seconds: Sleep between acquisition attempts.
        stale_after_seconds: Lease older than this is considered abandoned.
        metadata: Extra data to store in lease.json.

    Yields:
        Lease payload dict with owner, resource, created_at, metadata.

    Raises:
        LeaseConflictError: If lock cannot be acquired within timeout.
    """
    owner_id = str(uuid.uuid4())
    payload = {
        "resource": resource,
        "owner": owner_id,
        "created_at": _utc_now(),
        "pid": _get_pid(),
        **(metadata or {}),
    }

    target = _lease_dir(base, resource)
    target.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout_seconds
    holder_info = None

    while True:
        try:
            target.mkdir(parents=False, exist_ok=False)  # OS-level atomic
        except FileExistsError:
            # Directory exists — check if it's actually a directory
            if target.exists() and not target.is_dir():
                try:
                    target.unlink()  # Anomaly: file instead of dir
                except OSError:
                    pass
                continue

            # Check for stale lock
            if _stale_lease(target, stale_after_seconds):
                log.warning(f"Reclaiming stale lease for '{resource}'")
                try:
                    shutil.rmtree(target, ignore_errors=True)
                except OSError:
                    pass
                continue

            # Lock is held by someone else
            holder_info = _read_lease(target)

            if time.monotonic() >= deadline:
                raise LeaseConflictError(resource, holder_info)

            time.sleep(poll_interval_seconds)
            continue

        # mkdir succeeded — write lease metadata
        try:
            (target / "lease.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            # Failed to write metadata — release the lock
            shutil.rmtree(target, ignore_errors=True)
            raise LeaseConflictError(resource) from e

        break

    try:
        yield payload
    finally:
        # Only release if we still own it
        lease_info = _read_lease(target)
        if lease_info and lease_info.get("owner") == owner_id:
            shutil.rmtree(target, ignore_errors=True)
        else:
            log.warning(
                f"Lease for '{resource}' owned by someone else at release time "
                f"(expected {owner_id}, got {lease_info.get('owner') if lease_info else 'None'})"
            )


def _get_pid() -> int:
    """Get current process ID."""
    import os
    return os.getpid()


def is_lease_held(base: Path, resource: str) -> bool:
    """Check if a resource currently has an active (non-stale) lease."""
    target = _lease_dir(base, resource)
    if not target.exists():
        return False
    return not _stale_lease(target, stale_after_seconds=600.0)


def force_release(base: Path, resource: str) -> bool:
    """Force-release a lease. Use with caution — only for recovery."""
    target = _lease_dir(base, resource)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        log.warning(f"Force-released lease for '{resource}'")
        return True
    return False
