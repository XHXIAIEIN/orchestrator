"""
Agent-as-Tool composition primitive — R57 steal from Microsoft Agent Framework.

MAF's key insight: any agent function can be surfaced as a tool definition,
enabling recursive composition without full dispatch overhead.

``agent_as_tool`` wraps an async callable so it can be included in a tool list
passed to the Claude Agent SDK. The wrapper:
  - Accepts the agent function's kwargs as a JSON-serialisable dict
  - Invokes the agent async
  - Returns a string result (Claude tools must return str)

Usage:
    from src.middleware.composition import agent_as_tool

    researcher = agent_as_tool(
        run_research_agent,
        name="research",
        description="Run a research sub-agent on a given topic.",
    )
    # researcher is now a Claude tool definition dict that can be passed to query()
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)


def agent_as_tool(
    agent_fn: Callable[..., Awaitable[Any]],
    name: str,
    description: str,
    input_schema: dict | None = None,
) -> dict:
    """Wrap an agent async function as a Claude tool definition.

    Parameters
    ----------
    agent_fn:
        An async callable ``async def fn(**kwargs) -> Any``.
    name:
        Tool name (snake_case, no spaces, ≤64 chars).
    description:
        Human-readable description used by the LLM to decide when to call this tool.
    input_schema:
        Optional JSON Schema object describing the input. If omitted, defaults to
        an open ``{"type": "object"}`` schema that accepts any kwargs.

    Returns
    -------
    dict
        A tool definition dict compatible with the Claude Agent SDK tool list.
        Contains the standard ``name``, ``description``, ``input_schema`` keys
        plus an extra ``_handler`` key holding the actual callable (stripped
        before sending to the API; used internally by the pipeline).
    """
    if input_schema is None:
        input_schema = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    @functools.wraps(agent_fn)
    async def _wrapped(**kwargs: Any) -> str:
        log.debug("[agent_as_tool:%s] invoking with %s", name, list(kwargs.keys()))
        try:
            result = await agent_fn(**kwargs)
            return str(result) if result is not None else ""
        except Exception as exc:
            log.warning("[agent_as_tool:%s] error: %s", name, exc)
            return f"error: {exc}"

    return {
        "name": name,
        "description": description,
        "input_schema": input_schema,
        # Internal: handler callable used by MiddlewarePipeline.execute_function
        # when routing tool invocations through the FUNCTION layer.
        # The Claude Agent SDK ignores unknown keys when building API requests.
        "_handler": _wrapped,
    }


def extract_handler(tool_def: dict) -> Callable[..., Awaitable[str]] | None:
    """Return the internal handler from a tool definition, if present."""
    return tool_def.get("_handler")


def strip_internal_keys(tool_def: dict) -> dict:
    """Return a copy of tool_def without internal keys (safe to send to the API)."""
    return {k: v for k, v in tool_def.items() if not k.startswith("_")}
