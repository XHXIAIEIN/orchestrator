"""Git-Aware Stale Memory Detection — detect memories referencing deleted files.

Source: R65 Headroom (headroom/memory/budget.py:159-207)

Pipeline:
1. Run `git ls-files` → cached set of tracked files
2. For each memory entry, extract file path references:
   a. From YAML frontmatter `entity_refs` field
   b. From backtick-delimited paths in content: `src/foo/bar.py`
3. If referenced path is NOT in git ls-files AND does not exist on disk → stale
4. Score memories with time decay + access boost
5. Apply token budget truncation

Time decay formula (from Headroom):
  age_days = (now - created_at) / 86400
  decayed_importance = importance * exp(-rate * age_days)
  rate = 0.1 → ~10% decay per day
  access_boost = min(0.3, access_count * 0.05)

Composite score:
  recency = 1.0 / (1.0 + age_days * 0.1)
  access_boost = min(1.0, 0.5 + access_count * 0.1)
  score = importance * recency * access_boost
"""
from __future__ import annotations

import logging
import math
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Cache lifetime in seconds
_GIT_CACHE_TTL = 60.0

# Regex: backtick-enclosed paths with at least one directory separator
_BACKTICK_PATH = re.compile(r'`([/\\]?[\w.-]+(?:[/\\][\w.-]+)+)`')


# ── Git file cache ────────────────────────────────────────────────────────

