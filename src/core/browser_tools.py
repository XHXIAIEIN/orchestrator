"""
Browser Tools — Agent 可调用的浏览器工具函数。
所有函数同步。通过 BrowserRuntime 管理页面生命周期和 CDP 通信。

Guard 集成：每次操作后自动采集页面指纹并经过 ActionLoopDetector 检查。
警告信息附加在返回值的 "_guard_warnings" 字段中，调度层自行决定如何处理。
"""
import json
import logging
import time

from src.core.browser_guard import ActionLoopDetector, page_fingerprint

log = logging.getLogger(__name__)

# 模块级 guard 实例（跨调用追踪状态，随 scheduler 生命周期存在）
_loop_detector = ActionLoopDetector()


def get_loop_detector() -> ActionLoopDetector:
    """获取当前 guard 实例（供外部查看 stats 或 reset）。"""
    return _loop_detector


def browser_navigate(runtime, url: str) -> dict:
    """打开新 tab 并导航到 URL，返回 {title, url, page_id}。"""
    page_info = runtime.open_page("about:blank")
    page_id = page_info["id"]
    cdp = runtime.new_cdp_client(page_info["webSocketDebuggerUrl"])
    try:
        cdp.send("Page.enable")
        cdp.send("Page.navigate", {"url": url})
        # 等待页面加载（简单轮询 title）
        for _ in range(20):
            time.sleep(0.5)
            try:
                result = cdp.send("Runtime.evaluate", {"expression": "document.readyState"})
                state = result.get("result", {}).get("value", "")
                if state in ("complete", "interactive"):
                    break
            except Exception:
                pass
        # 获取 title
        result = cdp.send("Runtime.evaluate", {"expression": "document.title"})
        title = result.get("result", {}).get("value", "")
        ret = {"title": title, "url": url, "page_id": page_id}
        # Guard: 采集指纹 + 循环检测
        fp = page_fingerprint(runtime, page_id)
        warnings = _loop_detector.record("navigate", fingerprint=fp, url=url)
        if warnings:
            ret["_guard_warnings"] = warnings
        return ret
    finally:
        cdp.close()


def browser_screenshot(runtime, page_id: str) -> str:
    """对指定页面截图，返回 base64 PNG。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        raise ValueError(f"Page {page_id} not found")
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        result = cdp.send("Page.captureScreenshot", {"format": "png"})
        return result.get("data", "")
    finally:
        cdp.close()


def browser_snapshot(runtime, page_id: str) -> str:
    """获取页面 accessibility tree 的文本表示。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        raise ValueError(f"Page {page_id} not found")
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        # 用 JS 提取页面结构（比 Accessibility.getFullAXTree 更兼容）
        js = """
        (() => {
            const walk = (el, depth) => {
                if (!el || depth > 5) return [];
                let lines = [];
                const tag = el.tagName?.toLowerCase() || '';
                const role = el.getAttribute?.('role') || '';
                const label = el.getAttribute?.('aria-label') || el.textContent?.trim().substring(0, 80) || '';
                if (label && ['a','button','input','textarea','select','h1','h2','h3','h4','h5','h6','p','li','img'].includes(tag)) {
                    const type = el.type ? ` type="${el.type}"` : '';
                    const val = el.value ? ` value="${el.value.substring(0,50)}"` : '';
                    lines.push('  '.repeat(depth) + `${tag}${role ? '['+role+']' : ''}${type}: ${label}${val}`);
                }
                for (const child of (el.children || [])) {
                    lines.push(...walk(child, depth + 1));
                }
                return lines;
            };
            return walk(document.body, 0).join('\\n');
        })()
        """
        result = cdp.send("Runtime.evaluate", {"expression": js})
        return result.get("result", {}).get("value", "")
    finally:
        cdp.close()


def browser_read_page(runtime, url: str) -> str:
    """打开页面并提取正文文本，完成后关闭页面。"""
    page_info = runtime.open_page("about:blank")
    page_id = page_info["id"]
    cdp = runtime.new_cdp_client(page_info["webSocketDebuggerUrl"])
    try:
        cdp.send("Page.enable")
        cdp.send("Page.navigate", {"url": url})
        # 等待加载
        for _ in range(20):
            time.sleep(0.5)
            try:
                result = cdp.send("Runtime.evaluate", {"expression": "document.readyState"})
                if result.get("result", {}).get("value") in ("complete", "interactive"):
                    break
            except Exception:
                pass
        # 提取正文
        result = cdp.send("Runtime.evaluate", {"expression": "document.body?.innerText || ''"})
        text = result.get("result", {}).get("value", "")
        return text
    finally:
        cdp.close()
        try:
            runtime.close_page(page_id)
        except Exception:
            pass


