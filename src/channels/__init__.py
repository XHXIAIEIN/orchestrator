"""Channel 层 — 外部消息平台适配器。"""
from src.channels.base import Channel, ChannelMessage
from src.channels.registry import get_channel_registry, ChannelRegistry

__all__ = ["Channel", "ChannelMessage", "ChannelRegistry", "get_channel_registry"]
