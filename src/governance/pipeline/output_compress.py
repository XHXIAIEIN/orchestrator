# src/governance/pipeline/output_compress.py
"""RTK Output Compression — compress sub-agent results before passing back.

Stolen from pilot-shell's RTK (Return-To-Kernel) pattern. When a sub-agent
finishes, its raw output can be huge (full diffs, verbose logs). Before
passing back to the parent governor, compress it to essential information.

Compression strategies:
  1. Truncate — hard character limit
  2. Extract — pull structured data (VERDICT, file list, error summary)
  3. Summarize — LLM-based compression of verbose output
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Default maximum characters for compressed output
DEFAULT_MAX_CHARS = 6000


@dataclass
class CompressedOutput:
    """Compressed sub-agent result."""
    original_length: int
    compressed_length: int
    strategy: str        # "passthrough" | "truncate" | "extract" | "summarize"
    content: str
    metadata: dict = None

    @property
    def compression_ratio(self) -> float:
        if self.original_length == 0:
            return 1.0
        return self.compressed_length / self.original_length

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def compress_output(
    raw_output: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    strategy: str = "auto",
) -> CompressedOutput:
    """Compress sub-agent output for parent consumption.

    Args:
        raw_output: Full agent output text
        max_chars: Target maximum character count
        strategy: "auto" | "truncate" | "extract"

    Returns:
        CompressedOutput with compressed content
    """
    original_len = len(raw_output)

    if original_len <= max_chars:
        return CompressedOutput(
            original_length=original_len,
            compressed_length=original_len,
            strategy="passthrough",
            content=raw_output,
        )

    if strategy == "auto":
        # Try extract first, fall back to truncate
        extracted = _extract_structured(raw_output)
        if extracted and len(extracted) <= max_chars:
            return CompressedOutput(
                original_length=original_len,
                compressed_length=len(extracted),
                strategy="extract",
                content=extracted,
            )
        strategy = "truncate"

    if strategy == "extract":
        extracted = _extract_structured(raw_output)
        content = extracted if extracted else raw_output[:max_chars]
        return CompressedOutput(
            original_length=original_len,
            compressed_length=len(content),
            strategy="extract",
            content=content[:max_chars],
        )

    # Truncate with intelligent cut points
    content = _smart_truncate(raw_output, max_chars)
    return CompressedOutput(
        original_length=original_len,
        compressed_length=len(content),
        strategy="truncate",
        content=content,
    )


def _extract_structured(text: str) -> str | None:
    """Extract structured information from agent output.

    Pulls: VERDICT lines, file change lists, error summaries,
    and any section headers with their first paragraphs.
    """
    sections = []

    # Extract verdict/status lines
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(p) for p in (
            "VERDICT:", "STATUS:", "RESULT:", "DONE:", "ERROR:",
            "判定:", "状态:", "结果:", "完成:", "错误:",
            "## ", "### ",
        )):
            sections.append(stripped)

    # Extract file change summary
    file_changes = re.findall(r'(?:modified|created|deleted|changed|新建|修改|删除):\s*(.+)', text, re.IGNORECASE)
    if file_changes:
        sections.append("--- Files ---")
        sections.extend(f"  {f.strip()}" for f in file_changes[:10])

    # Extract error blocks
    error_blocks = re.findall(r'(?:Error|Exception|错误|失败)[:：]\s*(.+?)(?:\n\n|\Z)', text, re.IGNORECASE | re.DOTALL)
    if error_blocks:
        sections.append("--- Errors ---")
        for err in error_blocks[:3]:
            sections.append(f"  {err.strip()[:200]}")

    # Extract code diff stats
    diff_stats = re.findall(r'(\d+ files? changed.*)', text)
    if diff_stats:
        sections.extend(diff_stats[:3])

    if not sections:
        return None

    return "\n".join(sections)


def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate text at intelligent boundaries.

    Keeps the beginning (context) and end (results), drops the middle.
    """
    if len(text) <= max_chars:
        return text

    # Reserve space for head, gap marker, and tail
    head_budget = int(max_chars * 0.4)
    tail_budget = int(max_chars * 0.4)
    gap_marker = f"\n\n[... {len(text) - head_budget - tail_budget} chars truncated ...]\n\n"

    # Find clean cut points (paragraph or line boundaries)
    head = text[:head_budget]
    head_cut = head.rfind("\n")
    if head_cut > head_budget * 0.7:
        head = head[:head_cut]

    tail = text[-tail_budget:]
    tail_cut = tail.find("\n")
    if tail_cut > 0 and tail_cut < tail_budget * 0.3:
        tail = tail[tail_cut + 1:]

    return head + gap_marker + tail
