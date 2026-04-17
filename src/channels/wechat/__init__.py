"""Shim — wechat adapter moved to orchestrator_channels.wechat."""
from orchestrator_channels.wechat import WeChatChannel, load_credentials

__all__ = ["WeChatChannel", "load_credentials"]
