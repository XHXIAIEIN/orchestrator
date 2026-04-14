"""
Built-in middleware implementations for the three-layer async pipeline.

Three middlewares covering the most common cross-cutting concerns:
  logging_middleware    — emit a structured log line for every invocation (all layers)
  gate_middleware       — run verify_gate checks before FUNCTION-layer tool calls
  token_budget_middleware — track cumulative token usage at the CHAT layer
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from src.middleware.pipeline import MiddlewareContext, MiddlewareLayer

log = logging.getLogger(__name__)


# ── Logging ───────────────────────────────────────────────────────────────────

async def logging_middleware(ctx: MiddlewareContext, call_next: Callable) -> Any:
    """Emit a structured log line for every middleware invocation.

    Captures wall-clock elapsed time and annotates ctx.metadata with it.
    Applies to all three layers — AGENT, FUNCTION, CHAT.
    """
    label = ctx.layer.value
    if ctx.layer == MiddlewareLayer.FUNCTION:
        label = f"function:{ctx.metadata.get('tool_name', '?')}"

    start = time.monotonic()
    try:
        result = await call_next(ctx)
        elapsed = time.monotonic() - start
        ctx.metadata["elapsed_ms"] = round(elapsed * 1000, 1)
        log.info("[middleware:%s] %.0fms ok", label, elapsed * 1000)
        return result
    except Exception as exc:
        elapsed = time.monotonic() - start
        log.warning("[middleware:%s] %.0fms error: %s", label, elapsed * 1000, exc)
        raise


# ── Gate enforcement ──────────────────────────────────────────────────────────

# Tools that should NOT be intercepted by the gate check (internal plumbing).
_PASSTHROUGH_TOOLS: frozenset[str] = frozenset({
    "list_tasks", "get_task", "read_context", "get_summary",
})


async def gate_middleware(ctx: MiddlewareContext, call_next: Callable) -> Any:
    """Enforce gate rules before FUNCTION-layer tool invocations.

    At other layers (AGENT / CHAT) this middleware is a transparent pass-through.

    Gate logic:
    - Skip passthrough tools (read-only / safe introspection)
    - If ctx.metadata contains "gate_denied": True, raise MiddlewareTermination
      (allows upstream logic to pre-deny without reaching the handler)
    - Otherwise pass through; handlers are responsible for their own safety
    """
    if ctx.layer != MiddlewareLayer.FUNCTION:
        return await call_next(ctx)

    tool_name = ctx.metadata.get("tool_name", "")

    if tool_name in _PASSTHROUGH_TOOLS:
        log.debug("[gate_middleware] passthrough: %s", tool_name)
        return await call_next(ctx)

    # Allow upstream code to signal a pre-deny via metadata
    if ctx.metadata.get("gate_denied"):
        from src.middleware.pipeline import MiddlewareTermination
        reason = ctx.metadata.get("gate_reason", "gate denied")
        log.warning("[gate_middleware] DENIED tool=%s reason=%s", tool_name, reason)
        raise MiddlewareTermination(result={"error": "gate_denied", "reason": reason})

    log.debug("[gate_middleware] allowed: %s", tool_name)
    return await call_next(ctx)


# ── Token budget tracking ─────────────────────────────────────────────────────

# Module-level accumulator — intentionally shared across invocations so that
# cumulative usage builds up over the lifetime of the process.
_token_totals: dict[str, int] = {"input": 0, "output": 0, "calls": 0}


async def token_budget_middleware(ctx: MiddlewareContext, call_next: Callable) -> Any:
    """Track cumulative token usage at the CHAT layer.

    At other layers this middleware is transparent.

    After the handler returns, reads ``ctx.metadata["usage"]`` (a dict with
    "input_tokens" / "output_tokens" keys, same shape as the Anthropic API
    ``usage`` object) and folds those into the running totals.

    Annotates ctx.metadata with:
        cumulative_tokens  — {"input": N, "output": N, "calls": N}
    """
    result = await call_next(ctx)

    if ctx.layer == MiddlewareLayer.CHAT:
        usage = ctx.metadata.get("usage", {})
        _token_totals["input"] += usage.get("input_tokens", 0)
        _token_totals["output"] += usage.get("output_tokens", 0)
        _token_totals["calls"] += 1
        ctx.metadata["cumulative_tokens"] = dict(_token_totals)
        log.debug(
            "[token_budget] call=%d total_in=%d total_out=%d",
            _token_totals["calls"],
            _token_totals["input"],
            _token_totals["output"],
        )

    return result


def get_token_totals() -> dict[str, int]:
    """Return a snapshot of the accumulated token counts."""
    return dict(_token_totals)


def reset_token_totals() -> None:
    """Reset accumulators — useful for tests."""
    _token_totals["input"] = 0
    _token_totals["output"] = 0
    _token_totals["calls"] = 0
