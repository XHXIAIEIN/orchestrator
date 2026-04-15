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
from enum import Enum
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


# ---------------------------------------------------------------------------
# R66 yoyo-evolve: Enhanced Checkpoint-Restart Protocol
# ---------------------------------------------------------------------------


class CheckpointType(Enum):
    """Two checkpoint modes: agent-written (preferred) vs git-derived (fallback)."""
    SEMANTIC = "semantic"     # Agent proactively writes a checkpoint file
    MECHANICAL = "mechanical" # Fallback: built from git log + diff


@dataclass
class EnhancedCheckpoint:
    """Enhanced checkpoint with dual-mode support (R66 yoyo-evolve).

    Two checkpoint types:
    - SEMANTIC: Agent proactively writes a checkpoint file before running
      out of context. Describes "what was done, what remains."
    - MECHANICAL: Fallback built from git log + git diff + uncommitted changes.

    Semantic checkpoints are preferred (more context-aware).
    """
    task_id: str
    checkpoint_type: CheckpointType
    pre_task_sha: str           # git rev-parse HEAD before task started
    commits_during: list[str]   # git log --oneline pre_sha..HEAD
    uncommitted_diff: str       # git diff (first 5KB)
    files_modified: list[str]
    semantic_content: str = ""  # agent-written checkpoint file content
    attempt: int = 1            # which attempt this is (1 or 2)
    timestamp: str = ""
    resume_prompt: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def detect_enhanced_checkpoint(
    task_id: str,
    pre_task_sha: str,
    checkpoint_dir: str,
    cwd: str = ".",
) -> EnhancedCheckpoint | None:
    """Detect partial progress and build an enhanced checkpoint.

    Priority:
      1. Semantic checkpoint file at {checkpoint_dir}/checkpoint_task_{task_id}.md
      2. Mechanical checkpoint derived from git log/diff

    Returns None if no evidence of progress found.
    """
    import os

    try:
        # ── 1. Collect git state ──────────────────────────────────────────
        current_sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        current_sha = current_sha_result.stdout.strip()

        # Commits made since pre_task_sha
        commits: list[str] = []
        if pre_task_sha and current_sha and pre_task_sha != current_sha:
            log_result = subprocess.run(
                ["git", "log", "--oneline", "--no-merges", f"{pre_task_sha}..HEAD"],
                capture_output=True, text=True, cwd=cwd, timeout=10,
            )
            commits = [l.strip() for l in log_result.stdout.strip().splitlines() if l.strip()]

        diff_result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        uncommitted_diff = diff_result.stdout[:5000]

        files_result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        files_modified = [f.strip() for f in files_result.stdout.strip().splitlines() if f.strip()]

        # No evidence of any work at all
        if not commits and not files_modified:
            return None

        # ── 2. Check for semantic checkpoint file ─────────────────────────
        semantic_path = os.path.join(checkpoint_dir, f"checkpoint_task_{task_id}.md")
        semantic_content = ""
        if os.path.isfile(semantic_path):
            try:
                with open(semantic_path, encoding="utf-8") as fh:
                    semantic_content = fh.read()
            except OSError as exc:
                log.warning(f"detect_enhanced_checkpoint: cannot read semantic file: {exc}")

        checkpoint_type = CheckpointType.SEMANTIC if semantic_content else CheckpointType.MECHANICAL

        cp = EnhancedCheckpoint(
            task_id=task_id,
            checkpoint_type=checkpoint_type,
            pre_task_sha=pre_task_sha,
            commits_during=commits,
            uncommitted_diff=uncommitted_diff,
            files_modified=files_modified,
            semantic_content=semantic_content,
        )
        cp.resume_prompt = build_retry_prompt(cp)
        return cp

    except Exception as exc:
        log.warning(f"detect_enhanced_checkpoint: failed: {exc}")
        return None


