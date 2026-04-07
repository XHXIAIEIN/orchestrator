"""WorktreeManager — git worktree lifecycle for parallel task isolation.

Stolen from Cline Kanban worktree pattern: each task gets an isolated
git worktree so agents don't stomp on each other's working trees.
Large directories (node_modules, .venv, etc.) are junction-linked from
the main repo to avoid duplicating gigabytes on disk.

Windows note: junctions require no admin rights, unlike symlinks.
"""
import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directories to junction-link from main repo into each worktree
_JUNCTION_TARGETS = [
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
]

# Root directory where all worktrees live
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "worktrees"

_IS_WINDOWS = os.name == "nt"

# Windows file attribute for reparse points (junctions/symlinks)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the CompletedProcess result.

    Does NOT raise on non-zero exit — callers inspect returncode themselves.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out after %ds", " ".join(args), timeout)
        raise
    except FileNotFoundError:
        logger.error("git not found in PATH")
        raise


def _is_junction(path: Path) -> bool:
    """Return True if *path* is a junction (Windows) or symlink (Unix)."""
    if not path.exists() and not path.is_symlink():
        return False

    if _IS_WINDOWS:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))  # type: ignore[attr-defined]
        if attrs == 0xFFFFFFFF:  # INVALID_FILE_ATTRIBUTES
            return False
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    else:
        return path.is_symlink()


def _create_junction(src: Path, dst: Path) -> bool:
    """Create a junction (Windows) or symlink (Unix) from dst → src.

    Returns True on success, False on failure.
    src  = existing directory in the main repo
    dst  = desired path inside the worktree
    """
    if not src.exists():
        logger.debug("Junction source does not exist, skipping: %s", src)
        return False

    if dst.exists() or _is_junction(dst):
        logger.debug("Junction destination already exists, skipping: %s", dst)
        return True

    try:
        if _IS_WINDOWS:
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning("mklink /J failed: %s", result.stderr.strip())
                return False
        else:
            dst.symlink_to(src)

        logger.debug("Created junction: %s → %s", dst, src)
        return True
    except Exception as exc:
        logger.warning("Failed to create junction %s → %s: %s", dst, src, exc)
        return False


