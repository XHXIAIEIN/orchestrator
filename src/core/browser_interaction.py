"""
Browser Interaction — 点击、填写、滚动、按键、查找、执行 JS。
从 browser_tools.py 拆分出来。
"""
import json
import logging

from src.core.browser_guard import page_fingerprint, _loop_detector

log = logging.getLogger(__name__)


def browser_click_index(runtime, page_id: str, index: int, method: str = "js") -> dict:
    """通过 snapshot 的元素索引点击。先调用 browser_snapshot 获取 element_map。

    method: 'js' (快，默认) | 'mouse' (真实鼠标事件，绕过反自动化检测)
    """
    from src.core.browser_navigation import browser_snapshot

    # 先获取 snapshot 拿 element_map
    snap = browser_snapshot(runtime, page_id)
    element_map = snap.get("element_map", {})
    if index not in element_map:
        return {"status": "error", "message": f"Element index {index} not found. Valid: 0-{len(element_map)-1}"}

    selector = element_map[index]["selector"]

    if method == "mouse":
        # 获取元素中心坐标，用真实鼠标事件
        pages = runtime.list_pages()
        target = next((p for p in pages if p["id"] == page_id), None)
        if not target:
            return {"error": f"Page {page_id} not found"}
        cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
        try:
            js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return JSON.stringify({{x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}});
            }})()
            """
            result = cdp.send("Runtime.evaluate", {"expression": js})
            raw = result.get("result", {}).get("value")
            if not raw:
                return {"status": "error", "message": f"Could not locate element {index} for mouse click"}
            coords = json.loads(raw)
            return browser_click_at(runtime, page_id, coords["x"], coords["y"])
        finally:
            cdp.close()
    else:
        return browser_click(runtime, page_id, selector)


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
