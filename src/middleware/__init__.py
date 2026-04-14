"""
src.middleware — Three-layer async middleware pipeline (R57).

Layers:
    AGENT    — wraps entire agent.run()
    FUNCTION — wraps each tool invocation
    CHAT     — wraps each LLM call

Quick start:
    from src.middleware import MiddlewarePipeline, MiddlewareLayer
    from src.middleware.builtins import logging_middleware, gate_middleware, token_budget_middleware

    pipeline = MiddlewarePipeline()
    pipeline.use(MiddlewareLayer.AGENT, logging_middleware)
    pipeline.use(MiddlewareLayer.FUNCTION, gate_middleware)
    pipeline.use(MiddlewareLayer.CHAT, token_budget_middleware)

    result = await pipeline.execute_function("bash", {"command": "ls"}, bash_handler)
"""
from src.middleware.pipeline import (
    MiddlewareLayer,
    MiddlewareContext,
    MiddlewareTermination,
    MiddlewarePipeline,
    MiddlewareFn,
)

__all__ = [
    "MiddlewareLayer",
    "MiddlewareContext",
    "MiddlewareTermination",
    "MiddlewarePipeline",
    "MiddlewareFn",
]
