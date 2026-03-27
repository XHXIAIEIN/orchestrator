"""Channel 层 — 外部消息平台适配器。"""
from src.channels.base import Channel, ChannelMessage
from src.channels.registry import get_channel_registry, ChannelRegistry
from src.channels.channel_router import ChannelRouter, ChannelRoute

__all__ = [
    "Channel",
    "ChannelMessage",
    "ChannelRegistry",
    "ChannelRoute",
    "ChannelRouter",
    "get_channel_registry",
]