class GitFileCache:
    """Caches the set of git-tracked files for a repository.

    The cache is refreshed at most once every 60 seconds to avoid
    spawning a subprocess on every memory read.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._cache: frozenset[str] | None = None
        self._cache_time: float = 0.0

    def get_tracked_files(self) -> frozenset[str]:
        """Return the set of paths tracked by git, relative to repo root.

        Results are cached for _GIT_CACHE_TTL seconds.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < _GIT_CACHE_TTL:
            return self._cache

        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                paths = frozenset(
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                )
                self._cache = paths
                self._cache_time = now
                return paths
            else:
                log.warning("git ls-files failed (rc=%d): %s", result.returncode, result.stderr.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log.warning("GitFileCache: could not run git ls-files: %s", exc)

        # Return empty set on failure; don't falsely flag everything as stale
        return frozenset()

    def is_tracked(self, path: str) -> bool:
        """Return True if *path* (relative to repo root) is git-tracked."""
        # Normalise separators for cross-platform safety
        normalised = path.replace("\\", "/")
        return normalised in self.get_tracked_files()

    def invalidate(self) -> None:
        """Force cache refresh on next access."""
        self._cache = None
        self._cache_time = 0.0


# ── Data model ───────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """A parsed memory file."""
    path: Path
    content: str
    frontmatter: dict
    created_at: float       # Unix timestamp
    access_count: int
    importance: float       # 0.0 – 1.0


@dataclass
class StaleReport:
    """Result of a stale memory scan."""
    total_entries: int
    stale_entries: list[MemoryEntry]
    stale_paths: dict[str, list[str]]   # memory file path → list of missing file refs
    scan_duration_ms: float


# ── YAML frontmatter parser (stdlib only) ────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-ish frontmatter between --- delimiters.

    Returns (frontmatter_dict, body_text).  No external YAML library needed;
    we parse only the fields we care about (entity_refs, created_at, etc.).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    header = text[3:end].strip()
    body = text[end + 4:].strip()

    fm: dict = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip()

        # Handle inline lists:  key: [a, b, c]  or  key: a, b, c
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            fm[key] = items
        elif "," in value and not value.startswith('"'):
            items = [v.strip() for v in value.split(",") if v.strip()]
            fm[key] = items
        else:
            fm[key] = value.strip("'\"")

    return fm, body


def _load_memory_entry(md_path: Path) -> MemoryEntry | None:
    """Read and parse a memory .md file into a MemoryEntry."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.debug("Could not read %s: %s", md_path, exc)
        return None

    fm, body = _parse_frontmatter(text)

    # created_at: prefer frontmatter, fall back to file mtime
    created_at_raw = fm.get("created_at", "")
    created_at: float
    if created_at_raw:
        try:
            created_at = float(created_at_raw)
        except (ValueError, TypeError):
            # ISO string fallback
            try:
                import datetime
                created_at = datetime.datetime.fromisoformat(
                    str(created_at_raw).replace("Z", "+00:00")
                ).timestamp()
            except Exception:
                created_at = md_path.stat().st_mtime
    else:
        created_at = md_path.stat().st_mtime

    try:
        access_count = int(fm.get("access_count", 0))
    except (ValueError, TypeError):
        access_count = 0

    try:
        importance = float(fm.get("importance", 0.5))
    except (ValueError, TypeError):
        importance = 0.5

    return MemoryEntry(
        path=md_path,
        content=text,
        frontmatter=fm,
        created_at=created_at,
        access_count=access_count,
        importance=importance,
    )


# ── Stale detection ──────────────────────────────────────────────────────

def _extract_file_refs(entry: MemoryEntry) -> list[str]:
    """Extract all file path references from a memory entry.

    Sources:
    1. ``entity_refs`` list in frontmatter
    2. Backtick-delimited paths in body content
    """
    refs: list[str] = []

    # Source 1: entity_refs frontmatter field
    entity_refs = entry.frontmatter.get("entity_refs", [])
    if isinstance(entity_refs, str):
        entity_refs = [entity_refs]
    refs.extend(str(r) for r in entity_refs if r)

    # Source 2: backtick paths in content
    backtick_matches = _BACKTICK_PATH.findall(entry.content)
    refs.extend(backtick_matches)

    # Normalise: strip leading slashes for relative comparison
    normalised: list[str] = []
    for r in refs:
        clean = r.replace("\\", "/").lstrip("/")
        if clean:
            normalised.append(clean)

    return list(dict.fromkeys(normalised))  # deduplicate, preserve order


def detect_stale_memories(
    memory_dir: Path,
    repo_root: Path,
) -> StaleReport:
    """Scan all .md files in memory_dir and identify those with stale file refs.

    A memory is stale if any referenced path is neither tracked by git nor
    present on disk relative to repo_root.

    Args:
        memory_dir: Directory to scan recursively for .md files.
        repo_root:  Root of the git repository for git ls-files resolution.

    Returns:
        StaleReport with full details.
    """
    t0 = time.monotonic()
    cache = GitFileCache(repo_root)
    repo_root_resolved = repo_root.resolve()

    all_entries: list[MemoryEntry] = []
    stale_entries: list[MemoryEntry] = []
    stale_paths: dict[str, list[str]] = {}

    for md_file in sorted(memory_dir.rglob("*.md")):
        entry = _load_memory_entry(md_file)
        if entry is None:
            continue
        all_entries.append(entry)

        refs = _extract_file_refs(entry)
        missing: list[str] = []
        for ref in refs:
            # Check git tracking
            if cache.is_tracked(ref):
                continue
            # Check disk existence (relative to repo root)
            disk_path = repo_root_resolved / ref
            if disk_path.exists():
                continue
            missing.append(ref)

        if missing:
            stale_entries.append(entry)
            stale_paths[str(md_file)] = missing

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    log.info(
        "stale_detector: scanned %d entries, found %d stale in %.1f ms",
        len(all_entries),
        len(stale_entries),
        elapsed_ms,
    )

    return StaleReport(
        total_entries=len(all_entries),
        stale_entries=stale_entries,
        stale_paths=stale_paths,
        scan_duration_ms=elapsed_ms,
    )


# ── Scoring ──────────────────────────────────────────────────────────────

def score_memory(entry: MemoryEntry, now: float | None = None) -> float:
    """Compute a composite relevance score for a memory entry.

    Formula:
        age_days     = (now - created_at) / 86400
        recency      = 1.0 / (1.0 + age_days * 0.1)
        access_boost = min(1.0, 0.5 + access_count * 0.1)
        score        = importance * recency * access_boost

    Args:
        entry: The memory entry to score.
        now:   Unix timestamp for "now". Defaults to time.time().

    Returns:
        Float in (0, 1].
    """
    if now is None:
        now = time.time()

    age_days = max(0.0, (now - entry.created_at) / 86400.0)
    recency = 1.0 / (1.0 + age_days * 0.1)
    access_boost = min(1.0, 0.5 + entry.access_count * 0.1)
    return entry.importance * recency * access_boost


# ── Budget filter ────────────────────────────────────────────────────────

def _default_token_estimator(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def budget_filter(
    entries: list[MemoryEntry],
    max_tokens: int = 2000,
    token_estimator: Callable[[str], int] | None = None,
) -> list[MemoryEntry]:
    """Filter and truncate a memory list to fit within a token budget.

    Process:
    1. Remove stale entries (those detected via detect_stale_memories)
       — this function does NOT call detect_stale_memories itself; callers
       should pre-filter stale entries before calling budget_filter, or pass
       only non-stale entries.
    2. Sort by composite score (highest first).
    3. Greedily include entries until the token budget is exhausted.

    Args:
        entries:         List of MemoryEntry objects (may include stale).
        max_tokens:      Maximum total tokens to include.
        token_estimator: Optional callable(text) → int. Defaults to 4-chars/token.

    Returns:
        Subset of entries that fits within max_tokens, sorted by score desc.
    """
    estimator = token_estimator or _default_token_estimator
    now = time.time()

    scored = sorted(entries, key=lambda e: score_memory(e, now), reverse=True)

    result: list[MemoryEntry] = []
    total_tokens = 0

    for entry in scored:
        cost = estimator(entry.content)
        if total_tokens + cost > max_tokens:
            break
        result.append(entry)
        total_tokens += cost

    log.debug(
        "budget_filter: %d/%d entries retained (%d tokens used of %d budget)",
        len(result),
        len(entries),
        total_tokens,
        max_tokens,
    )
    return result
