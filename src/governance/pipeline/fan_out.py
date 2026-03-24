"""
Fan-out Collector — 多路输出写入。

voice-ai 启发：run-log 同时写文件+DB+外部 APM，无 exporter 时 no-op。

当前 run_logger 已经是 DB-first + JSONL fallback，
Fan-out 在此基础上增加：
  1. Event Bus 通知（其他系统可以订阅 run.completed 事件）
  2. 可选的外部 webhook 推送
  3. 标准化的 export 接口
"""
import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


@dataclass
class FanOutTarget:
    """输出目标。"""
    name: str
    type: str          # "event_bus" | "webhook" | "file" | "db" | "channel"
    enabled: bool = True
    config: dict = field(default_factory=dict)


# 默认输出目标
DEFAULT_TARGETS = [
    FanOutTarget("db", "db", True),
    FanOutTarget("event_bus", "event_bus", True),
    FanOutTarget("jsonl_backup", "file", True, {"dir": "departments/{department}"}),
    FanOutTarget("channels", "channel", True),
]


class FanOutCollector:
    """多路输出收集器。"""

    def __init__(self, targets: list[FanOutTarget] = None):
        self.targets = targets or list(DEFAULT_TARGETS)

    def emit(self, event_type: str, data: dict, department: str = ""):
        """向所有启用的目标发射数据。"""
        for target in self.targets:
            if not target.enabled:
                continue

            try:
                if target.type == "event_bus":
                    self._emit_event_bus(event_type, data, department)
                elif target.type == "webhook":
                    self._emit_webhook(target, event_type, data)
                elif target.type == "file":
                    self._emit_file(target, event_type, data, department)
                elif target.type == "channel":
                    self._emit_channel(event_type, data, department)
                # db 由 run_logger 直接处理，这里不重复
            except Exception as e:
                log.warning(f"fan_out: target '{target.name}' failed: {e}")

    def _emit_event_bus(self, event_type: str, data: dict, department: str):
        """发送到事件总线。"""
        try:
            from src.core.event_bus import get_event_bus, Event, Priority

            priority = Priority.NORMAL
            if data.get("status") == "failed":
                priority = Priority.HIGH
            elif "gate_failed" in str(data.get("status", "")):
                priority = Priority.HIGH

            bus = get_event_bus()
            bus.publish(Event(
                event_type=event_type,
                payload=data,
                priority=priority,
                source=f"fan_out:{department}",
                coalesce_key=f"{event_type}:{data.get('task_id', '')}",
            ))
        except Exception as e:
            log.debug(f"fan_out: event_bus unavailable: {e}")

    def _emit_webhook(self, target: FanOutTarget, event_type: str, data: dict):
        """推送到外部 webhook。"""
        url = target.config.get("url", "")
        if not url:
            return

        payload = json.dumps({
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            from src.channels.config import WEBHOOK_TIMEOUT
            urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT)
        except urllib.error.URLError:
            pass  # webhook 不可达，静默失败

    def _emit_channel(self, event_type: str, data: dict, department: str):
        """推送到消息平台（Telegram、企业微信等）。"""
        try:
            from src.channels.registry import get_channel_registry
            registry = get_channel_registry()
            registry.broadcast_event(event_type, data, department)
        except Exception as e:
            log.debug(f"fan_out: channel unavailable: {e}")

    def _emit_file(self, target: FanOutTarget, event_type: str,
                    data: dict, department: str):
        """写入文件（JSONL 格式）。"""
        dir_template = target.config.get("dir", "tmp/fan-out")
        # Prevent writing to departments/ root when department is empty
        dir_path = _REPO_ROOT / dir_template.format(department=department or "_unrouted")
        dir_path.mkdir(parents=True, exist_ok=True)

        file_name = target.config.get("file", "fan-out.jsonl")
        file_path = dir_path / file_name

        entry = {
            "event_type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **data,
        }

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# ── 全局单例 ──
_collector: Optional[FanOutCollector] = None


def get_fan_out() -> FanOutCollector:
    global _collector
    if _collector is None:
        _collector = FanOutCollector()
    return _collector
