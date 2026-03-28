"""PatchManager — save/restore git patches for failed task retries.

Stolen pattern from Cline Kanban: persist uncommitted work as a .patch file
so the executor can re-apply changes when a task is retried.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_PATCH_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "patches"


def _run_git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command, returning CompletedProcess (never raises on non-zero)."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class PatchManager:
    """Persist and restore uncommitted git changes across task retries."""

    def __init__(self) -> None:
        _PATCH_ROOT.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, task_id: int, cwd: str) -> Path | None:
        """Snapshot uncommitted changes as data/patches/{task_id}.patch.

        Returns the patch path on success, None if there's nothing to save.
        """
        try:
            result = _run_git(["diff", "HEAD"], cwd=cwd)
        except Exception as exc:
            logger.warning("patch_manager.save: git diff failed for task %s: %s", task_id, exc)
            return None

        if result.returncode != 0:
            logger.warning(
                "patch_manager.save: git diff exited %s for task %s: %s",
                result.returncode, task_id, result.stderr.strip(),
            )
            return None

        diff_output = result.stdout
        if not diff_output.strip():
            logger.debug("patch_manager.save: no uncommitted changes for task %s", task_id)
            return None

        patch_path = _PATCH_ROOT / f"{task_id}.patch"
        patch_path.write_text(diff_output, encoding="utf-8")
        logger.info(
            "patch_manager.save: saved %d bytes → %s",
            len(diff_output.encode("utf-8")), patch_path,
        )
        return patch_path

    def restore(self, task_id: int, cwd: str) -> bool:
        """Re-apply a saved patch into *cwd*.

        Tries ``git apply --3way`` first; falls back to ``git apply --reject``.
        Returns True if at least one strategy succeeded.
        """
        patch_path = _PATCH_ROOT / f"{task_id}.patch"
        if not patch_path.exists():
            logger.debug("patch_manager.restore: no patch for task %s", task_id)
            return False

        patch_str = str(patch_path)

        # Strategy 1: 3-way merge (cleaner, preserves index)
        try:
            result = _run_git(["apply", "--3way", patch_str], cwd=cwd)
            if result.returncode == 0:
                logger.info("patch_manager.restore: --3way succeeded for task %s", task_id)
                return True
            logger.debug(
                "patch_manager.restore: --3way failed (rc=%s): %s",
                result.returncode, result.stderr.strip(),
            )
        except Exception as exc:
            logger.warning("patch_manager.restore: --3way exception for task %s: %s", task_id, exc)

        # Strategy 2: reject — applies what it can, leaves .rej files for the rest
        try:
            result = _run_git(["apply", "--reject", patch_str], cwd=cwd)
            if result.returncode == 0:
                logger.info("patch_manager.restore: --reject succeeded for task %s", task_id)
                return True
            logger.warning(
                "patch_manager.restore: --reject also failed (rc=%s): %s",
                result.returncode, result.stderr.strip(),
            )
        except Exception as exc:
            logger.warning("patch_manager.restore: --reject exception for task %s: %s", task_id, exc)

        return False

    def cleanup(self, task_id: int) -> bool:
        """Delete the patch file for *task_id*.

        Returns True if the file existed (and was removed), False if it was already gone.
        """
        patch_path = _PATCH_ROOT / f"{task_id}.patch"
        if not patch_path.exists():
            return False
        patch_path.unlink()
        logger.info("patch_manager.cleanup: removed patch for task %s", task_id)
        return True

    def has_patch(self, task_id: int) -> bool:
        """Return True if a patch file exists for *task_id*."""
        return (_PATCH_ROOT / f"{task_id}.patch").exists()

    def get_patch_info(self, task_id: int) -> dict | None:
        """Return lightweight metadata for a stored patch (no content read).

        Keys: task_id, path, size_bytes, modified (ISO-8601 string).
        Returns None if the patch does not exist.
        """
        patch_path = _PATCH_ROOT / f"{task_id}.patch"
        if not patch_path.exists():
            return None
        stat = patch_path.stat()
        return {
            "task_id": task_id,
            "path": str(patch_path),
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
