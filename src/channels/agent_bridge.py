"""
Agent Bridge — three-layer protocol bridge for multi-agent communication.

Stolen from: WeClaw agent/agent.go (R45d)
            ACP (JSON-RPC stdio) > CLI (spawn per msg) > HTTP (OpenAI-compat)

Provides a unified AgentBridge ABC with three implementations.
Auto-selects the best protocol per agent based on discovery results.
Priority cascade: ACP (fastest, session reuse) → CLI (universal) → HTTP (remote).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from src.channels.agent_discovery import (
    AgentProfile, AgentProtocol, get_discovered_agents,
)

log = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Unified response from any agent bridge."""
    text: str
    agent_name: str
    protocol: AgentProtocol
    session_id: str = ""
    elapsed_s: float = 0.0
    error: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error


class AgentBridge(ABC):
    """Abstract agent communication bridge.

    Three implementations: ACPBridge (JSON-RPC stdio), CLIBridge (spawn per msg),
    HTTPBridge (OpenAI-compatible). Each speaks a different wire protocol but
    exposes the same chat() / reset_session() / set_cwd() interface.
    """

    def __init__(self, profile: AgentProfile):
        self.profile = profile
        self._cwd: str = os.getcwd()

    @property
    @abstractmethod
    def protocol(self) -> AgentProtocol:
        ...

    @abstractmethod
    async def chat(self, message: str, system_prompt: str = "") -> AgentResponse:
        """Send a message and get a response."""
        ...

    async def reset_session(self) -> None:
        """Reset conversation state. Default: no-op."""

    def set_cwd(self, path: str) -> None:
        """Set working directory for agent commands."""
        self._cwd = path

    async def health_check(self) -> bool:
        """Check if bridge is operational. Default: True."""
        return True

    async def close(self) -> None:
        """Clean up resources. Default: no-op."""


class ACPBridge(AgentBridge):
    """ACP — Agent Communication Protocol (JSON-RPC 2.0 over stdio).

    Keeps a long-running agent process. Messages go through stdin/stdout
    as JSON-RPC calls. Session state (and KV cache) is preserved across
    messages — this is the fastest and cheapest protocol.

    Stolen from WeClaw acp_agent.go: session/thread reuse, stderr capture.
    """

    protocol = AgentProtocol.ACP

    def __init__(self, profile: AgentProfile):
        super().__init__(profile)
        self._process: Optional[subprocess.Popen] = None
        self._request_id: int = 0
        self._session_id: str = ""
        self._lock = asyncio.Lock()

    async def _ensure_process(self) -> subprocess.Popen:
        """Start agent process if not running."""
        if self._process and self._process.poll() is None:
            return self._process

        cmd = [self.profile.binary_path]
        if self.profile.supports_dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        env = dict(os.environ)
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self._cwd,
            env=env,
        )
        log.info("acp_bridge: started %s (pid=%d)", self.profile.name, self._process.pid)
        return self._process

    async def chat(self, message: str, system_prompt: str = "") -> AgentResponse:
        t0 = time.monotonic()
        async with self._lock:
            try:
                proc = await self._ensure_process()
                self._request_id += 1

                request = {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "chat",
                    "params": {
                        "message": message,
                        "cwd": self._cwd,
                    },
                }
                if system_prompt:
                    request["params"]["system_prompt"] = system_prompt
                if self._session_id:
                    request["params"]["session_id"] = self._session_id

                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()

                # Read response line (blocking — run in executor)
                loop = asyncio.get_event_loop()
                line = await loop.run_in_executor(None, proc.stdout.readline)

                if not line.strip():
                    return AgentResponse(
                        text="", agent_name=self.profile.name,
                        protocol=AgentProtocol.ACP,
                        error="empty response from ACP agent",
                        elapsed_s=time.monotonic() - t0,
                    )

                resp = json.loads(line.strip())
                result = resp.get("result", {})
                if isinstance(result, str):
                    text = result
                else:
                    text = result.get("text", result.get("content", str(result)))
                    self._session_id = result.get("session_id", self._session_id)

                return AgentResponse(
                    text=text,
                    agent_name=self.profile.name,
                    protocol=AgentProtocol.ACP,
                    session_id=self._session_id,
                    elapsed_s=time.monotonic() - t0,
                    raw=resp,
                )

            except Exception as e:
                log.warning("acp_bridge: chat failed for %s: %s", self.profile.name, e)
                return AgentResponse(
                    text="", agent_name=self.profile.name,
                    protocol=AgentProtocol.ACP,
                    error=str(e),
                    elapsed_s=time.monotonic() - t0,
                )

    async def reset_session(self) -> None:
        self._session_id = ""
        if self._process and self._process.poll() is None:
            self._process.kill()
            self._process.wait()
            self._process = None

    async def health_check(self) -> bool:
        return self._process is not None and self._process.poll() is None

    async def close(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None


class CLIBridge(AgentBridge):
    """CLI — spawn agent process per message.

    Universal fallback. Works with any agent that accepts a prompt as argument.
    Supports --resume for session continuity where available.

    Stolen from WeClaw cli_agent.go: stream-json parsing, session resume.
    """

    protocol = AgentProtocol.CLI

    def __init__(self, profile: AgentProfile):
        super().__init__(profile)
        self._session_id: str = ""

    async def chat(self, message: str, system_prompt: str = "") -> AgentResponse:
        t0 = time.monotonic()
        cmd = [self.profile.binary_path]

        # Add flags based on capabilities
        if self.profile.supports_dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        if self._session_id and self.profile.supports_resume:
            cmd.extend(["--resume", self._session_id])

        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # Prompt as the last positional argument
        cmd.extend(["--print", message])

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True, text=True,
                    cwd=self._cwd,
                    timeout=300,
                    env=dict(os.environ),
                ),
            )

            text = result.stdout.strip()
            # Try to extract session_id from output for future --resume
            for line in result.stderr.split("\n"):
                if "session" in line.lower() and "id" in line.lower():
                    # Heuristic: look for session ID patterns
                    parts = line.split(":")
                    if len(parts) >= 2:
                        candidate = parts[-1].strip()
                        if len(candidate) > 8:
                            self._session_id = candidate
                            break

            if result.returncode != 0 and not text:
                return AgentResponse(
                    text="", agent_name=self.profile.name,
                    protocol=AgentProtocol.CLI,
                    error=f"exit code {result.returncode}: {result.stderr[:200]}",
                    elapsed_s=time.monotonic() - t0,
                )

            return AgentResponse(
                text=text,
                agent_name=self.profile.name,
                protocol=AgentProtocol.CLI,
                session_id=self._session_id,
                elapsed_s=time.monotonic() - t0,
            )

        except subprocess.TimeoutExpired:
            return AgentResponse(
                text="", agent_name=self.profile.name,
                protocol=AgentProtocol.CLI,
                error="timeout (300s)",
                elapsed_s=time.monotonic() - t0,
            )
        except Exception as e:
            return AgentResponse(
                text="", agent_name=self.profile.name,
                protocol=AgentProtocol.CLI,
                error=str(e),
                elapsed_s=time.monotonic() - t0,
            )

    async def reset_session(self) -> None:
        self._session_id = ""


