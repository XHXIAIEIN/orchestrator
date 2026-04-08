"""Shared Job Control Plane — file-system-based distributed task coordination.

Stolen from DocMason (R45b-P1). Provides idempotent task creation with
content-hash deduplication, stale owner recovery, and state machine flow.

When multiple agents request the same task simultaneously, only one executes.
Others become waiters and poll for completion.

Usage:
    from src.governance.shared_jobs import ensure_shared_job, update_job_state, JobState

    result = ensure_shared_job(
        data_dir, job_key="daily-report", input_signature="sha256:abc...",
        owner="agent-42", spec={"type": "report", "date": "2026-04-08"},
    )
    if result["caller_role"] == "owner":
        # We're responsible for executing this job
        do_work()
        update_job_state(data_dir, result["manifest"]["job_id"], JobState.COMPLETED)
    else:
        # Someone else is already on it — wait or check back later
        pass
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.core.fs_lock import workspace_lease

log = logging.getLogger(__name__)

# ── Constants ──

_JOBS_DIR = "shared_jobs"
_INDEX_FILE = "index.json"
_STALE_SECONDS = 300  # 5 minutes without heartbeat → stale


class JobState(str, Enum):
    """Job lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting-confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class CallerRole(str, Enum):
    """What the caller should do after ensure_shared_job."""
    OWNER = "owner"              # You execute this job
    WAITER = "waiter"            # Someone else is executing; poll for result
    CONFIRMATION = "confirmation"  # Job awaits user confirmation


@dataclass
class JobManifest:
    """Persistent job record."""
    job_id: str
    job_key: str
    input_signature: str
    owner: str
    state: str = JobState.PENDING.value
    created_at: str = ""
    updated_at: str = ""
    attempt_count: int = 1
    owner_pid: int = 0
    spec: dict = field(default_factory=dict)
    journal: list[dict] = field(default_factory=list)
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> JobManifest:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Path helpers ──

def _jobs_dir(data_dir: Path) -> Path:
    return data_dir / _JOBS_DIR


def _job_file(data_dir: Path, job_id: str) -> Path:
    return _jobs_dir(data_dir) / f"{job_id}.json"


def _index_path(data_dir: Path) -> Path:
    return _jobs_dir(data_dir) / _INDEX_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Index management ──

