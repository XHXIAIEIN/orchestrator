# src/core/mcp_health.py
"""MCP Server Health Check — track and verify MCP server availability.

Source: entrix hooks/hooks.json (Round 15)

Problem: MCP servers (Chrome DevTools, Context7, Playwright, etc.) are
external processes that can crash, hang, or become unreachable. Without
health tracking, the agent blindly retries dead servers, wasting tokens
and time on doomed tool calls.

Solution: Maintain a health registry of known MCP servers. Before each
MCP tool call, check the server's health status. After failures, mark
as unhealthy with exponential backoff before retry.

Integration points:
    - PreToolUse hook: check health before MCP tool calls
    - PostToolUse hook: update health on success/failure
    - health.py: report MCP status in system health check
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

log = logging.getLogger(__name__)

# Health states
HEALTHY = "healthy"
DEGRADED = "degraded"       # 1-2 recent failures
UNHEALTHY = "unhealthy"     # 3+ failures, backoff active

# Thresholds
DEGRADED_THRESHOLD = 1      # failures before degraded
UNHEALTHY_THRESHOLD = 3     # failures before unhealthy
RECOVERY_WINDOW_S = 300     # 5 min: auto-recover to degraded after this
MAX_BACKOFF_S = 120         # max backoff between retries


@dataclass
class MCPServerStatus:
    """Health status of a single MCP server."""
    name: str
    state: Literal["healthy", "degraded", "unhealthy"] = HEALTHY
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""
    backoff_until: float = 0.0  # don't retry before this time

    @property
    def is_available(self) -> bool:
        """Can this server accept requests right now?"""
        if self.state == HEALTHY:
            return True
        if self.state == UNHEALTHY:
            return time.time() >= self.backoff_until
        return True  # degraded: still available but warned


@dataclass
class MCPHealthRegistry:
    """Registry tracking health of all known MCP servers.

    Usage:
        registry = MCPHealthRegistry()

        # Before calling an MCP tool
        if registry.is_available("chrome-devtools"):
            result = call_mcp_tool(...)
            registry.record_success("chrome-devtools")
        else:
            reason = registry.get_status("chrome-devtools").last_error
            log.warning(f"MCP server unavailable: {reason}")

        # On failure
        registry.record_failure("chrome-devtools", "Connection refused")
    """

    servers: dict[str, MCPServerStatus] = field(default_factory=dict)

    def _ensure_server(self, name: str) -> MCPServerStatus:
        """Get or create server status entry."""
        if name not in self.servers:
            self.servers[name] = MCPServerStatus(name=name)
        return self.servers[name]

    def is_available(self, server_name: str) -> bool:
        """Check if server is available for requests."""
        status = self._ensure_server(server_name)

        # Auto-recovery: if enough time has passed since last failure,
        # allow a probe request
        if status.state == UNHEALTHY and time.time() >= status.backoff_until:
            log.info(f"mcp_health: {server_name} backoff expired, allowing probe")
            return True

        return status.is_available

    def record_success(self, server_name: str) -> None:
        """Record a successful MCP tool call."""
        status = self._ensure_server(server_name)
        status.consecutive_failures = 0
        status.total_successes += 1
        status.last_success = time.time()

        if status.state != HEALTHY:
            log.info(f"mcp_health: {server_name} recovered → healthy")
            status.state = HEALTHY
            status.backoff_until = 0.0

    def record_failure(self, server_name: str, error: str = "") -> None:
        """Record a failed MCP tool call."""
        status = self._ensure_server(server_name)
        status.consecutive_failures += 1
        status.total_failures += 1
        status.last_failure = time.time()
        status.last_error = error[:200] if error else "unknown error"

        # State transitions
        if status.consecutive_failures >= UNHEALTHY_THRESHOLD:
            status.state = UNHEALTHY
            # Exponential backoff: 10s, 20s, 40s, 80s, 120s max
            backoff = min(
                10 * (2 ** (status.consecutive_failures - UNHEALTHY_THRESHOLD)),
                MAX_BACKOFF_S,
            )
            status.backoff_until = time.time() + backoff
            log.warning(
                f"mcp_health: {server_name} → unhealthy "
                f"({status.consecutive_failures} failures, "
                f"backoff {backoff}s): {status.last_error}"
            )
        elif status.consecutive_failures >= DEGRADED_THRESHOLD:
            status.state = DEGRADED
            log.info(
                f"mcp_health: {server_name} → degraded "
                f"({status.consecutive_failures} failures): {status.last_error}"
            )

    def get_status(self, server_name: str) -> MCPServerStatus:
        """Get current status of a server."""
        return self._ensure_server(server_name)

    def get_all_statuses(self) -> list[MCPServerStatus]:
        """Get statuses of all known servers."""
        return list(self.servers.values())

    def get_summary(self) -> dict:
        """Get a summary dict suitable for health check reports."""
        if not self.servers:
            return {"status": "no_servers", "servers": []}

        unhealthy = [s for s in self.servers.values() if s.state == UNHEALTHY]
        degraded = [s for s in self.servers.values() if s.state == DEGRADED]

        overall = "pass"
        if degraded:
            overall = "warn"
        if unhealthy:
            overall = "fail"

        return {
            "status": overall,
            "total": len(self.servers),
            "healthy": len(self.servers) - len(unhealthy) - len(degraded),
            "degraded": len(degraded),
            "unhealthy": len(unhealthy),
            "servers": [
                {
                    "name": s.name,
                    "state": s.state,
                    "failures": s.consecutive_failures,
                    "last_error": s.last_error,
                }
                for s in self.servers.values()
                if s.state != HEALTHY
            ],
        }

    def extract_server_name(self, tool_name: str) -> str | None:
        """Extract MCP server name from a tool name.

        MCP tool names follow the pattern: mcp__<server>__<tool>
        Returns the server name, or None if not an MCP tool.
        """
        if not tool_name.startswith("mcp__"):
            return None
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return parts[1]
        return None


# Singleton registry (shared across the session)
_registry: MCPHealthRegistry | None = None


def get_registry() -> MCPHealthRegistry:
    """Get the global MCP health registry."""
    global _registry
    if _registry is None:
        _registry = MCPHealthRegistry()
    return _registry
