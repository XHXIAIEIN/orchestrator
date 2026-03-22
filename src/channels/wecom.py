"""
企业微信 Channel — Webhook 推送适配器。

仅出站：ChannelMessage → POST webhook_url（Markdown 格式）
企业微信 Webhook 不支持接收消息，无入站能力。
"""
import json
import logging
import urllib.request
import urllib.error

from src.channels.base import Channel, ChannelMessage

log = logging.getLogger(__name__)


class WeComChannel(Channel):
    """企业微信 Webhook 适配器。"""

    name = "wecom"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.enabled = True

    def send(self, message: ChannelMessage) -> bool:
        """推送消息到企业微信群。"""
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {
                "content": message.text,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            if result.get("errcode") != 0:
                log.warning(f"wecom: send failed: {result}")
                return False
            return True
        except Exception as e:
            log.warning(f"wecom: send failed: {e}")
            return False
