"""
Browser CDP — CDPClient 和 TabLease。
从 browser_runtime.py 拆分出来。
"""
import json
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class TabLease:
    tab_id: str
    purpose: str           # "read" | "interact"
    department: str
    ttl_s: int = 300
    _created_at: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self._created_at) > self.ttl_s


class CDPClient:
    """同步 CDP 客户端 — 通过 WebSocket 发送 CDP 命令并等待响应。"""

    def __init__(self, ws_url: str, timeout: float = 30):
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws = None
        self._msg_id = 0

    def connect(self):
        """建立 WebSocket 连接。"""
        from websockets.sync.client import connect as ws_connect
        self._ws = ws_connect(self._ws_url, close_timeout=5)
        return self

    def close(self):
        """关闭连接。"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, method: str, params: dict = None) -> dict:
        """发送 CDP 命令，等待匹配 id 的响应（跳过事件消息）。"""
        if not self._ws:
            raise RuntimeError("CDPClient not connected")
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(msg))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            except TimeoutError:
                break
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error'].get('message', data['error'])}")
                return data.get("result", {})
            # else: it's an event, skip it
        raise TimeoutError(f"CDP timeout waiting for response to {method}")
