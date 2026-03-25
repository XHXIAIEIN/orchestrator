# BrowserTools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add CDP WebSocket client and browser automation tools (navigate, screenshot, snapshot, click, fill, read_page) that departments can call.

**Architecture:** `browser_tools.py` provides sync tool functions. Internally uses a `CDPClient` class in `browser_runtime.py` that manages WebSocket connection to Chrome via the `websockets` library. Tools acquire a tab from the pool, do work, release.

**Tech Stack:** Python 3.12, websockets, CDP protocol, pytest

---

## File Structure

```
src/core/browser_runtime.py    ← Add CDPClient (WebSocket + CDP commands)
src/core/browser_tools.py      ← New: tool functions for Agent use
tests/core/test_browser_tools.py ← New: unit tests (mocked CDP)
```

---

### Task 1: CDPClient — WebSocket CDP communication

**Files:**
- Modify: `src/core/browser_runtime.py`
- Create: `tests/core/test_cdp_client.py`

Add a `CDPClient` class to browser_runtime.py:

```python
class CDPClient:
    """同步 CDP 客户端 — 通过 WebSocket 发送 CDP 命令。"""

    def __init__(self, ws_url: str, timeout: float = 30):
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws = None
        self._msg_id = 0

    def connect(self):
        """建立 WebSocket 连接。"""
        import websockets.sync.client
        self._ws = websockets.sync.client.connect(self._ws_url, close_timeout=5)

    def close(self):
        if self._ws:
            self._ws.close()
            self._ws = None

    def send(self, method: str, params: dict = None) -> dict:
        """发送 CDP 命令，等待响应。"""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(msg))
        # 等待匹配 id 的响应（跳过事件）
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=self._timeout)
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get("result", {})
        raise TimeoutError(f"CDP timeout waiting for response to {method}")
```

Also add to BrowserRuntime:
```python
def new_cdp_client(self, page_ws_url: str) -> CDPClient:
    """创建连接到指定页面的 CDP 客户端。"""
    client = CDPClient(page_ws_url, timeout=30)
    client.connect()
    return client

def open_page(self, url: str = "about:blank") -> dict:
    """通过 HTTP API 创建新页面，返回 page info dict。"""
    # PUT http://127.0.0.1:{port}/json/new?{url}
    req_url = f"http://127.0.0.1:{self._debug_port}/json/new?{url}"
    with urllib.request.urlopen(req_url, timeout=10) as resp:
        return json.loads(resp.read())

def close_page(self, page_id: str):
    """关闭指定页面。"""
    req_url = f"http://127.0.0.1:{self._debug_port}/json/close/{page_id}"
    urllib.request.urlopen(req_url, timeout=5)

def list_pages(self) -> list[dict]:
    """列出所有页面。"""
    req_url = f"http://127.0.0.1:{self._debug_port}/json/list"
    with urllib.request.urlopen(req_url, timeout=5) as resp:
        return json.loads(resp.read())
```

Tests: mock websockets.sync.client.connect, verify send/recv flow, test CDP error handling.

---

### Task 2: BrowserTools — navigate, screenshot, snapshot

**Files:**
- Create: `src/core/browser_tools.py`
- Create: `tests/core/test_browser_tools.py`

```python
# src/core/browser_tools.py
"""
Browser Tools — Agent 可调用的浏览器工具。
所有函数同步，内部通过 BrowserRuntime 管理 tab 和 CDP。
"""

def browser_navigate(runtime, url: str) -> dict:
    """打开 URL，返回 {title, url, status}。"""
    page_info = runtime.open_page(url)
    page_ws = page_info["webSocketDebuggerUrl"]
    cdp = runtime.new_cdp_client(page_ws)
    try:
        # Page.enable + wait for loadEventFired would be ideal,
        # but simpler: navigate then poll for title
        cdp.send("Page.enable")
        cdp.send("Page.navigate", {"url": url})
        time.sleep(2)  # 简单等待
        # 获取 title
        result = cdp.send("Runtime.evaluate", {"expression": "document.title"})
        title = result.get("result", {}).get("value", "")
        return {"title": title, "url": url, "page_id": page_info["id"]}
    finally:
        cdp.close()

def browser_screenshot(runtime, page_id: str = None) -> str:
    """截图，返回 base64 PNG。"""
    # 找到 page 的 ws url
    pages = runtime.list_pages()
    target = pages[0] if not page_id else next((p for p in pages if p["id"] == page_id), pages[0])
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        result = cdp.send("Page.captureScreenshot", {"format": "png"})
        return result.get("data", "")
    finally:
        cdp.close()

def browser_snapshot(runtime, page_id: str = None) -> str:
    """获取页面 accessibility snapshot（文本表示）。"""
    pages = runtime.list_pages()
    target = pages[0] if not page_id else next((p for p in pages if p["id"] == page_id), pages[0])
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        cdp.send("Accessibility.enable")
        result = cdp.send("Accessibility.getFullAXTree")
        nodes = result.get("nodes", [])
        # 简化输出：提取 role + name
        lines = []
        for node in nodes[:100]:  # 限制节点数
            role = node.get("role", {}).get("value", "")
            name = node.get("name", {}).get("value", "")
            if name:
                lines.append(f"{role}: {name}")
        return "\n".join(lines)
    finally:
        cdp.close()

def browser_read_page(runtime, url: str) -> str:
    """打开页面 + 提取正文文本。"""
    page_info = runtime.open_page(url)
    cdp = runtime.new_cdp_client(page_info["webSocketDebuggerUrl"])
    try:
        cdp.send("Page.enable")
        cdp.send("Page.navigate", {"url": url})
        time.sleep(3)
        result = cdp.send("Runtime.evaluate", {
            "expression": "document.body.innerText"
        })
        text = result.get("result", {}).get("value", "")
        return text
    finally:
        cdp.close()
        try:
            runtime.close_page(page_info["id"])
        except Exception:
            pass
```

---

### Task 3: BrowserTools — click, fill

**Files:**
- Modify: `src/core/browser_tools.py`
- Modify: `tests/core/test_browser_tools.py`

```python
def browser_click(runtime, page_id: str, selector: str) -> dict:
    """点击页面元素。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        # 用 JS 点击
        result = cdp.send("Runtime.evaluate", {
            "expression": f"document.querySelector('{selector}')?.click(); 'clicked'"
        })
        return {"status": "ok", "result": result.get("result", {}).get("value")}
    finally:
        cdp.close()

def browser_fill(runtime, page_id: str, selector: str, text: str) -> dict:
    """填写输入框。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        # Focus + 设置 value + 触发 input 事件
        js = f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (!el) return 'not_found';
            el.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set || Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeSetter.call(el, {json.dumps(text)});
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'filled';
        }})()
        """
        result = cdp.send("Runtime.evaluate", {"expression": js})
        return {"status": "ok", "result": result.get("result", {}).get("value")}
    finally:
        cdp.close()
```
