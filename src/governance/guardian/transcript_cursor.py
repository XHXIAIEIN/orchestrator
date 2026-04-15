"""Guardian Transcript Cursor — incremental review for guardian sub-agents.

Source: R61 Codex CLI (codex-rs/core/src/guardian/prompt.rs)

When a guardian retries a review, it should NOT re-transmit the entire
conversation. Instead, track the last position read via a cursor, and
on retry, only send entries after that cursor — unless compaction/rollback
invalidated the cursor (fall back to full).

Constants from Codex:
  GUARDIAN_REVIEW_TIMEOUT = 90s
  GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS = 10_000
  GUARDIAN_MAX_TOOL_TRANSCRIPT_TOKENS = 10_000
  GUARDIAN_RECENT_ENTRY_LIMIT = 40
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# ── Constants ─────────────────────────────────────────────────────────────

GUARDIAN_REVIEW_TIMEOUT = 90          # seconds
GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS = 10_000
GUARDIAN_MAX_TOOL_TRANSCRIPT_TOKENS = 10_000
GUARDIAN_RECENT_ENTRY_LIMIT = 40


# ── Enums ─────────────────────────────────────────────────────────────────

class PromptMode(Enum):
    """Whether to send full history or only the delta since last cursor."""
    FULL = "full"
    DELTA = "delta"


class ReviewOutcome(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


# ── Core types ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardianTranscriptCursor:
    """Opaque cursor tracking how far the guardian has read.

    history_version: incremented on compaction/rollback; mismatch → full re-send.
    entry_count: number of entries already transmitted in that version.
    """
    history_version: int
    entry_count: int

    def is_valid_for(self, current_version: int) -> bool:
        """True when the cursor can be used for delta mode."""
        return self.history_version == current_version


@dataclass(frozen=True)
class GuardianReviewResult:
    """Result returned after a guardian review pass."""
    outcome: ReviewOutcome
    reason: str
    cursor: GuardianTranscriptCursor
    duration_ms: int


# ── Prompt helpers ────────────────────────────────────────────────────────

def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Rough token truncation: assume ~4 chars per token."""
    char_limit = max_tokens * 4
    if len(text) <= char_limit:
        return text
    return text[-char_limit:]


