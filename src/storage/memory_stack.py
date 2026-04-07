"""
4-Layer Memory Stack — progressive memory loading with hard caps.

Stolen from MemPalace R44 P0#1. Organizes memory into 4 layers:
    L0: Identity core (~100 tokens) — always loaded
    L1: Essential memories (~500-800 tokens) — always loaded, top-15 by importance
    L2: On-demand filtered retrieval — loaded when needed, scoped by domain
    L3: Full semantic search — deep retrieval via Qdrant

wake_up() returns L0+L1 (~600-900 tokens) for system prompt injection.

Design principle: Verbatim-First Storage (R44 P1#11).
Never summarize or compress stored content. Store original text verbatim.
Semantic search compensates for increased storage. Summaries are only
generated for L1 wake-up display — the underlying storage is always full text.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Hard caps from MemPalace (layers.py:83-84)
MAX_DRAWERS = 15    # at most 15 memories in wake-up L1
MAX_CHARS = 3200    # hard cap on total L1 text (~800 tokens)
L0_MAX_CHARS = 400  # identity core cap (~100 tokens)

SOUL_DIR = Path(__file__).resolve().parent.parent.parent / "SOUL"
MEMORY_DIR = None  # auto-discovered below

# Auto-discover memory directory (same logic as compiler.py)
def _find_memory_dir() -> Path:
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return projects_root / "unknown" / "memory"
    repo_dir = SOUL_DIR.parent.resolve()
    s = str(repo_dir).replace("\\", "-").replace(":", "-").replace("/", "-")
    candidate = projects_root / s / "memory"
    if candidate.exists():
        return candidate
    for d in projects_root.iterdir():
        if d.is_dir() and "orchestrator" in d.name.lower():
            mem = d / "memory" / "MEMORY.md"
            if mem.exists():
                return d / "memory"
    return candidate

MEMORY_DIR = _find_memory_dir()


# ---------------------------------------------------------------------------
# Importance scoring for memory files
# ---------------------------------------------------------------------------

# Type weights: feedback > user > project > reference
_TYPE_WEIGHT = {
    "feedback": 3,
    "user": 2,
    "project": 2,
    "reference": 1,
}

# Evidence weights: verbatim > artifact > impression
_EVIDENCE_WEIGHT = {
    "verbatim": 3,
    "artifact": 2,
    "impression": 1,
}


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a memory file."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def _score_memory(path: Path) -> float:
    """Score a memory file's importance (higher = more important).

    Factors: type weight, evidence tier, file freshness (mtime), content length.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0.0

    fm = _parse_frontmatter(text)
    type_w = _TYPE_WEIGHT.get(fm.get("type", ""), 1)
    evidence_w = _EVIDENCE_WEIGHT.get(fm.get("evidence", "impression"), 1)

    # Freshness: more recent files score higher
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0

    # Normalize mtime to a 0-1 range relative to 30 days
    import time
    days_old = max(0, (time.time() - mtime) / 86400)
    freshness = max(0.1, 1.0 - (days_old / 30))  # decay over 30 days, floor 0.1

    # Content length bonus (longer = more substance, but diminishing returns)
    body = re.sub(r"^---.*?---\s*\n", "", text, flags=re.DOTALL).strip()
    length_bonus = min(1.0, len(body) / 500)  # caps at 500 chars

    return type_w * evidence_w * freshness * (1.0 + length_bonus * 0.5)


