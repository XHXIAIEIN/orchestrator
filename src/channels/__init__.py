"""Channel 层 — 外部消息平台适配器 + 多 Agent 桥接。"""
from src.channels.base import Channel, ChannelMessage
from src.channels.registry import get_channel_registry, ChannelRegistry
from src.channels.channel_router import ChannelRouter, ChannelRoute
from src.channels.agent_discovery import AgentProfile, AgentProtocol, detect_agents, get_discovered_agents
from src.channels.agent_bridge import AgentBridge, AgentResponse, create_bridge
from src.channels.session_pool import SessionPool, get_session_pool

__all__ = [
    "Channel",
    "ChannelMessage",
    "ChannelRegistry",
    "ChannelRoute",
    "ChannelRouter",
    "get_channel_registry",
    # Agent Bridge (R45d)
    "AgentBridge",
    "AgentProfile",
    "AgentProtocol",
    "AgentResponse",
    "SessionPool",
    "create_bridge",
    "detect_agents",
    "get_discovered_agents",
    "get_session_pool",
]