def _remove_junction(path: Path) -> bool:
    """Remove a junction/symlink without deleting the target's contents.

    Returns True if the junction was removed (or didn't exist).
    """
    if not _is_junction(path):
        if path.exists():
            logger.debug("Not a junction, skipping removal: %s", path)
        return True

    try:
        if _IS_WINDOWS:
            # rmdir removes the junction directory entry without touching target
            result = subprocess.run(
                ["cmd", "/c", "rmdir", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning("rmdir junction failed: %s", result.stderr.strip())
                return False
        else:
            path.unlink()

        logger.debug("Removed junction: %s", path)
        return True
    except Exception as exc:
        logger.warning("Failed to remove junction %s: %s", path, exc)
        return False


# ---------------------------------------------------------------------------
# WorktreeManager
# ---------------------------------------------------------------------------

class WorktreeManager:
    """Manage git worktrees for isolated parallel task execution.

    Each task gets its own worktree at:
        <_WORKTREE_ROOT>/task-<task_id>/

    Large shared directories are junction-linked from the main repo to
    avoid disk duplication.
    """

    def __init__(self, repo_root: Optional[str] = None) -> None:
        if repo_root is not None:
            self._repo_root = Path(repo_root).resolve()
        else:
            # Walk up from this file to find the repo root (.git directory)
            candidate = Path(__file__).resolve()
            for parent in [candidate, *candidate.parents]:
                if (parent / ".git").exists():
                    self._repo_root = parent
                    break
            else:
                # Fallback: three levels up from src/governance/worktree.py
                self._repo_root = Path(__file__).resolve().parent.parent.parent

        self._worktree_root = _WORKTREE_ROOT
        self._worktree_root.mkdir(parents=True, exist_ok=True)

        # In-memory map: task_id → worktree path
        self._active: dict[int, Path] = {}

        # Rebuild in-memory map from git worktree list on startup
        self._sync_active()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, task_id: int, branch_name: Optional[str] = None) -> Optional[Path]:
        """Create a git worktree for *task_id*.

        Strategy (in order):
        1. git worktree add -b task/<task_id> <path>
        2. If branch already exists: git worktree add <path> <branch>
        3. Last resort: git worktree add --detach <path>

        Returns the worktree Path on success, None on failure.
        """
        if task_id in self._active:
            existing = self._active[task_id]
            if existing.exists():
                logger.info("Worktree for task %d already exists at %s", task_id, existing)
                return existing
            else:
                # Stale entry — remove it
                del self._active[task_id]

        branch = branch_name or f"task/{task_id}"
        wt_path = self._worktree_root / f"task-{task_id}"

        if wt_path.exists():
            logger.warning(
                "Worktree path %s exists but not tracked; attempting registration", wt_path
            )
            # Try to register with git
            r = _run_git(["worktree", "repair"], cwd=self._repo_root)
            if wt_path.exists():
                self._active[task_id] = wt_path
                return wt_path

        # Attempt 1: create new branch
        r = _run_git(
            ["worktree", "add", "-b", branch, str(wt_path)],
            cwd=self._repo_root,
        )

        if r.returncode != 0:
            stderr = r.stderr.strip()
            if "already exists" in stderr or "already a worktree" in stderr:
                # Attempt 2: branch exists, just check it out
                logger.debug(
                    "Branch %s already exists, trying checkout strategy", branch
                )
                r2 = _run_git(
                    ["worktree", "add", str(wt_path), branch],
                    cwd=self._repo_root,
                )
                if r2.returncode != 0:
                    # Attempt 3: detach
                    logger.debug(
                        "Checkout strategy failed (%s), falling back to --detach",
                        r2.stderr.strip(),
                    )
                    r3 = _run_git(
                        ["worktree", "add", "--detach", str(wt_path)],
                        cwd=self._repo_root,
                    )
                    if r3.returncode != 0:
                        logger.error(
                            "All worktree creation strategies failed for task %d: %s",
                            task_id,
                            r3.stderr.strip(),
                        )
                        return None
            else:
                logger.error(
                    "git worktree add failed for task %d: %s", task_id, stderr
                )
                return None

        if not wt_path.exists():
            logger.error("Worktree path does not exist after creation: %s", wt_path)
            return None

        # Create junctions for large shared directories
        self._link_junctions(wt_path)

        self._active[task_id] = wt_path
        logger.info("Created worktree for task %d at %s", task_id, wt_path)
        return wt_path

    def cleanup(self, task_id: int) -> bool:
        """Remove the worktree and its branch for *task_id*.

        Steps:
        1. Remove junction links inside the worktree
        2. git worktree remove --force
        3. git branch -D task/<task_id>
        4. If git fails: shutil.rmtree fallback + git worktree prune

        Returns True if cleaned up successfully (or was already absent).
        """
        wt_path = self._active.get(task_id) or (self._worktree_root / f"task-{task_id}")

        if not wt_path.exists():
            logger.debug("Worktree for task %d does not exist, nothing to clean", task_id)
            self._active.pop(task_id, None)
            return True

        # Step 1: remove junctions so git doesn't try to recurse into them
        self._unlink_junctions(wt_path)

        # Step 2: git worktree remove
        r = _run_git(
            ["worktree", "remove", "--force", str(wt_path)],
            cwd=self._repo_root,
        )

        if r.returncode != 0:
            logger.warning(
                "git worktree remove failed for task %d (%s), falling back to rmtree",
                task_id,
                r.stderr.strip(),
            )
            try:
                shutil.rmtree(str(wt_path), ignore_errors=True)
            except Exception as exc:
                logger.error("shutil.rmtree failed for %s: %s", wt_path, exc)

            # Prune stale entries from git's worktree list
            _run_git(["worktree", "prune"], cwd=self._repo_root)

        # Step 3: delete the branch (best-effort)
        branch = f"task/{task_id}"
        rb = _run_git(["branch", "-D", branch], cwd=self._repo_root)
        if rb.returncode != 0:
            logger.debug(
                "Could not delete branch %s (may not exist or may be checked out): %s",
                branch,
                rb.stderr.strip(),
            )

        self._active.pop(task_id, None)
        logger.info("Cleaned up worktree for task %d", task_id)
        return True

    def get_path(self, task_id: int) -> Optional[Path]:
        """Return the worktree path for *task_id*, or None if not active."""
        path = self._active.get(task_id)
        if path is not None and not path.exists():
            # Stale — evict
            del self._active[task_id]
            return None
        return path

    def list_active(self) -> dict[int, Path]:
        """Return a snapshot of all currently active task_id → path mappings."""
        # Evict stale paths
        stale = [tid for tid, p in self._active.items() if not p.exists()]
        for tid in stale:
            del self._active[tid]
        return dict(self._active)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_active(self) -> None:
        """Rebuild _active from git worktree list output."""
        try:
            r = _run_git(["worktree", "list", "--porcelain"], cwd=self._repo_root)
        except Exception:
            return

        if r.returncode != 0:
            return

        current_wt_path: Optional[Path] = None
        for line in r.stdout.splitlines():
            if line.startswith("worktree "):
                current_wt_path = Path(line[len("worktree "):].strip())
            # Match our naming convention: task-<int>
            if current_wt_path is not None:
                name = current_wt_path.name
                if name.startswith("task-") and name[5:].isdigit():
                    tid = int(name[5:])
                    self._active[tid] = current_wt_path
                    current_wt_path = None

    def _link_junctions(self, wt_path: Path) -> None:
        """Create junctions for each entry in _JUNCTION_TARGETS."""
        for target in _JUNCTION_TARGETS:
            src = self._repo_root / target
            dst = wt_path / target
            if src.exists() and not _is_junction(dst) and not dst.exists():
                success = _create_junction(src, dst)
                if not success:
                    logger.debug(
                        "Skipped junction for %s (source missing or creation failed)", target
                    )

    def _unlink_junctions(self, wt_path: Path) -> None:
        """Remove junctions inside *wt_path* without touching their targets."""
        for target in _JUNCTION_TARGETS:
            dst = wt_path / target
            if _is_junction(dst):
                _remove_junction(dst)
