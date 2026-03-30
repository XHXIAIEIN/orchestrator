"""
File Ratchet — line-count-only-decreases guard.

Stolen from phodal/entrix (Round 15, Ratchet pattern):
  Baseline = git HEAD line count for each file.
  If a change pushes line count above baseline + tolerance → fail.
  Prevents AI-generated code bloat by enforcing a directional constraint.

Usage:
  ratchet = FileRatchet(DEFAULT_RATCHET, repo_root="/path/to/repo")
  results = ratchet.check_all()
  for r in results:
      if not r.passed:
          print(f"RATCHET FAIL: {r.path} {r.baseline_lines} → {r.current_lines} (+{r.delta})")
"""
from __future__ import annotations

import fnmatch
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RatchetConfig:
    """Configuration for file ratchet checks."""
    paths: list[str] = field(default_factory=lambda: ["src/**/*.py"])
    exclude: list[str] = field(default_factory=lambda: ["src/**/__pycache__/**", "src/tmp/**"])
    tolerance_lines: int = 5
    tolerance_pct: float = 0.05


@dataclass
class RatchetResult:
    """Result of a single file ratchet check."""
    path: str
    baseline_lines: int
    current_lines: int
    passed: bool
    delta: int


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

DEFAULT_RATCHET = RatchetConfig(
    paths=["src/**/*.py"],
    exclude=["src/**/__pycache__/**", "src/tmp/**"],
    tolerance_lines=10,
    tolerance_pct=0.10,
)


# ---------------------------------------------------------------------------
# FileRatchet
# ---------------------------------------------------------------------------


class FileRatchet:
    """Check that file line counts don't exceed git HEAD baseline + tolerance."""

    def __init__(self, config: RatchetConfig, repo_root: str = ".") -> None:
        self.config = config
        self.repo_root = Path(repo_root).resolve()

    def get_baseline(self, file_path: str) -> int:
        """Get line count from git HEAD for a file.

        Returns 0 if the file is new (not in HEAD) or git fails.
        """
        rel = self._to_relative(file_path)
        try:
            result = subprocess.run(
                ["git", "show", f"HEAD:{rel}"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_root),
                timeout=10,
            )
            if result.returncode != 0:
                # File doesn't exist in HEAD (new file) — no constraint
                log.debug("ratchet: %s not in HEAD, baseline=0", rel)
                return 0
            return result.stdout.count("\n")
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("ratchet: git failed for %s: %s", rel, e)
            return 0

    def check(self, file_path: str) -> RatchetResult:
        """Check a single file against its baseline."""
        baseline = self.get_baseline(file_path)
        current = self._count_lines(file_path)
        delta = current - baseline

        if baseline == 0:
            # New file — ratchet doesn't apply yet
            passed = True
        else:
            abs_tolerance = self.config.tolerance_lines
            pct_tolerance = int(baseline * self.config.tolerance_pct)
            effective_tolerance = max(abs_tolerance, pct_tolerance)
            passed = delta <= effective_tolerance

        if not passed:
            rel = self._to_relative(file_path)
            log.warning(
                "ratchet FAIL: %s %d → %d (+%d, tolerance=%d)",
                rel, baseline, current, delta,
                max(self.config.tolerance_lines, int(baseline * self.config.tolerance_pct)),
            )

        return RatchetResult(
            path=file_path,
            baseline_lines=baseline,
            current_lines=current,
            passed=passed,
            delta=delta,
        )

    def check_all(self) -> list[RatchetResult]:
        """Check all files matching config paths (excluding excludes)."""
        files = self._collect_files()
        results = []
        for f in sorted(files):
            results.append(self.check(f))
        return results

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _to_relative(self, file_path: str) -> str:
        """Convert to a git-friendly relative path (forward slashes)."""
        try:
            rel = Path(file_path).resolve().relative_to(self.repo_root)
            return str(rel).replace("\\", "/")
        except ValueError:
            return file_path.replace("\\", "/")

    def _count_lines(self, file_path: str) -> int:
        """Count lines in a local file."""
        try:
            return Path(file_path).read_text(encoding="utf-8").count("\n")
        except OSError:
            return 0

    def _collect_files(self) -> list[str]:
        """Glob all matching files under repo_root, minus excludes."""
        matched: set[str] = set()
        for pattern in self.config.paths:
            for p in self.repo_root.glob(pattern):
                if p.is_file():
                    matched.add(str(p))

        # Apply exclusions
        excluded: set[str] = set()
        for ex_pattern in self.config.exclude:
            for p in self.repo_root.glob(ex_pattern):
                excluded.add(str(p))

        # Also filter by fnmatch for paths that glob didn't catch
        result = []
        for f in matched:
            rel = self._to_relative(f)
            skip = False
            for ex in self.config.exclude:
                if fnmatch.fnmatch(rel, ex):
                    skip = True
                    break
            if f in excluded:
                skip = True
            if not skip:
                result.append(f)

        log.debug("ratchet: collected %d files from %s", len(result), self.config.paths)
        return result