def _load_index(data_dir: Path) -> dict:
    """Load the active-jobs index. Structure: {"active_by_key": {"key": "job_id"}}."""
    path = _index_path(data_dir)
    if not path.exists():
        return {"active_by_key": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_by_key": {}}


def _save_index(data_dir: Path, index: dict) -> None:
    path = _index_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_job(data_dir: Path, job_id: str) -> JobManifest | None:
    path = _job_file(data_dir, job_id)
    if not path.exists():
        return None
    try:
        return JobManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def _save_job(data_dir: Path, manifest: JobManifest) -> None:
    path = _job_file(data_dir, manifest.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Owner liveness detection ──

def _owner_process_active(pid: int) -> bool:
    """Check if the owner process is still alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # Signal 0: existence check, no actual signal
        return True
    except ProcessLookupError:
        return False  # Process doesn't exist
    except PermissionError:
        return True  # Process exists but we can't signal it
    except OSError:
        return False


def _job_is_stale(manifest: JobManifest) -> bool:
    """Check if a job's owner has died or gone stale."""
    # Completed/failed jobs aren't stale — they're done
    if manifest.state in (JobState.COMPLETED.value, JobState.FAILED.value):
        return False

    # Check PID liveness
    if manifest.owner_pid > 0 and not _owner_process_active(manifest.owner_pid):
        return True

    # Check time-based staleness
    try:
        updated = datetime.fromisoformat(manifest.updated_at)
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        return age > _STALE_SECONDS
    except (ValueError, TypeError):
        return True


def _add_journal(manifest: JobManifest, event: str, detail: str = "") -> None:
    """Append an event to the job journal."""
    manifest.journal.append({
        "event": event,
        "detail": detail,
        "timestamp": _utc_now(),
        "pid": os.getpid(),
    })
    manifest.updated_at = _utc_now()


# ── Public API ──

def compute_signature(*parts: str) -> str:
    """Compute a content-hash signature from input parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return f"sha256:{h.hexdigest()[:16]}"


def ensure_shared_job(
    data_dir: Path,
    *,
    job_key: str,
    input_signature: str,
    owner: str,
    spec: dict | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Create or join a shared job — idempotent.

    If a job with the same key and signature already exists and is active,
    returns it with caller_role=waiter. If stale, takes ownership.
    Otherwise creates a new job.

    Returns:
        {"manifest": JobManifest dict, "created": bool, "caller_role": CallerRole}
    """
    with workspace_lease(data_dir, f"shared-job:{job_key}", timeout_seconds=timeout_seconds):
        index = _load_index(data_dir)
        active_job_id = index["active_by_key"].get(job_key)

        if active_job_id:
            manifest = _load_job(data_dir, active_job_id)
            if manifest and manifest.input_signature == input_signature:
                # Idempotent hit — same job with same inputs
                if _job_is_stale(manifest):
                    # Take over from dead owner
                    log.warning(f"Taking over stale job {job_key} from {manifest.owner}")
                    manifest.owner = owner
                    manifest.owner_pid = os.getpid()
                    manifest.attempt_count += 1
                    manifest.state = JobState.RUNNING.value
                    _add_journal(manifest, "takeover", f"stale owner replaced by {owner}")
                    _save_job(data_dir, manifest)
                    return {"manifest": manifest.to_dict(), "created": False, "caller_role": CallerRole.OWNER.value}

                # Job alive — determine caller role
                if manifest.state == JobState.AWAITING_CONFIRMATION.value:
                    role = CallerRole.CONFIRMATION.value
                elif manifest.state in (JobState.COMPLETED.value, JobState.FAILED.value):
                    role = CallerRole.OWNER.value  # Terminal state; caller can start fresh
                else:
                    role = CallerRole.WAITER.value

                return {"manifest": manifest.to_dict(), "created": False, "caller_role": role}

            elif manifest and manifest.state not in (JobState.COMPLETED.value, JobState.FAILED.value):
                # Different signature but old job still running — let it finish
                return {"manifest": manifest.to_dict(), "created": False, "caller_role": CallerRole.WAITER.value}

        # Create new job
        now = _utc_now()
        manifest = JobManifest(
            job_id=uuid.uuid4().hex[:12],
            job_key=job_key,
            input_signature=input_signature,
            owner=owner,
            state=JobState.RUNNING.value,
            created_at=now,
            updated_at=now,
            owner_pid=os.getpid(),
            spec=spec or {},
        )
        _add_journal(manifest, "created", f"owner={owner}")
        _save_job(data_dir, manifest)

        # Update index
        index["active_by_key"][job_key] = manifest.job_id
        _save_index(data_dir, index)

        return {"manifest": manifest.to_dict(), "created": True, "caller_role": CallerRole.OWNER.value}


def update_job_state(
    data_dir: Path,
    job_id: str,
    new_state: JobState,
    *,
    result: dict | None = None,
    detail: str = "",
) -> JobManifest | None:
    """Transition a job to a new state."""
    manifest = _load_job(data_dir, job_id)
    if not manifest:
        log.error(f"Job {job_id} not found")
        return None

    old_state = manifest.state
    manifest.state = new_state.value
    if result is not None:
        manifest.result = result
    _add_journal(manifest, f"state:{old_state}→{new_state.value}", detail)
    _save_job(data_dir, manifest)

    # If terminal state, clean up index
    if new_state in (JobState.COMPLETED, JobState.FAILED):
        with workspace_lease(data_dir, f"shared-job:{manifest.job_key}", timeout_seconds=5.0):
            index = _load_index(data_dir)
            if index["active_by_key"].get(manifest.job_key) == job_id:
                del index["active_by_key"][manifest.job_key]
                _save_index(data_dir, index)

    return manifest


def heartbeat(data_dir: Path, job_id: str) -> bool:
    """Update the job's timestamp to prevent stale detection."""
    manifest = _load_job(data_dir, job_id)
    if not manifest:
        return False
    manifest.updated_at = _utc_now()
    _save_job(data_dir, manifest)
    return True


def get_job(data_dir: Path, job_id: str) -> dict | None:
    """Read a job manifest."""
    manifest = _load_job(data_dir, job_id)
    return manifest.to_dict() if manifest else None


def list_active_jobs(data_dir: Path) -> list[dict]:
    """List all active (non-terminal) jobs."""
    index = _load_index(data_dir)
    result = []
    for key, job_id in index["active_by_key"].items():
        manifest = _load_job(data_dir, job_id)
        if manifest:
            result.append(manifest.to_dict())
    return result


def cleanup_stale_jobs(data_dir: Path) -> list[str]:
    """Find and mark stale jobs as failed. Returns list of cleaned job IDs."""
    cleaned = []
    index = _load_index(data_dir)

    for key, job_id in list(index["active_by_key"].items()):
        manifest = _load_job(data_dir, job_id)
        if manifest and _job_is_stale(manifest):
            update_job_state(data_dir, job_id, JobState.FAILED, detail="stale cleanup")
            cleaned.append(job_id)

    return cleaned