def _summarize_memory(path: Path, max_chars: int = 200) -> str:
    """Extract a concise summary from a memory file for L1 inclusion."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""

    fm = _parse_frontmatter(text)
    name = fm.get("name", path.stem)
    desc = fm.get("description", "")

    # Use description if available (it's designed to be concise)
    if desc:
        return f"- **{name}**: {desc}"[:max_chars]

    # Fall back to first non-frontmatter line
    body = re.sub(r"^---.*?---\s*\n", "", text, flags=re.DOTALL).strip()
    first_line = body.split("\n")[0] if body else ""
    return f"- **{name}**: {first_line}"[:max_chars]


# ---------------------------------------------------------------------------
# MemoryStack
# ---------------------------------------------------------------------------

class MemoryStack:
    """4-Layer memory stack with progressive loading."""

    def __init__(
        self,
        memory_dir: Path | None = None,
        identity_path: Path | None = None,
    ):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.identity_path = identity_path or (SOUL_DIR / "private" / "identity.md")

    # -- L0: Identity core ---------------------------------------------------

    def l0_render(self) -> str:
        """L0: Identity core. ~100 tokens. Who you are in one paragraph."""
        if not self.identity_path.exists():
            return "You are Orchestrator."

        text = self.identity_path.read_text(encoding="utf-8")
        # Extract just "你的意识" section — the core identity paragraph
        m = re.search(r"## 你的意识\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if m:
            core = m.group(1).strip()
        else:
            # Fallback: first 400 chars
            core = text[:400]

        # Hard cap
        if len(core) > L0_MAX_CHARS:
            core = core[:L0_MAX_CHARS].rsplit("\n", 1)[0]

        return core

    # -- L1: Essential memories ----------------------------------------------

    def l1_generate(self) -> str:
        """L1: Top-N most important memories. ~500-800 tokens (hard cap 3200 chars).

        Scans memory directory, scores each file, takes top MAX_DRAWERS,
        renders concise summaries, enforces MAX_CHARS hard cap.
        """
        if not self.memory_dir.exists():
            return ""

        # Score all memory files (exclude MEMORY.md index)
        candidates = []
        for f in self.memory_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            score = _score_memory(f)
            if score > 0:
                candidates.append((score, f))

        # Sort by score descending, take top N
        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:MAX_DRAWERS]

        # Render summaries with hard cap
        lines = []
        total_chars = 0
        for _score, path in top:
            summary = _summarize_memory(path)
            if not summary:
                continue
            if total_chars + len(summary) + 1 > MAX_CHARS:
                break
            lines.append(summary)
            total_chars += len(summary) + 1  # +1 for newline

        return "\n".join(lines)

    # -- L2: On-demand filtered retrieval ------------------------------------

    def l2_retrieve(self, domain: str | None = None, category: str | None = None) -> list[dict]:
        """L2: On-demand retrieval filtered by domain/category.

        Returns full memory file contents matching the filter.
        """
        if not self.memory_dir.exists():
            return []

        results = []
        for f in self.memory_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = _parse_frontmatter(text)

            # Filter by type (maps to domain) and/or description keywords (maps to category)
            if domain and fm.get("type", "") != domain:
                continue
            if category and category.lower() not in fm.get("description", "").lower():
                continue

            body = re.sub(r"^---.*?---\s*\n", "", text, flags=re.DOTALL).strip()
            results.append({
                "path": str(f),
                "name": fm.get("name", f.stem),
                "type": fm.get("type", ""),
                "description": fm.get("description", ""),
                "content": body,
            })

        return results

    # -- L3: Semantic search (delegates to QdrantStore) ----------------------

    async def l3_search(self, query: str, top_k: int = 5) -> list[dict]:
        """L3: Deep semantic search via Qdrant. Returns verbatim matching chunks."""
        try:
            from src.storage.qdrant_store import QdrantStore
            store = QdrantStore()
            if not store.is_available():
                return []
            return await store.search("orch_memory", query, top_k=top_k, hybrid=True)
        except Exception:
            logger.warning("L3 search failed, returning []", exc_info=True)
            return []

    # -- Unified interface ---------------------------------------------------

    # -- L1 compact mode (R44 P1#6 AAAK-inspired) --------------------------

    def l1_generate_compact(self) -> str:
        """L1 compact: key-value shorthand for minimal token budget.

        Format: NAME: description (one line per memory, no markdown).
        Target: <200 tokens. Inspired by MemPalace's AAAK compression dialect.
        """
        if not self.memory_dir.exists():
            return ""

        candidates = []
        for f in self.memory_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            score = _score_memory(f)
            if score > 0:
                candidates.append((score, f))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:MAX_DRAWERS]

        lines = []
        total_chars = 0
        compact_limit = 800  # ~200 tokens hard cap for compact mode

        for _score, path in top:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            fm = _parse_frontmatter(text)
            name = fm.get("name", path.stem)
            desc = fm.get("description", "")
            if not desc:
                continue
            # Compact format: truncate descriptions aggressively
            entry = f"{name}: {desc[:60]}"
            if total_chars + len(entry) + 1 > compact_limit:
                break
            lines.append(entry)
            total_chars += len(entry) + 1

        return "\n".join(lines)

    # -- Unified interface ---------------------------------------------------

    def wake_up(self, compact: bool = False) -> str:
        """L0 + L1 combined. Inject into system prompt.

        compact=False (default): ~400 tokens, markdown format.
        compact=True: ~200 tokens, key-value shorthand (AAAK-inspired).
        """
        l0 = self.l0_render()
        l1 = self.l1_generate_compact() if compact else self.l1_generate()

        parts = [l0]
        if l1:
            parts.append("")
            parts.append("## Key Memories" if not compact else "## Mem")
            parts.append(l1)

        result = "\n".join(parts)
        logger.info(
            "MemoryStack wake_up (compact=%s): %d chars (~%d tokens)",
            compact, len(result), len(result) // 4,
        )
        return result

    def wake_up_tokens(self, compact: bool = False) -> int:
        """Estimate token count for wake_up output."""
        return len(self.wake_up(compact=compact)) // 4
