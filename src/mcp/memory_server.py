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
import logging
import os
import re
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

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
}

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


@mcp.tool(description="Search across memory files for a query string. scope: buffer|recent|archive|core|public|all")
def memory_search(query: str, scope: str = "all") -> str:
    """Search memory files for matching lines.

    Args:
        query: Search term (case-insensitive substring match).
        scope: Which files to search. One of: buffer, recent, archive, core, public, all.
               'all' searches buffer + recent + archive + core (not public tree).

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


@mcp.tool(description="List available memory entries or public files. scope: buffer|recent|archive|core|public")
def memory_list(scope: str = "buffer") -> str:
    """List entries or files in the specified memory scope.

    Args:
        scope: One of: buffer, recent, archive, core, public.
               For file scopes (buffer/recent/archive/core), returns line count and size.
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

    if scope not in _MEMORY_FILES:
        valid = ", ".join(_MEMORY_FILES.keys()) + ", public"
        return f"Unknown scope '{scope}'. Valid: {valid}"

    path = _MEMORY_FILES[scope]
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
