"""DanglingToolCall Fix — patch interrupted tool call histories.

Source: R62 DeerFlow (DanglingToolCallMiddleware, position 3 in 14-middleware chain)

When conversation history contains an AIMessage with tool_calls but no
matching ToolMessage (e.g., agent interrupted mid-turn), LLMs will error.

This middleware scans the message list and inserts synthetic error
ToolMessages at the correct position (in-place after the AIMessage,
NOT appended at the end — critical for message ordering).

Uses wrap_model_call semantics (modifies request before LLM), not
before_model (which appends to state via reducer, breaking order).

Note: this operates at the pre-LLM layer.  For pre-replay session repair
(Anthropic tool_use/tool_result pairing), see session_repair.py instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# Synthetic content inserted for dangling tool calls
_INTERRUPTED_CONTENT = "[Tool call was interrupted and did not return a result.]"


# ── Report ────────────────────────────────────────────────────────────────

@dataclass
class PatchReport:
    """Summary of what patch_dangling_tool_calls found and fixed."""
    total_messages: int = 0
    dangling_found: int = 0
    patches_inserted: int = 0
    tool_call_ids_patched: list[str] = field(default_factory=list)

    @property
    def had_dangles(self) -> bool:
        return self.dangling_found > 0


# ── Core patch function ───────────────────────────────────────────────────

def patch_dangling_tool_calls(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], PatchReport]:
    """Scan messages and insert synthetic ToolMessages for dangling tool calls.

    A tool call is "dangling" when an AIMessage references it via tool_calls
    but no subsequent ToolMessage (tool_result) with that tool_call_id exists.

    Synthetic messages are inserted immediately after the AIMessage that
    contains the dangling call — NOT appended at the end.  This preserves
    correct message ordering for LLM consumption.

    Args:
        messages: the raw message list (list of dicts with 'role', 'content',
                  optional 'tool_calls').

    Returns:
        (patched_messages, report) where patched_messages is a new list
        (original is not mutated).
    """
    report = PatchReport(total_messages=len(messages))

    # Collect all tool_call_ids that already have a matching tool result
    resolved_ids: set[str] = set()
    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id:
                resolved_ids.add(tc_id)
        # Also handle Anthropic-style tool_result blocks inside user messages
        content = msg.get("content")
        if role == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    if tool_use_id:
                        resolved_ids.add(tool_use_id)

    # Build patched list, inserting synthetics right after each AIMessage
    # that has dangling tool_calls.
    patched: list[dict[str, Any]] = []

    for msg in messages:
        patched.append(msg)

        role = msg.get("role", "")
        # Both "assistant" (OpenAI) and "ai" (LangChain) can carry tool_calls
        if role not in ("assistant", "ai"):
            continue

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue

        synthetics: list[dict[str, Any]] = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id") or tc.get("tool_call_id", "")
                tc_name = (
                    tc.get("function", {}).get("name")
                    or tc.get("name", "unknown_tool")
                )
            else:
                # Unexpected shape — skip
                continue

            if tc_id and tc_id not in resolved_ids:
                report.dangling_found += 1
                synthetic = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": tc_name,
                    "content": _INTERRUPTED_CONTENT,
                    "status": "error",
                }
                synthetics.append(synthetic)
                resolved_ids.add(tc_id)   # prevent double-patching
                report.tool_call_ids_patched.append(tc_id)

        if synthetics:
            patched.extend(synthetics)
            report.patches_inserted += len(synthetics)

    return patched, report


# ── Middleware integration ─────────────────────────────────────────────────

def as_middleware(
    next_fn: Callable[[list[dict[str, Any]]], Any],
) -> Callable[[list[dict[str, Any]]], Any]:
    """Wrap a function so it automatically receives patched messages.

    Usage::

        @as_middleware
        def call_llm(messages):
            return llm.invoke(messages)

        result = call_llm(raw_messages)   # dangling calls auto-patched

    The wrapper patches messages before calling next_fn.  The PatchReport
    is discarded; callers that need it should call patch_dangling_tool_calls
    directly.
    """
    def wrapped(messages: list[dict[str, Any]]) -> Any:
        patched, _report = patch_dangling_tool_calls(messages)
        return next_fn(patched)

    wrapped.__name__ = getattr(next_fn, "__name__", "wrapped")
    wrapped.__doc__ = (
        "[DanglingToolFix] " + (next_fn.__doc__ or "")
    )
    return wrapped
