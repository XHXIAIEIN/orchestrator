"""
Agent Auto-Discovery + Capability Probing.

Stolen from: WeClaw config/detect.go (R45d)
            DetectAndConfigure() + lookPath() + commandProbe()

Scans PATH for known agent binaries (claude, codex, gemini, etc.),
probes each for ACP capability (JSON-RPC over stdio), and populates
AgentProfile configs. Zero-config, works out of the box.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 3


class AgentProtocol(Enum):
    """Supported agent communication protocols, in priority order."""
    ACP = "acp"      # JSON-RPC 2.0 over stdio — fastest, session reuse
    CLI = "cli"      # Spawn per message — universal fallback
    HTTP = "http"    # OpenAI-compatible endpoint — remote agents


@dataclass
class AgentProfile:
    """Discovered agent with capabilities."""
    name: str                              # e.g. "claude", "codex", "gemini"
    binary_path: str                       # resolved absolute path
    protocols: list[AgentProtocol]         # supported protocols, priority order
    version: str = ""                      # --version output
    supports_resume: bool = False          # CLI --resume flag
    supports_dangerously_skip: bool = False  # --dangerously-skip-permissions
    http_endpoint: str = ""                # for HTTP protocol agents
    extra: dict = field(default_factory=dict)

    @property
    def best_protocol(self) -> AgentProtocol:
        """Highest-priority supported protocol."""
        return self.protocols[0] if self.protocols else AgentProtocol.CLI


# ── Known agent binaries and their detection heuristics ──

_KNOWN_AGENTS: dict[str, dict] = {
    "claude": {
        "binaries": ["claude", "claude.exe"],
        "version_flag": "--version",
        "acp_hint": "mcp",  # Claude supports ACP if it supports MCP
        "resume_flag": "--resume",
    },
    "codex": {
        "binaries": ["codex", "codex.exe"],
        "version_flag": "--version",
        "acp_hint": None,
        "resume_flag": None,
    },
    "gemini": {
        "binaries": ["gemini", "gemini.exe"],
        "version_flag": "--version",
        "acp_hint": None,
        "resume_flag": None,
    },
    "aider": {
        "binaries": ["aider", "aider.exe"],
        "version_flag": "--version",
        "acp_hint": None,
        "resume_flag": None,
    },
}


def _look_path(binary: str) -> Optional[str]:
    """Find binary in PATH, with login-shell fallback for version managers.

    Stolen from WeClaw lookPath(): first tries shutil.which(),
    then falls back to shell `which` for nvm/mise/asdf environments
    where binaries are only on interactive shell PATH.
    """
    # Fast path: standard PATH lookup
    found = shutil.which(binary)
    if found:
        return found

    # Login-shell fallback (Unix only — version managers like nvm/mise)
    if os.name != "nt":
        for shell_cmd in ["bash -lic", "zsh -lic"]:
            try:
                result = subprocess.run(
                    f"{shell_cmd} 'which {binary}'",
                    shell=True, capture_output=True, text=True,
                    timeout=PROBE_TIMEOUT_S,
                )
                path = result.stdout.strip()
                if path and os.path.isfile(path):
                    return path
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

    return None


def _probe_version(binary_path: str, version_flag: str) -> str:
    """Get version string from agent binary."""
    try:
        result = subprocess.run(
            [binary_path, version_flag],
            capture_output=True, text=True,
            timeout=PROBE_TIMEOUT_S,
        )
        return result.stdout.strip()[:100] or result.stderr.strip()[:100]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _probe_acp_support(binary_path: str) -> bool:
    """Test if agent binary supports ACP (JSON-RPC over stdio).

    Stolen from WeClaw commandProbe(): sends a JSON-RPC initialize
    request and checks for a valid response within timeout.
    """
    init_request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"capabilities": {}},
    }) + "\n"

    try:
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, _ = proc.communicate(input=init_request, timeout=PROBE_TIMEOUT_S)
        # Any JSON-RPC response means ACP is supported
        if stdout.strip():
            try:
                resp = json.loads(stdout.strip().split("\n")[0])
                return "jsonrpc" in resp
            except (json.JSONDecodeError, IndexError):
                pass
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        if proc:
            proc.kill()
            proc.wait()
    return False


def _probe_help_flags(binary_path: str) -> dict[str, bool]:
    """Check --help output for supported flags."""
    try:
        result = subprocess.run(
            [binary_path, "--help"],
            capture_output=True, text=True,
            timeout=PROBE_TIMEOUT_S,
        )
        help_text = (result.stdout + result.stderr).lower()
        return {
            "resume": "--resume" in help_text,
            "dangerously_skip": "--dangerously-skip-permissions" in help_text
                or "dangerously" in help_text,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"resume": False, "dangerously_skip": False}


def detect_agents(
    extra_binaries: Optional[dict[str, dict]] = None,
    http_endpoints: Optional[dict[str, str]] = None,
) -> dict[str, AgentProfile]:
    """Scan for available agent binaries and probe capabilities.

    Returns dict of agent_name → AgentProfile for all discovered agents.
    Zero-config: works by scanning PATH with known agent names.

    Args:
        extra_binaries: Additional agent definitions beyond built-in list.
        http_endpoints: name → URL for HTTP-based agents (e.g. {"openai": "http://localhost:8080"}).
    """
    agents: dict[str, AgentProfile] = {}
    all_agents = dict(_KNOWN_AGENTS)
    if extra_binaries:
        all_agents.update(extra_binaries)

    for name, spec in all_agents.items():
        for binary in spec.get("binaries", [name]):
            path = _look_path(binary)
            if not path:
                continue

            # Found binary — probe capabilities
            version = _probe_version(path, spec.get("version_flag", "--version"))
            help_flags = _probe_help_flags(path)

            protocols = [AgentProtocol.CLI]  # CLI always available

            # ACP probe (expensive — only if hinted)
            if spec.get("acp_hint"):
                if _probe_acp_support(path):
                    protocols.insert(0, AgentProtocol.ACP)

            agents[name] = AgentProfile(
                name=name,
                binary_path=path,
                protocols=protocols,
                version=version,
                supports_resume=help_flags.get("resume", False),
                supports_dangerously_skip=help_flags.get("dangerously_skip", False),
            )
            log.info(
                "agent_discovery: found %s at %s (protocols=%s, version=%s)",
                name, path, [p.value for p in protocols], version[:50],
            )
            break  # Found first binary for this agent, stop

    # HTTP endpoints (remote agents, user-configured)
    if http_endpoints:
        for name, url in http_endpoints.items():
            if name in agents:
                agents[name].protocols.append(AgentProtocol.HTTP)
                agents[name].http_endpoint = url
            else:
                agents[name] = AgentProfile(
                    name=name,
                    binary_path="",
                    protocols=[AgentProtocol.HTTP],
                    http_endpoint=url,
                )
            log.info("agent_discovery: registered HTTP agent %s → %s", name, url)

    log.info("agent_discovery: discovered %d agents: %s", len(agents), list(agents.keys()))
    return agents


# ── Singleton cache ──

_cached_agents: Optional[dict[str, AgentProfile]] = None


def get_discovered_agents(force_rescan: bool = False) -> dict[str, AgentProfile]:
    """Get cached agent discovery results. Rescans on first call or when forced."""
    global _cached_agents
    if _cached_agents is None or force_rescan:
        _cached_agents = detect_agents()
    return _cached_agents
