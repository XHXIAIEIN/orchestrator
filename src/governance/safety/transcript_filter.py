"""
Transcript Filter — strip assistant text from context to prevent self-injection.

Source: Claude Code YOLO Classifier (Round 28b)

Problem: When the model's own prior text is included in a safety classifier's context,
the model can inadvertently influence its own safety assessment.

Solution: Only pass user messages and tool results to safety-critical classifiers.
"""
from __future__ import annotations

import re


def filter_transcript_for_safety(messages: list[dict]) -> list[dict]:
    """Filter a conversation transcript to only user messages and tool results.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.

    Returns:
        Filtered list containing only user and tool messages.
    """
    safe_roles = {"user", "tool", "tool_result", "system"}
    return [m for m in messages if m.get("role", "") in safe_roles]


def strip_assistant_from_text(text: str) -> str:
    """Remove assistant-attributed text blocks from a flat transcript string."""
    text = re.sub(r'<assistant>.*?</assistant>', '[assistant text removed]', text, flags=re.DOTALL)
    text = re.sub(
        r'(?m)^Assistant:.*?(?=^(?:User|Tool|System):|\Z)',
        '[assistant text removed]\n',
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    return text