class HTTPBridge(AgentBridge):
    """HTTP — OpenAI-compatible chat/completions endpoint.

    For remote agents or self-hosted models. Maintains conversation
    history client-side (server is stateless).

    Stolen from WeClaw http_agent.go: OpenAI-compat, client-side history.
    """

    protocol = AgentProtocol.HTTP

    def __init__(self, profile: AgentProfile):
        super().__init__(profile)
        self._history: list[dict] = []
        self._endpoint = profile.http_endpoint.rstrip("/")

    async def chat(self, message: str, system_prompt: str = "") -> AgentResponse:
        import urllib.request
        import urllib.error

        t0 = time.monotonic()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self._history)
        messages.append({"role": "user", "content": message})

        body = json.dumps({
            "model": self.profile.name,
            "messages": messages,
            "stream": False,
        }).encode()

        url = f"{self._endpoint}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            loop = asyncio.get_event_loop()

            def _do_request():
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read().decode())

            data = await loop.run_in_executor(None, _do_request)
            text = data["choices"][0]["message"]["content"]

            # Update client-side history
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": text})

            return AgentResponse(
                text=text,
                agent_name=self.profile.name,
                protocol=AgentProtocol.HTTP,
                elapsed_s=time.monotonic() - t0,
                raw=data,
            )

        except Exception as e:
            return AgentResponse(
                text="", agent_name=self.profile.name,
                protocol=AgentProtocol.HTTP,
                error=str(e),
                elapsed_s=time.monotonic() - t0,
            )

    async def reset_session(self) -> None:
        self._history.clear()

    async def health_check(self) -> bool:
        import urllib.request
        try:
            url = f"{self._endpoint}/v1/models"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False


# ── Bridge Factory ──

_BRIDGE_MAP: dict[AgentProtocol, type[AgentBridge]] = {
    AgentProtocol.ACP: ACPBridge,
    AgentProtocol.CLI: CLIBridge,
    AgentProtocol.HTTP: HTTPBridge,
}


def create_bridge(
    profile: AgentProfile,
    preferred_protocol: Optional[AgentProtocol] = None,
) -> AgentBridge:
    """Create the best available bridge for an agent.

    Uses preferred_protocol if specified and supported, otherwise
    falls back through the agent's protocol priority list.
    """
    if preferred_protocol and preferred_protocol in profile.protocols:
        cls = _BRIDGE_MAP[preferred_protocol]
        return cls(profile)

    # Use best available protocol
    protocol = profile.best_protocol
    cls = _BRIDGE_MAP[protocol]
    return cls(profile)


def create_bridges_for_all(
    agents: Optional[dict[str, AgentProfile]] = None,
) -> dict[str, AgentBridge]:
    """Create bridges for all discovered agents."""
    if agents is None:
        agents = get_discovered_agents()
    return {name: create_bridge(profile) for name, profile in agents.items()}
