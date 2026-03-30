"""
Incremental Change Awareness — git diff to domain mapping.

Stolen from phodal/entrix (Round 15, P2 pattern):
  git diff -> file-domain mapping -> only run relevant checks.
  Fitness rules with `run_when_changed` glob only fire when matching
  domains have changed. Rules without that field always execute.

Usage:
  changed = get_changed_files("HEAD~1")
  domains = map_files_to_domains(changed)
  active_rules = filter_rules_by_changes(all_rules, domains)
  summary = get_change_summary("HEAD~1")
"""
from __future__ import annotations

import fnmatch
import logging
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain mapping table
# ---------------------------------------------------------------------------

# Each entry: (glob_pattern, domain_name)
_PATH_DOMAIN_MAP: list[tuple[str, str]] = [
    ("src/governance/**",  "governance"),
    ("src/channels/**",    "channels"),
    ("src/collectors/**",  "collectors"),
    ("src/exam/**",        "exam"),
    ("src/core/**",        "core"),
    ("departments/**",     "departments"),
    ("dashboard/**",       "dashboard"),
    ("SOUL/**",            "soul"),
]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(*args: str, cwd: str | None = None) -> str:
    """Run a git command and return stdout. Empty string on failure."""
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("git %s failed (rc=%d): %s", args[0], result.returncode, result.stderr.strip())
            return ""
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("git %s error: %s", args[0], exc)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_changed_files(base_ref: str = "HEAD~1", cwd: str | None = None) -> list[str]:
    """Get list of files changed between base_ref and working tree.

    Includes both committed and staged changes relative to base_ref.
    """
    output = _run_git("diff", "--name-only", base_ref, cwd=cwd)
    if not output:
        return []
    # Normalize to forward slashes
    return [f.replace("\\", "/") for f in output.splitlines() if f.strip()]


def map_files_to_domains(files: list[str]) -> set[str]:
    """Map a list of file paths to their owning domains.

    Uses fnmatch glob patterns against the domain mapping table.
    Files not matching any pattern are silently ignored.
    """
    domains: set[str] = set()
    for filepath in files:
        normalized = filepath.replace("\\", "/")
        for pattern, domain in _PATH_DOMAIN_MAP:
            if fnmatch.fnmatch(normalized, pattern):
                domains.add(domain)
                break  # First match wins
    return domains


def filter_rules_by_changes(
    rules: dict,
    changed_domains: set[str],
) -> dict:
    """Filter fitness rules to only those relevant to changed domains.

    Rules without a `run_when_changed` attribute always pass through.
    Rules with `run_when_changed` (a list of domain globs) are included
    only if at least one glob matches a changed domain.

    Args:
        rules: {dimension: FitnessRule} — as returned by load_fitness_rules()
        changed_domains: set of domain strings from map_files_to_domains()

    Returns:
        Filtered dict with only the relevant rules.
    """
    if not changed_domains:
        # No change info — conservative: run everything
        return dict(rules)

    filtered = {}
    for dim, rule in rules.items():
        # Check for run_when_changed attribute (may not exist on FitnessRule)
        domain_globs = getattr(rule, "run_when_changed", None)

        if domain_globs is None:
            # No restriction — always execute
            filtered[dim] = rule
            continue

        # domain_globs is a list of glob patterns like ["governance", "core"]
        # or wildcard patterns like ["*"] or ["govern*"]
        if isinstance(domain_globs, str):
            domain_globs = [domain_globs]

        for glob_pat in domain_globs:
            if any(fnmatch.fnmatch(d, glob_pat) for d in changed_domains):
                filtered[dim] = rule
                break

    return filtered


def get_change_summary(base_ref: str = "HEAD~1", cwd: str | None = None) -> dict:
    """Return a summary of changes since base_ref.

    Returns:
        {
            "files_changed": list[str],
            "domains": list[str],
            "insertions": int,
            "deletions": int,
        }
    """
    files = get_changed_files(base_ref, cwd=cwd)
    domains = map_files_to_domains(files)

    # Get stat summary
    insertions = 0
    deletions = 0
    stat_output = _run_git("diff", "--stat", "--numstat", base_ref, cwd=cwd)
    if stat_output:
        for line in stat_output.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    ins = int(parts[0]) if parts[0] != "-" else 0
                    dels = int(parts[1]) if parts[1] != "-" else 0
                    insertions += ins
                    deletions += dels
                except ValueError:
                    continue

    return {
        "files_changed": files,
        "domains": sorted(domains),
        "insertions": insertions,
        "deletions": deletions,
    }