def build_retry_prompt(checkpoint: EnhancedCheckpoint) -> str:
    """Build a resume prompt from an EnhancedCheckpoint.

    SEMANTIC checkpoints use the agent's own checkpoint content as primary context.
    MECHANICAL checkpoints are reconstructed from git log + diff stat + diff preview.
    Both include explicit "do NOT redo committed work" warnings.
    """
    parts: list[str] = [
        f"## Checkpoint Recovery — Task {checkpoint.task_id}",
        f"Checkpoint type: {checkpoint.checkpoint_type.value.upper()}",
        f"Attempt: {checkpoint.attempt}",
        "",
    ]

    if checkpoint.checkpoint_type == CheckpointType.SEMANTIC:
        parts += [
            "### Agent Checkpoint (self-written)",
            "The previous agent wrote this checkpoint before context ran out:",
            "",
            checkpoint.semantic_content,
            "",
        ]
        if checkpoint.commits_during:
            parts += [
                "### Commits already made (DO NOT redo these):",
                *[f"- {c}" for c in checkpoint.commits_during[:10]],
                "",
            ]

    else:  # MECHANICAL
        parts += [
            "### Mechanical Checkpoint (reconstructed from git)",
            "The previous agent was interrupted. Reconstructed from git history:",
            "",
        ]
        if checkpoint.commits_during:
            parts += [
                f"#### Commits made ({len(checkpoint.commits_during)}):",
                *[f"- {c}" for c in checkpoint.commits_during[:10]],
                "",
            ]

        if checkpoint.files_modified:
            diff_stat_result = None
            try:
                diff_stat_result = subprocess.run(
                    ["git", "diff", "--stat"],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

            parts.append("#### Uncommitted changes:")
            if diff_stat_result and diff_stat_result.stdout.strip():
                parts += [f"```\n{diff_stat_result.stdout.strip()}\n```", ""]

        if checkpoint.uncommitted_diff:
            parts += [
                "#### Diff preview (first 5KB):",
                f"```diff\n{checkpoint.uncommitted_diff}\n```",
                "",
            ]

    parts += [
        "### Instructions",
        "- Continue from the committed state above.",
        "- Do NOT redo work that is already committed.",
        "- Focus only on what remains incomplete.",
        "- If a semantic checkpoint file exists, follow its 'remaining work' section.",
    ]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# R66: Compaction Thrash Detector
# ---------------------------------------------------------------------------


class CompactionThrashDetector:
    """Detect and prevent compaction thrashing (R66 yoyo-evolve).

    If N consecutive compactions produce < threshold reduction,
    stop compacting and suggest /clear instead.
    """

    THRASH_THRESHOLD: int = 2    # consecutive low-value compactions
    MIN_REDUCTION: float = 0.10  # 10% minimum useful reduction

    def __init__(self) -> None:
        self._consecutive_low: int = 0
        self._history: list[tuple[float, float]] = []  # (before, after) token sizes

    def record(self, before_tokens: int, after_tokens: int) -> bool:
        """Record a compaction result. Returns True if thrashing detected.

        A compaction is "low value" when the reduction ratio is below
        MIN_REDUCTION (e.g., 100k -> 95k is only 5%, not worth it).
        """
        self._history.append((float(before_tokens), float(after_tokens)))

        if before_tokens <= 0:
            return False

        reduction = (before_tokens - after_tokens) / before_tokens
        if reduction < self.MIN_REDUCTION:
            self._consecutive_low += 1
        else:
            self._consecutive_low = 0

        thrashing = self._consecutive_low >= self.THRASH_THRESHOLD
        if thrashing:
            log.warning(
                f"CompactionThrashDetector: {self._consecutive_low} consecutive low-value "
                f"compactions (last: {before_tokens}->{after_tokens}, "
                f"reduction={reduction:.1%}). Consider /clear instead."
            )
        return thrashing

    def should_compact(self) -> bool:
        """Returns False if recent compactions have been low-value."""
        return self._consecutive_low < self.THRASH_THRESHOLD

    def reset(self) -> None:
        """Reset after a /clear or significant context change."""
        self._consecutive_low = 0
        self._history.clear()
