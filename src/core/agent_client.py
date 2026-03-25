"""Thin wrapper around claude_agent_sdk for single-shot prompt→text queries."""

import json
import logging
import os

import anyio
from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage, AssistantMessage,
)

from src.governance.context.prompts import find_git_bash
from src.core.llm_router import MODEL_SONNET

log = logging.getLogger(__name__)

DEFAULT_MODEL = MODEL_SONNET


async def _agent_query_async(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_turns: int = 1,
    cwd: str | None = None,
) -> str:
    """Send a prompt via Agent SDK, return the final text."""
    # Windows git bash hint
    agent_env: dict[str, str] = {}
    if os.name == "nt" and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
        bash_path = find_git_bash()
        if bash_path:
            agent_env["CLAUDE_CODE_GIT_BASH_PATH"] = bash_path

    text_parts: list[str] = []
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system_prompt or None,
            model=model,
            max_turns=max_turns,
            permission_mode="bypassPermissions",
            **({"cwd": cwd} if cwd else {}),
            **({"env": agent_env} if agent_env else {}),
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in (message.content or []):
                if getattr(block, "type", None) == "text":
                    text_parts.append(getattr(block, "text", ""))
        elif isinstance(message, ResultMessage):
            if message.is_error:
                error_msg = message.result or "unknown error"
                log.error("agent_query: SDK returned error: %s", error_msg[:500])
                raise RuntimeError(f"Agent SDK error: {error_msg[:500]}")
            if message.result:
                return message.result
    return "\n".join(text_parts)


def agent_query(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_turns: int = 1,
    cwd: str | None = None,
) -> str:
    """Synchronous wrapper — send prompt via Agent SDK, get text back."""
    async def _run():
        return await _agent_query_async(prompt, system_prompt, model, max_turns, cwd)
    return anyio.run(_run)


def agent_query_json(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_turns: int = 1,
    cwd: str | None = None,
) -> dict:
    """Send prompt, parse response as JSON. Handles markdown fences."""
    raw = agent_query(prompt, system_prompt, model, max_turns, cwd)

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl >= 0:
            text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as exc:
        log.error("agent_query_json: failed to parse JSON: %s\nRaw: %s", exc, raw[:500])
        raise RuntimeError(f"Failed to parse JSON from Agent SDK response: {exc}") from exc
