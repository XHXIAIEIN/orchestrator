"""
Checkpoint Recovery — detect partial progress and resume interrupted agents.

Source: yoyo-evolve Checkpoint-Restart (Round 30)

When a sub-agent times out or errors:
1. Check git log for commits made during this task
2. Check git diff for uncommitted changes
3. Build a checkpoint context document
4. Return it for the next agent to resume from

This is NOT automatic re-execution. It produces a checkpoint document
that the dispatcher can feed to a fresh agent.
"""
from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

log = logging.getLogger(__name__)

# ── R43: Durability modes (LangGraph steal) ──────────────────

Durability = Literal["sync", "async", "exit"]


@dataclass
class StructuredCheckpoint:
    """Structured checkpoint with channel state and durability support (R43).

    Unlike the git-based Checkpoint, this captures in-memory channel state
    for fast resume without re-scanning git history.
    """
    task_id: str
    channel_values: dict[str, Any]       # serialized channel state
    channel_versions: dict[str, int] = field(default_factory=dict)  # version per channel
    pending_writes: list[tuple[str, Any]] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# Buffered checkpoints for exit-mode durability
_exit_buffer: dict[str, list[StructuredCheckpoint]] = {}
_async_pool: ThreadPoolExecutor | None = None


def _get_async_pool() -> ThreadPoolExecutor:
    """Lazy-init shared pool for async checkpoint writes."""
    global _async_pool
    if _async_pool is None:
        _async_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ckpt")
    return _async_pool


def save_checkpoint(
    cp: StructuredCheckpoint,
    durability: Durability = "sync",
    db=None,
) -> None:
    """Save a structured checkpoint with configurable durability.

    Args:
        cp: The checkpoint to save
        durability:
          - "sync": write to DB immediately, block until done
          - "async": submit to thread pool, return immediately
          - "exit": buffer in memory, flush on task completion or error
        db: EventsDB instance (required for sync/async modes)
    """
    if durability == "sync":
        if db:
            _write_checkpoint_to_db(cp, db)
        else:
            log.warning("save_checkpoint(sync): no db provided, checkpoint lost")

    elif durability == "async":
        pool = _get_async_pool()
        if db:
            pool.submit(_write_checkpoint_to_db, cp, db)
        else:
            log.warning("save_checkpoint(async): no db provided")

    elif durability == "exit":
        _exit_buffer.setdefault(cp.task_id, []).append(cp)

    else:
        log.warning(f"save_checkpoint: unknown durability '{durability}'")


def flush_exit_buffer(task_id: str, db=None) -> int:
    """Flush buffered exit-mode checkpoints to DB.

    Called on task completion or error to ensure no data loss.
    Returns number of checkpoints flushed.
    """
    buffered = _exit_buffer.pop(task_id, [])
    if not buffered or not db:
        return 0

    count = 0
    for cp in buffered:
        try:
            _write_checkpoint_to_db(cp, db)
            count += 1
        except Exception as e:
            log.warning(f"flush_exit_buffer: failed to write checkpoint: {e}")
    return count


def _write_checkpoint_to_db(cp: StructuredCheckpoint, db) -> None:
    """Write a structured checkpoint to the database."""
    try:
        if hasattr(db, "put_checkpoint"):
            db.put_checkpoint(cp)
        else:
            # Fallback: store as a regular log entry
            import json
            db.write_log(
                "checkpoint",
                json.dumps({
                    "task_id": cp.task_id,
                    "channel_values": str(cp.channel_values)[:2000],
                    "channel_versions": cp.channel_versions,
                    "metadata": cp.metadata,
                    "timestamp": cp.timestamp,
                }),
            )
    except Exception as e:
        log.warning(f"_write_checkpoint_to_db: {e}")


@dataclass
class Checkpoint:
    """Captured state of a partially completed task (git-based, legacy)."""
    task_id: str
    commits_during_task: list[str]
    uncommitted_diff: str
    files_modified: list[str]
    timestamp: str
    resume_prompt: str


def detect_checkpoint(task_id: str, task_start_time: float,
                       cwd: str = ".") -> Checkpoint | None:
    """Detect partial progress since task_start_time.

    Returns a Checkpoint if there's evidence of work, None if the task
    produced nothing.
    """
    try:
        since = datetime.fromtimestamp(task_start_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline", "--no-merges"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        commits = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

        diff_result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        diff_stat = diff_result.stdout.strip()

        full_diff = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        diff_text = full_diff.stdout[:5000]

        status_result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        files = [f.strip() for f in status_result.stdout.strip().split("\n") if f.strip()]

        if not commits and not files:
            return None

        resume_parts = [
            f"## Checkpoint Recovery — Task {task_id}",
            f"The previous agent was interrupted. Here is the partial progress:",
            "",
        ]

        if commits:
            resume_parts.append(f"### Commits made ({len(commits)}):")
            for c in commits[:10]:
                resume_parts.append(f"- {c}")
            resume_parts.append("")

        if diff_stat:
            resume_parts.append(f"### Uncommitted changes:")
            resume_parts.append(f"```\n{diff_stat}\n```")
            resume_parts.append("")

        if diff_text:
            resume_parts.append(f"### Diff preview (first 5KB):")
            resume_parts.append(f"```diff\n{diff_text}\n```")
            resume_parts.append("")

        resume_parts.append("### Your mission:")
        resume_parts.append("Continue from where the previous agent left off. Do NOT redo work that's already committed. Focus on completing the remaining steps.")

        return Checkpoint(
            task_id=task_id,
            commits_during_task=commits,
            uncommitted_diff=diff_text,
            files_modified=files,
            timestamp=datetime.now(timezone.utc).isoformat(),
            resume_prompt="\n".join(resume_parts),
        )

    except Exception as e:
        log.warning(f"checkpoint_recovery: failed to detect checkpoint: {e}")
        return None
