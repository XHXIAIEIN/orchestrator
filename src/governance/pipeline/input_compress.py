"""Input Compression — compress incoming context before sub-agent consumption.

Stolen from: microsoft/VibeVoice (Round 17)
Patterns: Segment-then-Concat + Compression-as-First-Class

VibeVoice's 7.5Hz tokenizer compresses 60-min audio into 27K tokens BEFORE
the LLM backbone sees it. The equivalent for Orchestrator: chain-from context
and conversation history should be compressed BEFORE injection into the
sub-agent prompt, not after.

This is the symmetric counterpart to output_compress.py:
  output_compress.py  →  compress results AFTER execution
  input_compress.py   →  compress context BEFORE execution

Compression pipeline:
  1. Segment — split long context into fixed-size chunks
  2. Compress — extract structured info from each segment independently
  3. Concat — merge compressed segments with is_final_chunk marker
  4. Budget — ensure total fits within tier's context_budget
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Segment size in characters (analogous to VibeVoice's 60-second segments)
DEFAULT_SEGMENT_SIZE = 3000
# Minimum context length before compression kicks in
COMPRESS_THRESHOLD = 4000


@dataclass
class CompressedInput:
    """Compressed input context ready for prompt injection."""
    original_length: int
    compressed_length: int
    num_segments: int
    strategy: str            # "passthrough" | "segment_extract" | "segment_truncate"
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.original_length == 0:
            return 1.0
        return self.compressed_length / self.original_length


@dataclass
class Segment:
    """A single segment of input context."""
    index: int
    text: str
    is_final: bool = False


def segment_context(text: str, segment_size: int = DEFAULT_SEGMENT_SIZE) -> list[Segment]:
    """Split input context into segments at paragraph boundaries.

    Analogous to VibeVoice's _iter_segments() that splits 60-min audio
    into 60-second chunks for independent encoding.
    """
    if len(text) <= segment_size:
        return [Segment(index=0, text=text, is_final=True)]

    segments = []
    pos = 0
    idx = 0

    while pos < len(text):
        end = min(pos + segment_size, len(text))

        # Find clean cut point at paragraph boundary
        if end < len(text):
            # Look for double newline (paragraph break)
            cut = text.rfind("\n\n", pos, end)
            if cut > pos + segment_size * 0.5:
                end = cut + 2  # Include the double newline
            else:
                # Fall back to single newline
                cut = text.rfind("\n", pos, end)
                if cut > pos + segment_size * 0.6:
                    end = cut + 1

        chunk = text[pos:end]
        segments.append(Segment(index=idx, text=chunk))
        pos = end
        idx += 1

    if segments:
        segments[-1].is_final = True

    return segments


def _extract_segment(segment: Segment) -> str:
    """Extract structured information from a single segment.

    Pulls: headers, key-value pairs, verdicts, file references,
    code blocks (first/last lines only), and error summaries.
    """
    text = segment.text
    extracted = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Section headers
        if stripped.startswith(("#", "##", "###")):
            extracted.append(stripped)
            continue

        # Verdict/status/result lines
        if any(stripped.upper().startswith(p) for p in (
            "VERDICT:", "STATUS:", "RESULT:", "ERROR:", "DONE:", "FAILED:",
            "判定:", "状态:", "结果:", "错误:", "完成:", "失败:",
        )):
            extracted.append(stripped)
            continue

        # File references
        if re.search(r'(?:src|departments|SOUL|dashboard|tests|config)/[\w/.-]+\.\w+', stripped):
            extracted.append(stripped)
            continue

        # Key-value patterns (important context)
        if re.match(r'^[\w_-]+\s*[:=]\s*.+', stripped):
            extracted.append(stripped)
            continue

        # Bullet points with actionable content
        if stripped.startswith(("- ", "* ", "• ")) and len(stripped) < 200:
            extracted.append(stripped)
            continue

    # Code blocks — keep first and last lines only
    code_blocks = re.findall(r'```\w*\n(.*?)```', text, re.DOTALL)
    for block in code_blocks[:3]:
        lines = block.strip().splitlines()
        if len(lines) <= 3:
            extracted.append(f"```\n{block.strip()}\n```")
        else:
            extracted.append(f"```\n{lines[0]}\n  ... ({len(lines)-2} lines) ...\n{lines[-1]}\n```")

    if not extracted:
        # Fallback: keep first 2 and last 2 non-empty lines
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) <= 4:
            return text.strip()
        return "\n".join(lines[:2] + ["  ..."] + lines[-2:])

    # Add final segment marker
    if segment.is_final:
        extracted.append("[end of context]")

    return "\n".join(extracted)


def compress_input(
    raw_context: str,
    context_budget: int = 0,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
    strategy: str = "auto",
) -> CompressedInput:
    """Compress input context for sub-agent prompt injection.

    Args:
        raw_context: Full context text (chain-from output, conversation history, etc.)
        context_budget: Target token budget (0 = use character-based heuristic).
                       Converted to char estimate at ~4 chars/token.
        segment_size: Characters per segment for Segment-then-Concat.
        strategy: "auto" | "segment_extract" | "segment_truncate"

    Returns:
        CompressedInput with compressed content.
    """
    original_len = len(raw_context)

    # Convert token budget to char budget (rough: 4 chars/token)
    max_chars = context_budget * 4 if context_budget > 0 else COMPRESS_THRESHOLD * 2

    # Short context — passthrough
    if original_len <= COMPRESS_THRESHOLD:
        return CompressedInput(
            original_length=original_len,
            compressed_length=original_len,
            num_segments=1,
            strategy="passthrough",
            content=raw_context,
        )

    # ── Segment-then-Concat (VibeVoice pattern) ──
    segments = segment_context(raw_context, segment_size)

    if strategy == "auto":
        # Try extract first, fall back to truncate
        compressed_segments = [_extract_segment(seg) for seg in segments]
        merged = "\n\n---\n\n".join(compressed_segments)

        if len(merged) <= max_chars:
            return CompressedInput(
                original_length=original_len,
                compressed_length=len(merged),
                num_segments=len(segments),
                strategy="segment_extract",
                content=merged,
                metadata={"segments": len(segments)},
            )
        strategy = "segment_truncate"

    if strategy == "segment_extract":
        compressed_segments = [_extract_segment(seg) for seg in segments]
        merged = "\n\n---\n\n".join(compressed_segments)
        # Hard truncate if still over budget
        if len(merged) > max_chars:
            merged = _budget_truncate(merged, max_chars)
        return CompressedInput(
            original_length=original_len,
            compressed_length=len(merged),
            num_segments=len(segments),
            strategy="segment_extract",
            content=merged,
            metadata={"segments": len(segments)},
        )

    # segment_truncate: keep head + tail of each segment
    truncated_segments = []
    per_segment_budget = max(500, max_chars // max(len(segments), 1))

    for seg in segments:
        if len(seg.text) <= per_segment_budget:
            truncated_segments.append(seg.text)
        else:
            head = seg.text[:per_segment_budget // 2]
            tail = seg.text[-(per_segment_budget // 3):]
            gap = len(seg.text) - len(head) - len(tail)
            truncated_segments.append(
                f"{head}\n[... {gap} chars ...]\n{tail}"
            )

    merged = "\n\n---\n\n".join(truncated_segments)
    if len(merged) > max_chars:
        merged = _budget_truncate(merged, max_chars)

    return CompressedInput(
        original_length=original_len,
        compressed_length=len(merged),
        num_segments=len(segments),
        strategy="segment_truncate",
        content=merged,
        metadata={"segments": len(segments)},
    )


def _budget_truncate(text: str, max_chars: int) -> str:
    """Hard truncate respecting the budget, keeping head and tail."""
    if len(text) <= max_chars:
        return text
    head_budget = int(max_chars * 0.5)
    tail_budget = int(max_chars * 0.3)
    gap = len(text) - head_budget - tail_budget
    head = text[:head_budget]
    tail = text[-tail_budget:]
    return f"{head}\n\n[... {gap} chars compressed ...]\n\n{tail}"
