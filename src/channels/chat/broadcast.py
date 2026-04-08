"""
Multi-Agent Broadcast — @agent syntax for parallel agent dispatch.

Stolen from: WeClaw messaging/handler.go broadcastToAgents() (R45d)

Syntax:
    @cc @cx hello world     → parallel dispatch to claude + codex
    @claude fix this bug    → single agent dispatch
    @all what time is it    → broadcast to all discovered agents

Parses @ prefixes, dispatches via SessionPool in parallel,
returns labeled responses: [claude] ... / [codex] ...
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from src.channels.agent_bridge import AgentResponse
from src.channels.agent_discovery import get_discovered_agents
from src.channels.session_pool import get_session_pool

log = logging.getLogger(__name__)

# Agent name aliases (short → canonical name)
AGENT_ALIASES: dict[str, str] = {
    "cc": "claude",
    "claude": "claude",
    "cx": "codex",
    "codex": "codex",
    "gm": "gemini",
    "gemini": "gemini",
    "ai": "aider",
    "aider": "aider",
}

# Pattern: one or more @agent prefixes followed by the message
_BROADCAST_PATTERN = re.compile(
    r"^((?:@\w+\s+)+)(.+)$",
    re.DOTALL,
)


def parse_broadcast(text: str) -> Optional[tuple[list[str], str]]:
    """Parse @agent prefixes from message text.

    Returns:
        (agent_names, message) if broadcast syntax detected, else None.

    Examples:
        "@cc hello"           → (["claude"], "hello")
        "@cc @cx fix this"    → (["claude", "codex"], "fix this")
        "@all status"         → (["all"], "status")
        "normal message"      → None
    """
    match = _BROADCAST_PATTERN.match(text.strip())
    if not match:
        return None

    prefix_str = match.group(1)
    message = match.group(2).strip()

    # Extract @names
    raw_names = re.findall(r"@(\w+)", prefix_str)
    if not raw_names:
        return None

    # Resolve aliases
    agents = []
    for name in raw_names:
        canonical = AGENT_ALIASES.get(name.lower(), name.lower())
        if canonical not in agents:
            agents.append(canonical)

    return agents, message


async def broadcast_to_agents(
    user_id: str,
    agent_names: list[str],
    message: str,
    system_prompt: str = "",
) -> list[AgentResponse]:
    """Dispatch message to multiple agents in parallel.

    Stolen from WeClaw broadcastToAgents(): goroutine per agent,
    first-come-first-served response ordering.

    Args:
        user_id: Chat/user identifier for session pooling.
        agent_names: List of agent names (or ["all"] for broadcast).
        message: The actual message content.
        system_prompt: Optional system prompt.

    Returns:
        List of AgentResponse, one per agent (including errors).
    """
    pool = get_session_pool()
    discovered = get_discovered_agents()

    # Resolve "all" to all discovered agents
    if "all" in agent_names:
        agent_names = list(discovered.keys())

    # Filter to only discovered agents
    valid_agents = []
    missing = []
    for name in agent_names:
        if name in discovered:
            valid_agents.append(name)
        else:
            missing.append(name)

    if missing:
        log.warning("broadcast: unknown agents: %s", missing)

    if not valid_agents:
        return [AgentResponse(
            text="",
            agent_name="system",
            protocol=None,
            error=f"No known agents found. Requested: {agent_names}. "
                  f"Available: {list(discovered.keys())}",
        )]

    # Parallel dispatch
    async def _call(name: str) -> AgentResponse:
        try:
            return await pool.chat(
                user_id=user_id,
                agent_name=name,
                message=message,
                system_prompt=system_prompt,
                profile=discovered[name],
            )
        except Exception as e:
            log.warning("broadcast: %s failed: %s", name, e)
            return AgentResponse(
                text="", agent_name=name,
                protocol=None,
                error=str(e),
            )

    tasks = [_call(name) for name in valid_agents]
    responses = await asyncio.gather(*tasks)
    return list(responses)


def format_broadcast_responses(responses: list[AgentResponse]) -> str:
    """Format multi-agent responses with agent labels.

    Each response gets a [agent_name] prefix, separated by dividers.
    """
    if len(responses) == 1:
        r = responses[0]
        if r.ok:
            return f"**[{r.agent_name}]** ({r.protocol.value}, {r.elapsed_s:.1f}s)\n\n{r.text}"
        return f"**[{r.agent_name}]** Error: {r.error}"

    parts = []
    for r in responses:
        if r.ok:
            header = f"**[{r.agent_name}]** ({r.protocol.value}, {r.elapsed_s:.1f}s)"
            parts.append(f"{header}\n\n{r.text}")
        else:
            parts.append(f"**[{r.agent_name}]** Error: {r.error}")

    return "\n\n---\n\n".join(parts)
