"""Connection-Based Agent Composition — capability discovery via graph edges (R40-P7).

Agent capabilities are discovered from graph edges, not static config.
Supports: tool edges, memory edges, skill edges, task delegation edges.
Nested discovery: child agent's tools are transitively visible to parent.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class EdgeKind(Enum):
    TOOL = "input-tools"
    MEMORY = "input-memory"
    SKILL = "input-skill"
    MAIN = "input-main"
    TASK = "input-task"


@dataclass
class AgentNode:
    node_id: str
    agent_type: str  # "ai", "tool", "memory", "skill"
    config: dict = field(default_factory=dict)


@dataclass
class CapabilityEdge:
    source: str
    target: str
    kind: EdgeKind


class CompositionGraph:
    """Directed graph for agent capability composition."""

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}
        self._edges: list[CapabilityEdge] = []

    def add_node(self, node: AgentNode) -> None:
        self._nodes[node.node_id] = node

    def add_edge(self, edge: CapabilityEdge) -> None:
        self._edges.append(edge)

    def discover_by_kind(self, node_id: str, kind: EdgeKind) -> list[str]:
        return [e.target for e in self._edges if e.source == node_id and e.kind == kind]

    def discover_tools(self, node_id: str, recursive: bool = False) -> list[str]:
        direct = self.discover_by_kind(node_id, EdgeKind.TOOL)
        if not recursive:
            return direct
        visited = set()
        result = []
        def _walk(nid: str) -> None:
            for target in self.discover_by_kind(nid, EdgeKind.TOOL):
                if target not in visited:
                    visited.add(target)
                    result.append(target)
                    target_node = self._nodes.get(target)
                    if target_node and target_node.agent_type == "ai":
                        _walk(target)
        _walk(node_id)
        return result

    def generate_delegate_tools(self, node_id: str) -> list[dict]:
        tools = []
        for target_id in self.discover_by_kind(node_id, EdgeKind.TOOL):
            target_node = self._nodes.get(target_id)
            if target_node and target_node.agent_type == "ai":
                tools.append({
                    "name": f"delegate_to_{target_id}",
                    "description": f"Delegate a task to {target_id} agent",
                    "target_node_id": target_id,
                    "config": target_node.config,
                })
        return tools