def browser_click(runtime, page_id: str, selector: str) -> dict:
    """点击页面中匹配 selector 的元素。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        js = f"document.querySelector({json.dumps(selector)})?.click() ?? 'not_found'"
        result = cdp.send("Runtime.evaluate", {"expression": js})
        val = result.get("result", {}).get("value")
        if val == "not_found":
            return {"status": "error", "message": f"Element not found: {selector}"}
        ret = {"status": "ok"}
        # Guard: 采集指纹 + 循环检测
        fp = page_fingerprint(runtime, page_id)
        warnings = _loop_detector.record("click", fingerprint=fp, selector=selector)
        if warnings:
            ret["_guard_warnings"] = warnings
        return ret
    finally:
        cdp.close()


def browser_fill(runtime, page_id: str, selector: str, text: str) -> dict:
    """填写输入框。用 native setter 触发 React 等框架的事件。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        escaped_text = json.dumps(text)
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return 'not_found';
            el.focus();
            const proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(el, {escaped_text});
            else el.value = {escaped_text};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'filled';
        }})()
        """
        result = cdp.send("Runtime.evaluate", {"expression": js})
        val = result.get("result", {}).get("value")
        if val == "not_found":
            return {"status": "error", "message": f"Element not found: {selector}"}
        ret = {"status": "ok"}
        # Guard: 采集指纹 + 循环检测
        fp = page_fingerprint(runtime, page_id)
        warnings = _loop_detector.record("fill", fingerprint=fp, selector=selector)
        if warnings:
            ret["_guard_warnings"] = warnings
        return ret
    finally:
        cdp.close()


def browser_scroll(runtime, page_id: str, direction: str = "down", amount: int = 500) -> dict:
    """滚动页面。direction: 'up' | 'down'。amount: 像素数。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        sign = -1 if direction == "up" else 1
        px = sign * abs(amount)
        js = f"window.scrollBy(0, {px}); JSON.stringify({{scrollY: window.scrollY, scrollHeight: document.body.scrollHeight, innerHeight: window.innerHeight}})"
        result = cdp.send("Runtime.evaluate", {"expression": js})
        raw = result.get("result", {}).get("value", "{}")
        info = json.loads(raw)
        ret = {
            "status": "ok",
            "scrollY": info.get("scrollY", 0),
            "scrollHeight": info.get("scrollHeight", 0),
            "viewportHeight": info.get("innerHeight", 0),
            "atBottom": info.get("scrollY", 0) + info.get("innerHeight", 0) >= info.get("scrollHeight", 0) - 5,
        }
        # Guard
        fp = page_fingerprint(runtime, page_id)
        warnings = _loop_detector.record("scroll", fingerprint=fp, direction=direction)
        if warnings:
            ret["_guard_warnings"] = warnings
        return ret
    finally:
        cdp.close()