def _format_entry(entry: Any, index: int) -> str:
    """Render a single transcript entry as readable text."""
    if isinstance(entry, dict):
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        tool_calls = entry.get("tool_calls", [])
        if tool_calls:
            tc_summary = ", ".join(
                tc.get("function", {}).get("name", tc.get("name", "?"))
                for tc in tool_calls
            )
            return f"[{index}] {role}: <tool_calls: {tc_summary}>"
        if isinstance(content, list):
            text_parts = [
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = " ".join(text_parts)
        return f"[{index}] {role}: {str(content)[:500]}"
    return f"[{index}] {str(entry)[:500]}"


def build_guardian_prompt(
    entries: list[Any],
    mode: PromptMode,
    cursor: Optional[GuardianTranscriptCursor],
    max_tokens: int = GUARDIAN_MAX_MESSAGE_TRANSCRIPT_TOKENS,
    history_version: int = 0,
) -> tuple[str, GuardianTranscriptCursor]:
    """Build the guardian review prompt, returning (prompt_text, new_cursor).

    Delta mode: if cursor matches current history_version, only transmit
    entries after cursor.entry_count.  Otherwise falls back to FULL.

    Full mode: only transmits the last GUARDIAN_RECENT_ENTRY_LIMIT entries.
    """
    use_delta = (
        mode is PromptMode.DELTA
        and cursor is not None
        and cursor.is_valid_for(history_version)
        and cursor.entry_count < len(entries)
    )

    if use_delta:
        slice_start = cursor.entry_count
        visible = entries[slice_start:]
        preamble = (
            f"[DELTA REVIEW — entries {slice_start}..{len(entries) - 1} shown "
            f"(version {history_version})]\n"
        )
    else:
        # Full mode: cap to recent entry limit
        if len(entries) > GUARDIAN_RECENT_ENTRY_LIMIT:
            omitted = len(entries) - GUARDIAN_RECENT_ENTRY_LIMIT
            visible = entries[-GUARDIAN_RECENT_ENTRY_LIMIT:]
            preamble = (
                f"[FULL REVIEW — showing last {GUARDIAN_RECENT_ENTRY_LIMIT} of "
                f"{len(entries)} entries ({omitted} omitted)]\n"
            )
        else:
            visible = entries
            preamble = f"[FULL REVIEW — {len(entries)} entries]\n"

    body_lines: list[str] = []
    for i, entry in enumerate(visible):
        real_index = (len(entries) - len(visible)) + i
        body_lines.append(_format_entry(entry, real_index))

    body = "\n".join(body_lines)
    body = _truncate_to_tokens(body, max_tokens)

    prompt = (
        "You are a guardian reviewing the following conversation transcript.\n"
        "Decide whether the agent's actions are safe and within policy.\n\n"
        + preamble
        + body
        + "\n\nRespond with APPROVED or REJECTED and a brief reason."
    )

    new_cursor = GuardianTranscriptCursor(
        history_version=history_version,
        entry_count=len(entries),
    )
    return prompt, new_cursor


# ── Message formatters ─────────────────────────────────────────────────────

def format_rejection_message(reason: str) -> str:
    """Format a guardian rejection response.

    Includes the Codex 'must not attempt workaround' language.
    """
    return (
        f"REJECTED: {reason}\n\n"
        "The agent must not attempt a workaround or proceed with the flagged "
        "action. The operation has been halted. If you believe this is a false "
        "positive, escalate to a human reviewer."
    )


def format_timeout_message() -> str:
    """Format a guardian timeout response.

    Includes the Codex 'may retry once' language.
    """
    return (
        "TIMEOUT: The guardian review did not complete within "
        f"{GUARDIAN_REVIEW_TIMEOUT}s. The agent may retry once. "
        "If the second attempt also times out, the operation will be blocked."
    )


# ── High-level runner (synchronous stub) ──────────────────────────────────

def run_guardian_review(
    entries: list[Any],
    reviewer_fn: Any,                       # callable(prompt: str) -> str
    mode: PromptMode = PromptMode.FULL,
    cursor: Optional[GuardianTranscriptCursor] = None,
    history_version: int = 0,
) -> GuardianReviewResult:
    """Run one guardian review pass and return the result.

    reviewer_fn: synchronous callable that accepts a prompt string and
    returns the reviewer's raw response (e.g. "APPROVED: looks fine").
    """
    start_ms = int(time.monotonic() * 1000)
    prompt, new_cursor = build_guardian_prompt(
        entries, mode, cursor,
        history_version=history_version,
    )

    try:
        raw = reviewer_fn(prompt)
    except TimeoutError:
        return GuardianReviewResult(
            outcome=ReviewOutcome.TIMEOUT,
            reason=format_timeout_message(),
            cursor=new_cursor,
            duration_ms=int(time.monotonic() * 1000) - start_ms,
        )

    upper = raw.strip().upper()
    if upper.startswith("APPROVED"):
        outcome = ReviewOutcome.APPROVED
        reason = raw.strip()
    elif upper.startswith("REJECTED"):
        outcome = ReviewOutcome.REJECTED
        reason = format_rejection_message(raw.strip())
    else:
        # Treat ambiguous response as rejection (fail-safe)
        outcome = ReviewOutcome.REJECTED
        reason = format_rejection_message(f"Ambiguous reviewer response: {raw[:200]}")

    return GuardianReviewResult(
        outcome=outcome,
        reason=reason,
        cursor=new_cursor,
        duration_ms=int(time.monotonic() * 1000) - start_ms,
    )
