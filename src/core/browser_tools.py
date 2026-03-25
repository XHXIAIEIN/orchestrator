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
