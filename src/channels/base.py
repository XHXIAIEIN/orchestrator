"""
Channel 抽象基类 — OpenClaw 式适配器模式。

每个消息平台实现一个 Channel 子类，上层只看到统一的 ChannelMessage。
出站：Event Bus → formatter → Channel.send()
入站：Channel.start() polling → parse → Event Bus.publish()
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ChannelMessage:
    """平台无关的消息对象。"""
    text: str                          # Markdown 格式正文
    event_type: str = ""               # 原始事件类型 e.g. "task.completed"
    priority: str = "NORMAL"           # CRITICAL / HIGH / NORMAL / LOW
    department: str = ""               # 来源部门
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Channel(ABC):
    """消息平台适配器基类。"""

    name: str = "base"
    enabled: bool = True

    @abstractmethod
    def send(self, message: ChannelMessage) -> bool:
        """推送一条消息。返回是否成功。"""

    def start(self):
        """启动入站监听（如 polling）。默认无操作。"""

    def stop(self):
        """停止监听。"""

    def __repr__(self):
        return f"<Channel:{self.name} enabled={self.enabled}>"
