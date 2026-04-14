"""
Three-Layer Async Middleware Pipeline — R57 steal from Microsoft Agent Framework.

MAF uses an onion-model middleware pipeline with three distinct interception layers:
  AGENT    — wraps an entire agent.run() invocation
  FUNCTION — wraps each tool/function call
  CHAT     — wraps each LLM API call

Execution order (onion / A1→A2→R1→R2→Handler→R2→R1→A2→A1):
  - Middlewares run outermost-first on the way in
  - Innermost first (LIFO) on the way back out
  - Any middleware can raise MiddlewareTermination to short-circuit the chain

Compatible with the existing sync pipeline at src.governance.pipeline.middleware —
that layer stays unchanged; this module sits above it as an async decorator layer.

Usage:
    from src.middleware.pipeline import MiddlewarePipeline, MiddlewareLayer

    pipeline = MiddlewarePipeline()
    pipeline.use(MiddlewareLayer.AGENT, logging_middleware)
    pipeline.use(MiddlewareLayer.FUNCTION, gate_middleware)

    result = await pipeline.execute_function("bash", {"command": "ls"}, bash_handler)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)


# ── Layer enum ───────────────────────────────────────────────────────────────

class MiddlewareLayer(str, Enum):
    AGENT = "agent"       # wraps entire agent.run()
    FUNCTION = "function"  # wraps each tool/function invocation
    CHAT = "chat"          # wraps each LLM API call


# ── Short-circuit exception ──────────────────────────────────────────────────

class MiddlewareTermination(Exception):
    """Raise inside a middleware to skip the remainder of the chain.

    The pipeline catches this and returns ``result`` immediately.
    """
    def __init__(self, result: Any = None) -> None:
        super().__init__()
        self.result = result


# ── Context ──────────────────────────────────────────────────────────────────

@dataclass
class MiddlewareContext:
    """Shared state flowing through one middleware chain execution."""
    layer: MiddlewareLayer
    input_data: Any
    metadata: dict = field(default_factory=dict)
    result: Any = None


# ── Type aliases ─────────────────────────────────────────────────────────────

# async def my_mw(ctx: MiddlewareContext, call_next: Callable) -> Any: ...
MiddlewareFn = Callable[["MiddlewareContext", Callable[..., Awaitable[Any]]], Awaitable[Any]]


# ── Pipeline engine ──────────────────────────────────────────────────────────

class MiddlewarePipeline:
    """Three-layer async middleware pipeline with onion execution model.

    Each layer maintains an independent list of middlewares. Calling
    ``execute_agent`` / ``execute_function`` / ``execute_chat`` runs the
    corresponding list as a nested async call chain, then invokes the
    provided ``handler`` at the centre.
    """

    def __init__(self) -> None:
        self._middlewares: dict[MiddlewareLayer, list[MiddlewareFn]] = {
            MiddlewareLayer.AGENT: [],
            MiddlewareLayer.FUNCTION: [],
            MiddlewareLayer.CHAT: [],
        }

    # ── Registration ─────────────────────────────────────────────────────────

    def use(self, layer: MiddlewareLayer, middleware: MiddlewareFn) -> "MiddlewarePipeline":
        """Register a middleware for the given layer.

        Middlewares run in registration order (first registered = outermost).
        Returns self for chaining.
        """
        self._middlewares[layer].append(middleware)
        return self

    # ── Execution helpers ─────────────────────────────────────────────────────

    async def execute_agent(self, input_data: Any, handler: Callable[..., Awaitable[Any]]) -> Any:
        """Execute through the AGENT middleware chain, then call handler(input_data)."""
        ctx = MiddlewareContext(layer=MiddlewareLayer.AGENT, input_data=input_data)
        return await self._run(ctx, MiddlewareLayer.AGENT, handler)

    async def execute_function(
        self,
        tool_name: str,
        args: dict,
        handler: Callable[..., Awaitable[Any]],
    ) -> Any:
        """Execute through the FUNCTION middleware chain, then call handler(tool_name, args)."""
        ctx = MiddlewareContext(
            layer=MiddlewareLayer.FUNCTION,
            input_data={"tool_name": tool_name, "args": args},
            metadata={"tool_name": tool_name},
        )
        return await self._run(ctx, MiddlewareLayer.FUNCTION, handler)

    async def execute_chat(
        self,
        messages: list,
        handler: Callable[..., Awaitable[Any]],
        **handler_kwargs: Any,
    ) -> Any:
        """Execute through the CHAT middleware chain, then call handler(messages, **handler_kwargs)."""
        ctx = MiddlewareContext(
            layer=MiddlewareLayer.CHAT,
            input_data=messages,
            metadata={"handler_kwargs": handler_kwargs},
        )
        return await self._run(ctx, MiddlewareLayer.CHAT, handler)

    # ── Core chain builder ────────────────────────────────────────────────────

    async def _run(
        self,
        ctx: MiddlewareContext,
        layer: MiddlewareLayer,
        handler: Callable[..., Awaitable[Any]],
    ) -> Any:
        """Build and execute the onion chain for a given layer.

        Chain structure (N middlewares registered):
            mw[0]( mw[1]( ... mw[N-1]( handler ) ... ) )
        """
        middlewares = self._middlewares[layer]

        async def build_next(index: int) -> Callable[[MiddlewareContext], Awaitable[Any]]:
            """Return the call_next callable for middleware at position index."""
            async def call_next(c: MiddlewareContext) -> Any:
                if index >= len(middlewares):
                    # Reached the centre — invoke the actual handler
                    return await _call_handler(c, handler)
                try:
                    next_fn = await build_next(index + 1)
                    return await middlewares[index](c, next_fn)
                except MiddlewareTermination as term:
                    return term.result
            return call_next

        try:
            entry = await build_next(0)
            return await entry(ctx)
        except MiddlewareTermination as term:
            return term.result


async def _call_handler(ctx: MiddlewareContext, handler: Callable[..., Awaitable[Any]]) -> Any:
    """Dispatch to the inner handler based on layer semantics."""
    layer = ctx.layer
    if layer == MiddlewareLayer.AGENT:
        return await handler(ctx.input_data)
    elif layer == MiddlewareLayer.FUNCTION:
        tool_name = ctx.input_data.get("tool_name", "")
        args = ctx.input_data.get("args", {})
        return await handler(tool_name, args)
    elif layer == MiddlewareLayer.CHAT:
        handler_kwargs = ctx.metadata.get("handler_kwargs", {})
        return await handler(ctx.input_data, **handler_kwargs)
    else:
        return await handler(ctx.input_data)
