import pytest
from src.governance.agent_composition import (
    AgentNode, CapabilityEdge, CompositionGraph, EdgeKind
)

def test_discover_tools_from_edges():
    graph = CompositionGraph()
    graph.add_node(AgentNode(node_id="lead", agent_type="ai"))
    graph.add_node(AgentNode(node_id="coder", agent_type="ai"))
    graph.add_node(AgentNode(node_id="browser", agent_type="tool"))
    graph.add_edge(CapabilityEdge(source="lead", target="coder", kind=EdgeKind.TOOL))
    graph.add_edge(CapabilityEdge(source="lead", target="browser", kind=EdgeKind.TOOL))
    tools = graph.discover_tools("lead")
    assert set(tools) == {"coder", "browser"}

def test_discover_memory_edges():
    graph = CompositionGraph()
    graph.add_node(AgentNode(node_id="agent", agent_type="ai"))
    graph.add_node(AgentNode(node_id="mem", agent_type="memory"))
    graph.add_edge(CapabilityEdge(source="agent", target="mem", kind=EdgeKind.MEMORY))
    memories = graph.discover_by_kind("agent", EdgeKind.MEMORY)
    assert memories == ["mem"]

def test_nested_tool_discovery():
    graph = CompositionGraph()
    graph.add_node(AgentNode(node_id="lead", agent_type="ai"))
    graph.add_node(AgentNode(node_id="sub", agent_type="ai"))
    graph.add_node(AgentNode(node_id="tool", agent_type="tool"))
    graph.add_edge(CapabilityEdge(source="lead", target="sub", kind=EdgeKind.TOOL))
    graph.add_edge(CapabilityEdge(source="sub", target="tool", kind=EdgeKind.TOOL))
    tools = graph.discover_tools("lead", recursive=True)
    assert set(tools) == {"sub", "tool"}

def test_generate_delegate_tools():
    graph = CompositionGraph()
    graph.add_node(AgentNode(node_id="lead", agent_type="ai"))
    graph.add_node(AgentNode(node_id="coder", agent_type="ai"))
    graph.add_edge(CapabilityEdge(source="lead", target="coder", kind=EdgeKind.TOOL))
    delegates = graph.generate_delegate_tools("lead")
    assert len(delegates) == 1
    assert delegates[0]["name"] == "delegate_to_coder"
