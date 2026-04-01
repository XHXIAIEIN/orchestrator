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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Captured state of a partially completed task."""
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
