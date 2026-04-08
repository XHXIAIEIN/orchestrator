"""
Session Pool — reuse agent sessions to preserve KV cache.

Stolen from: WeClaw ACP session reuse + MinLi KV Cache analysis (R45d)

Key insight: same-session continuous dialogue vs frequent new sessions = 3-5x
cost difference due to KV cache hits. This pool maps (user, agent) → bridge
instance, keeping the bridge (and its session state) alive across messages.

For ACP bridges, this means the agent process stays running.
For CLI bridges, this means --resume session IDs are preserved.
For HTTP bridges, this means conversation history is maintained client-side.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from src.channels.agent_bridge import AgentBridge, AgentResponse, create_bridge
from src.channels.agent_discovery import AgentProfile, get_discovered_agents

log = logging.getLogger(__name__)

# Session TTL — evict sessions idle for more than this many seconds
SESSION_TTL_S = 1800  # 30 minutes
MAX_SESSIONS = 50     # hard cap to prevent resource leak


@dataclass
class PoolEntry:
    """A pooled bridge session."""
    bridge: AgentBridge
    user_id: str
    agent_name: str
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    message_count: int = 0

    def touch(self) -> None:
        self.last_used = time.monotonic()
        self.message_count += 1

    @property
    def idle_s(self) -> float:
        return time.monotonic() - self.last_used


class SessionPool:
    """Pool of agent bridge sessions, keyed by (user_id, agent_name).

    Reuses existing bridges when the same user talks to the same agent,
    preserving session state and KV cache. Evicts idle sessions.
    """

    def __init__(self, ttl_s: int = SESSION_TTL_S, max_sessions: int = MAX_SESSIONS):
        self._pool: dict[str, PoolEntry] = {}
        self._ttl_s = ttl_s
        self._max_sessions = max_sessions

    @staticmethod
    def _key(user_id: str, agent_name: str) -> str:
        return f"{user_id}:{agent_name}"

    def _evict_stale(self) -> int:
        """Remove sessions idle longer than TTL."""
        now = time.monotonic()
        stale_keys = [
            k for k, v in self._pool.items()
            if now - v.last_used > self._ttl_s
        ]
        for k in stale_keys:
            entry = self._pool.pop(k)
            log.info(
                "session_pool: evicted %s (idle %.0fs, %d msgs)",
                k, entry.idle_s, entry.message_count,
            )
        return len(stale_keys)

    def _evict_lru(self) -> None:
        """Evict least-recently-used session if at capacity."""
        if len(self._pool) < self._max_sessions:
            return
        lru_key = min(self._pool, key=lambda k: self._pool[k].last_used)
        entry = self._pool.pop(lru_key)
        log.info(
            "session_pool: LRU evicted %s (%d msgs)",
            lru_key, entry.message_count,
        )

    def get_or_create(
        self,
        user_id: str,
        agent_name: str,
        profile: Optional[AgentProfile] = None,
    ) -> AgentBridge:
        """Get existing bridge or create a new one.

        If a pooled session exists for (user_id, agent_name) and it's not
        stale, reuse it. Otherwise create a fresh bridge.
        """
        self._evict_stale()

        key = self._key(user_id, agent_name)
        entry = self._pool.get(key)

        if entry:
            entry.touch()
            log.debug(
                "session_pool: reused %s (msg #%d)",
                key, entry.message_count,
            )
            return entry.bridge

        # Create new bridge
        if profile is None:
            agents = get_discovered_agents()
            profile = agents.get(agent_name)
            if not profile:
                raise ValueError(f"Unknown agent: {agent_name}")

        self._evict_lru()
        bridge = create_bridge(profile)
        self._pool[key] = PoolEntry(
            bridge=bridge,
            user_id=user_id,
            agent_name=agent_name,
        )
        log.info(
            "session_pool: created %s (%s via %s)",
            key, agent_name, bridge.protocol.value,
        )
        return bridge

    async def chat(
        self,
        user_id: str,
        agent_name: str,
        message: str,
        system_prompt: str = "",
        profile: Optional[AgentProfile] = None,
    ) -> AgentResponse:
        """Convenience: get-or-create bridge, then chat."""
        bridge = self.get_or_create(user_id, agent_name, profile)
        return await bridge.chat(message, system_prompt)

    async def reset(self, user_id: str, agent_name: str) -> bool:
        """Reset a specific session (e.g. on /new command)."""
        key = self._key(user_id, agent_name)
        entry = self._pool.pop(key, None)
        if entry:
            await entry.bridge.reset_session()
            await entry.bridge.close()
            log.info("session_pool: reset %s", key)
            return True
        return False

    async def reset_all(self, user_id: str) -> int:
        """Reset all sessions for a user."""
        prefix = f"{user_id}:"
        keys = [k for k in self._pool if k.startswith(prefix)]
        for k in keys:
            entry = self._pool.pop(k)
            await entry.bridge.reset_session()
            await entry.bridge.close()
        return len(keys)

    async def close_all(self) -> None:
        """Shut down all pooled sessions."""
        for entry in self._pool.values():
            await entry.bridge.close()
        self._pool.clear()
        log.info("session_pool: closed all sessions")

    def get_stats(self) -> dict:
        """Pool statistics for diagnostics."""
        return {
            "active_sessions": len(self._pool),
            "sessions": {
                k: {
                    "agent": v.agent_name,
                    "protocol": v.bridge.protocol.value,
                    "messages": v.message_count,
                    "idle_s": round(v.idle_s, 1),
                }
                for k, v in self._pool.items()
            },
        }


# ── Singleton ──

_pool: Optional[SessionPool] = None


def get_session_pool() -> SessionPool:
    """Get the global session pool instance."""
    global _pool
    if _pool is None:
        _pool = SessionPool()
    return _pool