def browser_send_keys(runtime, page_id: str, keys: str) -> dict:
    """发送键盘按键。支持特殊键名：Enter, Tab, Escape, Backspace, ArrowUp/Down/Left/Right。

    用 CDP Input.dispatchKeyEvent 发送真实键盘事件（非 JS 模拟）。
    """
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}

    # 特殊键映射：keyName → (key, code, keyCode, text)
    _SPECIAL = {
        "Enter":      ("Enter",     "Enter",      13, "\r"),
        "Tab":        ("Tab",       "Tab",         9,  ""),
        "Escape":     ("Escape",    "Escape",      27, ""),
        "Backspace":  ("Backspace", "Backspace",   8,  ""),
        "ArrowUp":    ("ArrowUp",   "ArrowUp",     38, ""),
        "ArrowDown":  ("ArrowDown", "ArrowDown",   40, ""),
        "ArrowLeft":  ("ArrowLeft", "ArrowLeft",   37, ""),
        "ArrowRight": ("ArrowRight","ArrowRight",  39, ""),
        "Delete":     ("Delete",    "Delete",      46, ""),
        "Home":       ("Home",      "Home",        36, ""),
        "End":        ("End",       "End",         35, ""),
    }

    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        if keys in _SPECIAL:
            key, code, key_code, text = _SPECIAL[keys]
            for event_type in ("keyDown", "keyUp"):
                params = {
                    "type": event_type,
                    "key": key,
                    "code": code,
                    "windowsVirtualKeyCode": key_code,
                    "nativeVirtualKeyCode": key_code,
                }
                if event_type == "keyDown" and text:
                    params["text"] = text
                cdp.send("Input.dispatchKeyEvent", params)
        else:
            # 普通字符：逐字符发送 keyDown + char + keyUp
            for ch in keys:
                cdp.send("Input.dispatchKeyEvent", {
                    "type": "keyDown",
                    "key": ch,
                    "text": ch,
                })
                cdp.send("Input.dispatchKeyEvent", {
                    "type": "keyUp",
                    "key": ch,
                })
        return {"status": "ok", "keys": keys}
    finally:
        cdp.close()


def browser_find_text(runtime, page_id: str, text: str) -> dict:
    """在页面中查找文本并滚动到其位置。返回是否找到以及元素信息。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        escaped = json.dumps(text)
        js = f"""
        (() => {{
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null
            );
            while (walker.nextNode()) {{
                if (walker.currentNode.textContent.includes({escaped})) {{
                    const el = walker.currentNode.parentElement;
                    el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    const rect = el.getBoundingClientRect();
                    return JSON.stringify({{
                        found: true,
                        tag: el.tagName.toLowerCase(),
                        text: el.textContent.substring(0, 200),
                        y: Math.round(window.scrollY + rect.top),
                    }});
                }}
            }}
            return JSON.stringify({{found: false}});
        }})()
        """
        result = cdp.send("Runtime.evaluate", {"expression": js})
        raw = result.get("result", {}).get("value", '{"found": false}')
        info = json.loads(raw)
        if info.get("found"):
            return {"status": "ok", **info}
        return {"status": "not_found", "message": f"Text not found: {text}"}
    finally:
        cdp.close()


def browser_click_at(runtime, page_id: str, x: int, y: int) -> dict:
    """通过真实鼠标事件点击坐标。绕过反自动化检测，用于 JS click 失效的场景。

    从 web-access 偷师：JS click 是快捷路径，真实鼠标事件是后备方案。
    """
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        for event_type in ("mousePressed", "mouseReleased"):
            cdp.send("Input.dispatchMouseEvent", {
                "type": event_type,
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            })
        ret = {"status": "ok", "x": x, "y": y}
        fp = page_fingerprint(runtime, page_id)
        warnings = _loop_detector.record("click_at", fingerprint=fp, selector=f"@{x},{y}")
        if warnings:
            ret["_guard_warnings"] = warnings
        return ret
    finally:
        cdp.close()


def browser_search(runtime, query: str, engine: str = "google") -> dict:
    """高级搜索函数 — 自动导航到搜索引擎并执行搜索。

    从 web-access 偷师的工具选择思维：与其让 agent 手动 navigate → fill → send_keys，
    不如提供一个高级函数把整个流程封装起来。

    engine: 'google' | 'bing' | 'duckduckgo'
    """
    import urllib.parse

    _ENGINES = {
        "google":     "https://www.google.com/search?q={}",
        "bing":       "https://www.bing.com/search?q={}",
        "duckduckgo": "https://duckduckgo.com/?q={}",
    }

    engine = engine.lower()
    if engine not in _ENGINES:
        return {"error": f"Unknown search engine: {engine}. Use: {', '.join(_ENGINES)}"}

    url = _ENGINES[engine].format(urllib.parse.quote_plus(query))
    result = browser_navigate(runtime, url)
    result["query"] = query
    result["engine"] = engine
    return result


def browser_evaluate(runtime, page_id: str, expression: str) -> dict:
    """在页面中执行任意 JavaScript。高危工具，需白名单授权。"""
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        return {"error": f"Page {page_id} not found"}
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        result = cdp.send("Runtime.evaluate", {"expression": expression})
        return {
            "value": result.get("result", {}).get("value"),
            "type": result.get("result", {}).get("type"),
        }
    finally:
        cdp.close()
