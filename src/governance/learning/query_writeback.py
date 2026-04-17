"""R75 Graphify: Query Result Writeback — Memory Feedback Loop.

When the system answers a question (Q&A, analysis, diagnosis), the result
is saved as a Markdown file in the memory directory. On the next memory
synthesis cycle, these files are automatically scanned and incorporated.

This closes the feedback loop: knowledge grows not just from external input,
but from the system's own reasoning. "Ask and learn" instead of "ask and forget."

File format:
    memory/query_results/qa_20260415_120000_<slug>.md
    - YAML frontmatter with type, date, question, source references
    - Body with question, answer, and sources

Integration:
    - memory_synthesizer.py: add query_results/ to scan paths
    - executor_session.py: call save_query_result() after significant Q&A

Source: Graphify ingest.py save_query_result() (R75 deep steal)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not (_REPO_ROOT / "src").is_dir():
    _REPO_ROOT = _REPO_ROOT.parent

DEFAULT_MEMORY_DIR = _REPO_ROOT / ".remember"
QUERY_RESULTS_DIR = DEFAULT_MEMORY_DIR / "query_results"


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w]", "_", text.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:max_len]


def save_query_result(
    question: str,
    answer: str,
    source_refs: list[str] | None = None,
    memory_dir: Path | None = None,
    tags: list[str] | None = None,
    department: str = "",
) -> Path | None:
    """Save a Q&A result as Markdown for future memory synthesis.

    This is the core of the memory feedback loop: every significant answer
    the system produces becomes input for future knowledge.

    Args:
        question: The original question or task description.
        answer: The system's response/analysis.
        source_refs: Optional list of source file paths or URLs.
        memory_dir: Override memory directory (default: .remember/).
        tags: Optional tags for categorization.
        department: Which department produced this answer.

    Returns:
        Path to the written file, or None on failure.
    """
    if not question or not answer:
        return None

    now = datetime.now(timezone.utc)
    slug = _slugify(question)
    filename = f"qa_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.md"

    output_dir = memory_dir or QUERY_RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    tag_str = ", ".join(tags) if tags else ""
    frontmatter_lines = [
        "---",
        f'type: "query_result"',
        f'date: "{now.isoformat()}"',
        f'question: "{question[:200]}"',
    ]
    if department:
        frontmatter_lines.append(f'department: "{department}"')
    if tag_str:
        frontmatter_lines.append(f'tags: [{tag_str}]')
    frontmatter_lines.append(f'evidence: "artifact"')
    frontmatter_lines.append("---")

    # Build body
    body_parts = [
        f"\n# Q: {question}\n",
        f"## Answer\n\n{answer}\n",
    ]
    if source_refs:
        body_parts.append("\n## Sources\n")
        body_parts.extend(f"- {ref}" for ref in source_refs)
        body_parts.append("")

    content = "\n".join(frontmatter_lines) + "\n".join(body_parts)

    out_path = output_dir / filename
    try:
        out_path.write_text(content, encoding="utf-8")
        log.info("query_writeback: saved %s (%d chars)", filename, len(content))
        return out_path
    except OSError as exc:
        log.error("query_writeback: failed to write %s: %s", filename, exc)
        return None


def list_query_results(memory_dir: Path | None = None) -> list[Path]:
    """List all saved query result files, newest first."""
    target = memory_dir or QUERY_RESULTS_DIR
    if not target.is_dir():
        return []
    files = sorted(target.glob("qa_*.md"), reverse=True)
    return files


def count_query_results(memory_dir: Path | None = None) -> int:
    """Count saved query results."""
    return len(list_query_results(memory_dir))


def prune_old_results(
    max_files: int = 200,
    memory_dir: Path | None = None,
) -> int:
    """Remove oldest query results if count exceeds max_files.

    Returns number of files removed.
    """
    files = list_query_results(memory_dir)
    if len(files) <= max_files:
        return 0

    to_remove = files[max_files:]  # files is newest-first, remove oldest
    removed = 0
    for f in to_remove:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass

    if removed:
        log.info("query_writeback: pruned %d old results", removed)
    return removed
