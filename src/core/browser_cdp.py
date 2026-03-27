"""
Browser CDP — CDPClient 和 TabLease。
从 browser_runtime.py 拆分出来。
"""
import base64
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
    """同步 CDP 客户端 — 通过 WebSocket 发送 CDP 命令并等待响应。

    从 Carbonyl 偷师：支持事件订阅模式（subscribe），
    用于 screencastFrame 等持续推帧场景。
    """

    def __init__(self, ws_url: str, timeout: float = 30):
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws = None
        self._msg_id = 0
        self._event_buffer: list[dict] = []

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
        """发送 CDP 命令，等待匹配 id 的响应（事件存入缓冲区）。"""
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
            if "method" in data:
                self._event_buffer.append(data)
        raise TimeoutError(f"CDP timeout waiting for response to {method}")

    def recv_event(self, timeout: float = 1.0) -> dict | None:
        """接收一个 CDP 事件。先消费缓冲区，再从 WebSocket 读取。

        从 Carbonyl 偷师的「渲染管线劫持」思路：
        不再是请求-响应模式截图，而是订阅事件流持续接收帧。
        """
        if self._event_buffer:
            return self._event_buffer.pop(0)
        if not self._ws:
            return None
        try:
            raw = self._ws.recv(timeout=timeout)
            data = json.loads(raw)
            if "method" in data:
                return data
            return None
        except (TimeoutError, Exception):
            return None

    def drain_events(self, method_filter: str = "", max_events: int = 100) -> list[dict]:
        """排空事件缓冲区，可选按 method 过滤。"""
        results = []
        # 先消费已缓冲的
        remaining = []
        for ev in self._event_buffer:
            if not method_filter or ev.get("method") == method_filter:
                results.append(ev)
            else:
                remaining.append(ev)
        self._event_buffer = remaining
        # 再尝试非阻塞读取更多
        while len(results) < max_events and self._ws:
            try:
                raw = self._ws.recv(timeout=0.05)
                data = json.loads(raw)
                if "method" in data:
                    if not method_filter or data["method"] == method_filter:
                        results.append(data)
                    else:
                        self._event_buffer.append(data)
            except (TimeoutError, Exception):
                break
        return results

    # ── Screenshot & Screencast ─────────────────────────────────

    def take_screenshot(self, format: str = "png", quality: int = 80) -> bytes:
        """Page.captureScreenshot — 请求-响应式截图，返回原始图片字节。"""
        params = {"format": format}
        if format in ("jpeg", "webp"):
            params["quality"] = quality
        result = self.send("Page.captureScreenshot", params)
        return base64.b64decode(result["data"])

    def enable_screencast(
        self,
        format: str = "jpeg",
        quality: int = 50,
        max_width: int = 1280,
        max_height: int = 720,
    ) -> None:
        """Page.startScreencast — 开启推帧模式。"""
        self.send("Page.startScreencast", {
            "format": format,
            "quality": quality,
            "maxWidth": max_width,
            "maxHeight": max_height,
        })

    def disable_screencast(self) -> None:
        """Page.stopScreencast — 关闭推帧。"""
        self.send("Page.stopScreencast")

    def recv_screencast_frame(self, timeout: float = 5.0) -> tuple[bytes, dict]:
        """等待下一帧 screencastFrameReceived，解码并 ack。

        返回 (image_bytes, metadata_dict)。
        metadata 包含 offsetTop, pageScaleFactor, deviceWidth, deviceHeight,
        scrollOffsetX, scrollOffsetY, timestamp。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            event = self.recv_event(timeout=remaining)
            if event and event.get("method") == "Page.screencastFrame":
                params = event["params"]
                image_bytes = base64.b64decode(params["data"])
                metadata = params["metadata"]
                session_id = params["sessionId"]
                # Ack 是必须的，否则 Chrome 停止推帧
                self.send("Page.screencastFrameAck", {"sessionId": session_id})
                return image_bytes, metadata
        raise TimeoutError("Timed out waiting for screencast frame")
