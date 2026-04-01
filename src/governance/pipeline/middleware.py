"""
Governor Middleware Pipeline — composable cross-cutting concerns.

Source: DeerFlow 2.0 LoopDetection + SubagentLimit + MemoryUpdate middleware chain.

Each middleware wraps the next handler in the chain. Middleware can:
- Pre-process context before the core runs
- Post-process results after the core returns
- Short-circuit by returning early (without calling next())
- Catch and handle errors from inner middleware

Usage:
    from src.governance.pipeline.middleware import (
        MiddlewareContext, compose, loop_detection, token_counter,
    )

    pipeline = compose([loop_detection(), token_counter()])
    result = pipeline(ctx, core_handler)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


# ── Context ──────────────────────────────────────────────────────────────

@dataclass
class MiddlewareContext:
    """Shared state flowing through the middleware chain."""
    task_id: int | None = None
    task_spec: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    token_usage: dict = field(default_factory=lambda: {"input": 0, "output": 0})
    metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""


# ── Types ────────────────────────────────────────────────────────────────

# Middleware signature: (ctx, next_fn) -> ctx
# next_fn signature: (ctx) -> ctx
MiddlewareFn = Callable[[MiddlewareContext, Callable], MiddlewareContext]
CoreFn = Callable[[MiddlewareContext], MiddlewareContext]


# ── Compose ──────────────────────────────────────────────────────────────

def compose(middlewares: list[MiddlewareFn]) -> Callable[[MiddlewareContext, CoreFn], MiddlewareContext]:
    """Compose middleware list into a single callable.

    Outermost middleware is index 0 (runs first on enter, last on exit).
    """
    def run(ctx: MiddlewareContext, core: CoreFn) -> MiddlewareContext:
        def build_chain(index: int) -> Callable[[MiddlewareContext], MiddlewareContext]:
            if index >= len(middlewares):
                return core
            mw = middlewares[index]
            next_fn = build_chain(index + 1)
            return lambda c: mw(c, next_fn)
        return build_chain(0)(ctx)
    return run


# ── Built-in Middleware ──────────────────────────────────────────────────

def loop_detection(window_size: int = 20, warn_at: int = 3, stop_at: int = 5) -> MiddlewareFn:
    """Detect repetitive tool call patterns via sliding-window hash comparison.

    Source: DeerFlow LoopDetectionMiddleware.
    """
    ring: deque[str] = deque(maxlen=window_size)

    def middleware(ctx: MiddlewareContext, next_fn: Callable) -> MiddlewareContext:
        # Hash current tool calls
        if ctx.tool_calls:
            sorted_calls = sorted(
                [json.dumps(tc, sort_keys=True)[:200] for tc in ctx.tool_calls]
            )
            h = hashlib.md5("|".join(sorted_calls).encode()).hexdigest()[:12]
            ring.append(h)

            count = sum(1 for x in ring if x == h)
            if count >= stop_at:
                log.warning(f"loop_detection: STOP — pattern {h} repeated {count}×")
                ctx.aborted = True
                ctx.abort_reason = f"Loop detected: same tool pattern {count}× in last {window_size} calls"
                return ctx
            elif count >= warn_at:
                log.warning(f"loop_detection: WARN — pattern {h} repeated {count}×")
                ctx.metadata["loop_warning"] = f"Pattern repeated {count}×"

        return next_fn(ctx)

    return middleware


def token_counter() -> MiddlewareFn:
    """Track cumulative token usage across the pipeline."""
    totals = {"input": 0, "output": 0, "calls": 0}

    def middleware(ctx: MiddlewareContext, next_fn: Callable) -> MiddlewareContext:
        totals["calls"] += 1
        result = next_fn(ctx)
        totals["input"] += result.token_usage.get("input", 0)
        totals["output"] += result.token_usage.get("output", 0)
        result.metadata["cumulative_tokens"] = dict(totals)
        return result

    return middleware


def subagent_limit(max_concurrent: int = 3) -> MiddlewareFn:
    """Cap concurrent sub-agent tool calls, truncate excess.

    Source: DeerFlow SubagentLimitMiddleware.
    """
    def middleware(ctx: MiddlewareContext, next_fn: Callable) -> MiddlewareContext:
        agent_calls = [tc for tc in ctx.tool_calls if tc.get("name") == "Agent"]
        if len(agent_calls) > max_concurrent:
            log.warning(
                f"subagent_limit: {len(agent_calls)} agent calls, truncating to {max_concurrent}"
            )
            # Keep first N agent calls, preserve all non-agent calls
            kept = 0
            filtered = []
            for tc in ctx.tool_calls:
                if tc.get("name") == "Agent":
                    if kept < max_concurrent:
                        filtered.append(tc)
                        kept += 1
                else:
                    filtered.append(tc)
            ctx.tool_calls = filtered
            ctx.metadata["subagent_truncated"] = len(agent_calls) - max_concurrent

        return next_fn(ctx)

    return middleware


def error_recovery(max_retries: int = 2) -> MiddlewareFn:
    """Catch errors from inner middleware, retry or degrade gracefully."""
    def middleware(ctx: MiddlewareContext, next_fn: Callable) -> MiddlewareContext:
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return next_fn(ctx)
            except Exception as e:
                last_error = e
                log.warning(f"error_recovery: attempt {attempt + 1}/{max_retries + 1} failed: {e}")
                ctx.errors.append({"attempt": attempt, "error": str(e), "time": time.time()})
        # All retries exhausted
        ctx.aborted = True
        ctx.abort_reason = f"All {max_retries + 1} attempts failed. Last error: {last_error}"
        return ctx

    return middleware


def timing() -> MiddlewareFn:
    """Measure execution time of the inner pipeline."""
    def middleware(ctx: MiddlewareContext, next_fn: Callable) -> MiddlewareContext:
        start = time.monotonic()
        result = next_fn(ctx)
        elapsed = time.monotonic() - start
        result.metadata["execution_time_ms"] = round(elapsed * 1000, 1)
        return result

    return middleware
