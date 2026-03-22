"""
Channel 注册表 — 管理所有消息平台的生命周期。

自动发现：根据环境变量判断启用哪些 channel。
零配置时静默不启用，zero-impact。
"""
import logging
import os
import threading
from typing import Optional

from src.channels.base import Channel, ChannelMessage
from src.channels.formatter import format_event

log = logging.getLogger(__name__)


class ChannelRegistry:
    """Channel 注册表 + 广播器。"""

    def __init__(self):
        self._channels: dict[str, Channel] = {}
        self._started = False
        self._lock = threading.Lock()

    def register(self, channel: Channel):
        """注册一个 channel。"""
        with self._lock:
            self._channels[channel.name] = channel
            log.info(f"channel: registered '{channel.name}' (enabled={channel.enabled})")

    def unregister(self, name: str):
        """移除一个 channel。"""
        with self._lock:
            if name in self._channels:
                del self._channels[name]

    def broadcast(self, message: ChannelMessage):
        """向所有启用的 channel 广播消息。"""
        for ch in self._channels.values():
            if not ch.enabled:
                continue
            try:
                ch.send(message)
            except Exception as e:
                log.warning(f"channel: broadcast to '{ch.name}' failed: {e}")

    def broadcast_event(self, event_type: str, data: dict, department: str = ""):
        """从原始事件数据广播（自动格式化）。"""
        message = format_event(event_type, data, department)
        self.broadcast(message)

    def start_all(self):
        """启动所有 channel 的入站监听。"""
        if self._started:
            return
        self._started = True
        for ch in self._channels.values():
            if ch.enabled:
                try:
                    ch.start()
                    log.info(f"channel: started '{ch.name}'")
                except Exception as e:
                    log.error(f"channel: failed to start '{ch.name}': {e}")

    def stop_all(self):
        """停止所有 channel。"""
        self._started = False
        for ch in self._channels.values():
            try:
                ch.stop()
            except Exception:
                pass

    def get_status(self) -> dict:
        """返回所有 channel 的状态。"""
        return {
            name: {
                "enabled": ch.enabled,
                "type": type(ch).__name__,
            }
            for name, ch in self._channels.items()
        }

    def auto_discover(self):
        """根据环境变量自动发现和注册 channel。"""
        # Telegram
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            try:
                from src.channels.telegram import TelegramChannel
                tg = TelegramChannel(
                    token=os.environ["TELEGRAM_BOT_TOKEN"],
                    chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
                    min_priority=os.environ.get("TELEGRAM_MIN_PRIORITY", "HIGH"),
                )
                self.register(tg)
            except Exception as e:
                log.error(f"channel: failed to init telegram: {e}")

        # 企业微信
        if os.environ.get("WECOM_WEBHOOK_URL"):
            try:
                from src.channels.wecom import WeComChannel
                wecom = WeComChannel(
                    webhook_url=os.environ["WECOM_WEBHOOK_URL"],
                )
                self.register(wecom)
            except Exception as e:
                log.error(f"channel: failed to init wecom: {e}")

        if not self._channels:
            log.debug("channel: no channels configured (set TELEGRAM_BOT_TOKEN or WECOM_WEBHOOK_URL)")


# ── 全局单例 ──
_registry: Optional[ChannelRegistry] = None


def get_channel_registry() -> ChannelRegistry:
    global _registry
    if _registry is None:
        _registry = ChannelRegistry()
        _registry.auto_discover()
    return _registry
