"""
MCP Memory Server — exposes Orchestrator's memory system via MCP protocol.

Resources (read-only):
  memory://buffer   → .remember/remember.md
  memory://recent   → .remember/recent.md       (if exists)
  memory://archive  → .remember/archive.md      (if exists)
  memory://core     → .remember/core-memories.md (if exists)
  memory://public/{path} → SOUL/public/{path}   (read-only)

Tools (write / query):
  memory_write(target, content)   — append to buffer (.remember/remember.md)
  memory_save(facts, source, importance) — save atomic facts to shared memory
  memory_search(query, scope)     — full-text search across memory files
  memory_list(scope)              — list available memory entries

Security:
  SOUL/private/ is NEVER exposed — no resource, no tool bypass.
  All resource reads are appended to src/mcp/audit.log.

Run:
  python -m src.mcp.memory_server
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from src.core.atomic_write import atomic_write

log = logging.getLogger(__name__)

# ── Path resolution ─────────────────────────────────────────────────────

def _find_repo_root() -> Path:
    """Walk up from this file until we find the repo root (has src/ and .remember/ or SOUL/)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "src").is_dir() and ((p / ".remember").is_dir() or (p / "SOUL").is_dir()):
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent.parent


REPO_ROOT = _find_repo_root()
REMEMBER_DIR = REPO_ROOT / ".remember"
SOUL_PUBLIC_DIR = REPO_ROOT / "SOUL" / "public"
SOUL_PRIVATE_DIR = REPO_ROOT / "SOUL" / "private"
AUDIT_LOG = Path(__file__).resolve().parent / "audit.log"

# Canonical memory file paths
_MEMORY_FILES: dict[str, Path] = {
    "buffer": REMEMBER_DIR / "remember.md",
    "recent": REMEMBER_DIR / "recent.md",
    "archive": REMEMBER_DIR / "archive.md",
    "core": REMEMBER_DIR / "core-memories.md",
    "shared": REMEMBER_DIR / "shared",   # directory, not a file
}

# ── Shared-memory constants ──────────────────────────────────────────────

_SUPERSEDE_SIMILARITY = 0.70
_SHARED_DIR = REMEMBER_DIR / "shared"

# Warm-up flag: set to True once _SHARED_DIR has been initialised
_shared_dir_ready: bool = False


def _ensure_shared_dir() -> None:
    """Create .remember/shared/ on first use."""
    global _shared_dir_ready
    if not _shared_dir_ready:
        _SHARED_DIR.mkdir(parents=True, exist_ok=True)
        _shared_dir_ready = True

# ── Jaccard similarity helper ────────────────────────────────────────────

def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity for fast approximate matching.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Float in [0.0, 1.0]. 1.0 = identical word sets.
    """
    tokens_a = frozenset(re.findall(r'\w+', a.lower()))
    tokens_b = frozenset(re.findall(r'\w+', b.lower()))
    if not tokens_a and not tokens_b:
        return 1.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


# ── Audit logger ────────────────────────────────────────────────────────

def _audit(action: str, resource: str, requester: str = "mcp-client") -> None:
    """Append one line to audit.log: timestamp | action | resource | requester."""
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    line = f"{ts} | {action} | {resource} | {requester}\n"
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        log.warning("audit.log write failed: %s", e)


# ── Safety guard ────────────────────────────────────────────────────────

def _is_private_path(path: Path) -> bool:
    """Return True if path is inside SOUL/private/. Must never be exposed."""
    try:
        path.resolve().relative_to(SOUL_PRIVATE_DIR.resolve())
        return True
    except ValueError:
        return False


def _safe_read(path: Path, label: str) -> str:
    """Read a file safely. Raises if private or missing."""
    if _is_private_path(path):
        raise PermissionError(f"Access denied: {label} is in SOUL/private/")
    if not path.exists():
        raise FileNotFoundError(f"Memory file not found: {label}")
    return path.read_text(encoding="utf-8")


# ── MCP server ──────────────────────────────────────────────────────────

mcp = FastMCP(
    name="orchestrator-memory",
    instructions=(
        "Provides read/write access to Orchestrator's memory system. "
        "SOUL/private/ is never exposed. "
        "Write operations only append to the buffer (remember.md)."
    ),
)


# ── Resources ───────────────────────────────────────────────────────────

@mcp.resource("memory://buffer", name="buffer", description="Current memory buffer (.remember/remember.md)", mime_type="text/markdown")
def resource_buffer() -> str:
    _audit("READ", "memory://buffer")
    return _safe_read(_MEMORY_FILES["buffer"], "buffer")


@mcp.resource("memory://recent", name="recent", description="7-day rolling memory (.remember/recent.md)", mime_type="text/markdown")
def resource_recent() -> str:
    _audit("READ", "memory://recent")
    return _safe_read(_MEMORY_FILES["recent"], "recent")


@mcp.resource("memory://archive", name="archive", description="Older archived memories (.remember/archive.md)", mime_type="text/markdown")
def resource_archive() -> str:
    _audit("READ", "memory://archive")
    return _safe_read(_MEMORY_FILES["archive"], "archive")


@mcp.resource("memory://core", name="core", description="Core persistent memories (.remember/core-memories.md)", mime_type="text/markdown")
def resource_core() -> str:
    _audit("READ", "memory://core")
    return _safe_read(_MEMORY_FILES["core"], "core")


@mcp.resource(
    "memory://public/{path}",
    name="public",
    description="Read a file from SOUL/public/ by relative path",
    mime_type="text/plain",
)
def resource_public(path: str) -> str:
    # Normalise: strip leading slashes to prevent path traversal
    clean = path.lstrip("/").replace("..", "")
    target = (SOUL_PUBLIC_DIR / clean).resolve()

    # Must still be inside SOUL/public/ after resolution
    try:
        target.relative_to(SOUL_PUBLIC_DIR.resolve())
    except ValueError:
        raise PermissionError(f"Path traversal attempt: {path}")

    if _is_private_path(target):
        raise PermissionError("Access denied: SOUL/private/ is not accessible")

    _audit("READ", f"memory://public/{clean}")
    if not target.exists():
        raise FileNotFoundError(f"SOUL/public/{clean} not found")
    return target.read_text(encoding="utf-8")


# ── Tools ───────────────────────────────────────────────────────────────

@mcp.tool(description="Append content to the memory buffer (.remember/remember.md). Only the buffer is writable.")
def memory_write(content: str) -> str:
    """Append a timestamped entry to the memory buffer.

    Args:
        content: Text to append. Will be prefixed with a UTC timestamp.

    Returns:
        Confirmation message with the number of bytes written.
    """
    if not content or not content.strip():
        return "Error: content must not be empty"

    buf_path = _MEMORY_FILES["buffer"]
    buf_path.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n<!-- written via MCP {ts} -->\n{content.strip()}\n"

    with buf_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    _audit("WRITE", "memory://buffer")
    byte_count = len(entry.encode("utf-8"))
    return f"Appended {byte_count} bytes to buffer."


@mcp.tool(description="Save atomic facts to shared memory. Each fact is stored independently. Similar facts (>70% match) auto-supersede older entries.")
def memory_save(
    facts: list[str],
    source: str = "mcp-client",
    importance: float = 0.5,
) -> str:
    """Save a list of atomic facts to .remember/shared/.

    Each fact is written as its own timestamped .md file with YAML frontmatter.
    Before writing, existing shared/*.md files are checked for Jaccard similarity
    >= _SUPERSEDE_SIMILARITY; matching entries are marked as superseded.

    Args:
        facts:      List of atomic fact strings.
        source:     Identifier of the caller (logged in frontmatter).
        importance: Float 0.0–1.0 stored in frontmatter for scoring.

    Returns:
        Summary of saved and superseded counts.
    """
    _ensure_shared_dir()

    if not facts:
        return "Error: facts list must not be empty"

    valid_facts = [f.strip() for f in facts if f and f.strip()]
    if not valid_facts:
        return "Error: all facts were empty strings"

    # Load existing shared entries for similarity check
    existing_files = sorted(_SHARED_DIR.glob("*.md"))
    existing_data: list[tuple[Path, str, dict]] = []  # (path, content_str, frontmatter_dict)

    def _parse_shared_fm(text: str) -> dict:
        """Minimal frontmatter parse for shared entries."""
        fm: dict = {}
        if not text.startswith("---"):
            return fm
        end = text.find("\n---", 3)
        if end == -1:
            return fm
        for line in text[3:end].splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip("'\"")
        return fm

    for ef in existing_files:
        try:
            raw = ef.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_shared_fm(raw)
        # Skip already-superseded entries from similarity pool
        if fm.get("superseded_by"):
            continue
        # Extract the fact body (after frontmatter)
        body = raw
        if raw.startswith("---"):
            end = raw.find("\n---", 3)
            if end != -1:
                body = raw[end + 4:].strip()
        existing_data.append((ef, body, fm))

    now_ts = time.time()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    saved = 0
    superseded_total = 0

    for fact_text in valid_facts:
        # Find near-duplicates and mark them superseded
        superseded_paths: list[str] = []
        for ef_path, ef_body, ef_fm in existing_data:
            sim = _jaccard_similarity(fact_text, ef_body)
            if sim >= _SUPERSEDE_SIMILARITY:
                superseded_paths.append(ef_path.name)
                try:
                    updated = ef_path.read_text(encoding="utf-8")
                    new_fm_line = f"superseded_by: {now_iso}\n"
                    if "superseded_by:" in updated:
                        updated = re.sub(
                            r'superseded_by:.*\n',
                            new_fm_line,
                            updated,
                        )
                    else:
                        # Insert before closing ---
                        close = updated.find("\n---", 3)
                        if close != -1:
                            updated = updated[:close] + f"\n{new_fm_line.rstrip()}" + updated[close:]
                    atomic_write(ef_path, updated)
                    superseded_total += 1
                except OSError as exc:
                    log.warning("memory_save: could not update superseded entry %s: %s", ef_path, exc)

        # Build new entry ID and filename
        fact_hash = hashlib.sha1(fact_text.encode()).hexdigest()[:8]
        headroom_id = f"shm-{int(now_ts)}-{fact_hash}"
        filename = f"{int(now_ts)}-{fact_hash}.md"
        target = _SHARED_DIR / filename

        frontmatter_lines = [
            "---",
            f"headroom_id: {headroom_id}",
            f"source: {source}",
            f"importance: {importance}",
            f"created_at: {now_iso}",
            f"access_count: 0",
        ]
        if superseded_paths:
            frontmatter_lines.append(f"supersedes: {', '.join(superseded_paths)}")
        frontmatter_lines.append("---")
        frontmatter_lines.append("")
        frontmatter_lines.append(fact_text)

        entry_text = "\n".join(frontmatter_lines)
        try:
            atomic_write(target, entry_text)
            saved += 1
            # Add to existing_data so subsequent facts in same batch see this one
            existing_data.append((target, fact_text, {
                "headroom_id": headroom_id,
                "source": source,
                "importance": str(importance),
                "created_at": now_iso,
            }))
        except OSError as exc:
            log.error("memory_save: failed to write %s: %s", target, exc)

    _audit("SAVE", f"shared facts={saved} superseded={superseded_total} source={source}")
    return (
        f"Saved {saved}/{len(valid_facts)} fact(s) to shared memory. "
        f"Superseded {superseded_total} older similar entries."
    )


@mcp.tool(description="Search across memory files for a query string. scope: buffer|recent|archive|core|shared|public|all")
def memory_search(query: str, scope: str = "all", top_k: int = 30) -> str:
    """Search memory files for matching lines.

    Args:
        query: Search term (case-insensitive substring match).
        scope: Which files to search. One of:
               buffer, recent, archive, core, shared, public, all.
               'all' searches buffer + recent + archive + core + shared
               (not public tree).
        top_k: Maximum results to return for the 'shared' scope (default 30).
               Over-fetches top_k*3 candidates then filters superseded entries.

    Returns:
        Matching lines with file label, or a 'no matches' message.
    """
    if not query or not query.strip():
        return "Error: query must not be empty"

    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    results: list[str] = []

    def _search_file(label: str, path: Path) -> None:
        if not path.exists():
            return
        try:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    results.append(f"[{label}:{i}] {line.rstrip()}")
        except OSError:
            pass

    if scope in ("buffer", "all"):
        _search_file("buffer", _MEMORY_FILES["buffer"])
    if scope in ("recent", "all"):
        _search_file("recent", _MEMORY_FILES["recent"])
    if scope in ("archive", "all"):
        _search_file("archive", _MEMORY_FILES["archive"])
    if scope in ("core", "all"):
        _search_file("core", _MEMORY_FILES["core"])

    if scope in ("shared", "all"):
        _ensure_shared_dir()
        # Over-fetch (top_k * 3) then filter superseded
        candidates: list[tuple[str, str]] = []  # (label, line_text)
        for md_file in sorted(_SHARED_DIR.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            # Skip superseded entries
            if re.search(r'^superseded_by:', text, re.MULTILINE):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    candidates.append((f"shared/{md_file.name}:{i}", line.rstrip()))
        # Truncate to top_k after filtering
        for label, line in candidates[: top_k * 3][:top_k]:
            results.append(f"[{label}] {line}")

    if scope == "public":
        if SOUL_PUBLIC_DIR.exists():
            for md_file in SOUL_PUBLIC_DIR.rglob("*.md"):
                rel = md_file.relative_to(SOUL_PUBLIC_DIR)
                _search_file(f"public/{rel}", md_file)

    _audit("SEARCH", f"scope={scope} query={query[:80]}")

    if not results:
        return f"No matches for '{query}' in scope '{scope}'."

    header = f"Found {len(results)} match(es) for '{query}' in scope '{scope}':\n"
    # Cap at 100 lines to avoid context overflow
    truncated = results[:100]
    body = "\n".join(truncated)
    suffix = f"\n... (truncated, {len(results) - 100} more)" if len(results) > 100 else ""
    return header + body + suffix


@mcp.tool(description="List available memory entries or public files. scope: buffer|recent|archive|core|shared|public")
def memory_list(scope: str = "buffer") -> str:
    """List entries or files in the specified memory scope.

    Args:
        scope: One of: buffer, recent, archive, core, shared, public.
               For file scopes (buffer/recent/archive/core), returns line count and size.
               For 'shared', returns atomic fact files with superseded status.
               For 'public', returns available file paths under SOUL/public/.

    Returns:
        Human-readable listing.
    """
    _audit("LIST", f"scope={scope}")

    if scope == "public":
        if not SOUL_PUBLIC_DIR.exists():
            return "SOUL/public/ directory not found."
        files = sorted(SOUL_PUBLIC_DIR.rglob("*"))
        lines = [
            str(f.relative_to(SOUL_PUBLIC_DIR))
            for f in files
            if f.is_file() and not _is_private_path(f)
        ]
        if not lines:
            return "No files in SOUL/public/."
        return f"SOUL/public/ ({len(lines)} files):\n" + "\n".join(lines)

    if scope == "shared":
        _ensure_shared_dir()
        all_files = sorted(_SHARED_DIR.glob("*.md"))
        if not all_files:
            return "No shared facts stored yet."
        active = []
        superseded = []
        for f in all_files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if re.search(r'^superseded_by:', text, re.MULTILINE):
                superseded.append(f.name)
            else:
                active.append(f.name)
        return (
            f"shared/ — {len(active)} active, {len(superseded)} superseded "
            f"({len(all_files)} total)\n"
            "active:\n" + "\n".join(f"  {n}" for n in active) +
            ("\nsuperseded:\n" + "\n".join(f"  {n}" for n in superseded) if superseded else "")
        )

    if scope not in _MEMORY_FILES:
        valid = ", ".join(_MEMORY_FILES.keys()) + ", public"
        return f"Unknown scope '{scope}'. Valid: {valid}"

    path = _MEMORY_FILES[scope]
    # 'shared' is a directory — handled above; remaining keys are files
    if path.is_dir():
        return f"scope '{scope}' is a directory — use scope='shared' for directory listing"
    if not path.exists():
        return f"Memory file for '{scope}' does not exist yet: {path.name}"

    stat = path.stat()
    text = path.read_text(encoding="utf-8")
    line_count = text.count("\n")
    size_kb = stat.st_size / 1024

    return (
        f"scope={scope} | file={path.name} | "
        f"lines={line_count} | size={size_kb:.1f} KB\n"
        f"path: {path}"
    )


# ── Lazy warm-up ────────────────────────────────────────────────────────

def _warmup() -> None:
    """Initialise shared memory dir at server start (not on first query)."""
    _ensure_shared_dir()
    log.info("memory_server warmup: shared dir ready at %s", _SHARED_DIR)


# Register warm-up via FastMCP lifespan if available, otherwise call at import.
# FastMCP exposes an `on_startup` list on some versions; fall back gracefully.
try:
    mcp.on_startup.append(_warmup)  # type: ignore[attr-defined]
except AttributeError:
    # Older FastMCP — warm up at import time instead (still lazy relative to queries)
    _warmup()


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    log.info("Starting Orchestrator Memory MCP server (stdio)...")
    log.info("REPO_ROOT: %s", REPO_ROOT)
    log.info("REMEMBER_DIR: %s", REMEMBER_DIR)
    log.info("SOUL_PUBLIC: %s", SOUL_PUBLIC_DIR)
    log.info("AUDIT_LOG: %s", AUDIT_LOG)
    mcp.run(transport="stdio")
