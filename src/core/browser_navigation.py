"""
Browser Navigation — 导航、页面读取、快照、搜索。
从 browser_tools.py 拆分出来。
"""
import json
import logging
import time

from src.core.browser_guard import page_fingerprint, _loop_detector

log = logging.getLogger(__name__)


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


# ── Carbonyl 偷师 #1: screencastFrame 帧流 ──────────────────────
# 原理：Carbonyl 用自定义 SoftwareOutputDevice 让 compositor 每帧直接
# 写入共享内存，实现零拷贝帧流。CDP 层没法做到那么底层，但
# Page.screencastFrame 是最接近的——持续推帧而非逐次截图。


def browser_screencast_start(runtime, page_id: str,
                             format: str = "png",
                             quality: int = 60,
                             max_width: int = 1280,
                             max_height: int = 720,
                             every_nth_frame: int = 1) -> "CDPClient":
    """启动 screencast 帧流，返回持有连接的 CDPClient。

    调用方通过 cdp.recv_event() 接收 Page.screencastFrame 事件，
    每帧包含 {data: base64, metadata: {offsetTop, pageScaleFactor, ...}, sessionId}。
    **必须**对每帧调用 browser_screencast_ack() 确认，否则推帧停止。

    用法示例::

        cdp = browser_screencast_start(runtime, page_id)
        try:
            for _ in range(30):  # 收 30 帧
                ev = cdp.recv_event(timeout=2.0)
                if ev and ev.get("method") == "Page.screencastFrame":
                    frame_b64 = ev["params"]["data"]
                    session_id = ev["params"]["sessionId"]
                    browser_screencast_ack(cdp, session_id)
                    # ... process frame_b64
        finally:
            browser_screencast_stop(cdp)
    """
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        raise ValueError(f"Page {page_id} not found")

    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    cdp.send("Page.enable")
    cdp.send("Page.startScreencast", {
        "format": format,
        "quality": quality,
        "maxWidth": max_width,
        "maxHeight": max_height,
        "everyNthFrame": every_nth_frame,
    })
    log.info("screencast started for page %s (%dx%d, q=%d)",
             page_id, max_width, max_height, quality)
    return cdp


def browser_screencast_ack(cdp, session_id: int) -> None:
    """确认收到 screencast 帧，释放下一帧推送。"""
    cdp.send("Page.screencastFrameAck", {"sessionId": session_id})


def browser_screencast_stop(cdp) -> None:
    """停止 screencast 并关闭连接。"""
    try:
        cdp.send("Page.stopScreencast")
    except Exception:
        pass
    cdp.close()


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


def browser_snapshot(runtime, page_id: str) -> dict:
    """获取页面结构的索引化表示。

    从 browser-use 偷师的元素索引系统：
    - 每个可交互元素分配数字索引 [0], [1], [2]...
    - 只保留可见元素（可见性检测链：display/visibility/opacity + 视口相交）
    - agent 可以直接用 browser_click_index(index) 操作元素

    返回 {snapshot: str, element_map: dict[int, {tag, selector, text}]}
    """
    pages = runtime.list_pages()
    target = next((p for p in pages if p["id"] == page_id), None)
    if not target:
        raise ValueError(f"Page {page_id} not found")
    cdp = runtime.new_cdp_client(target["webSocketDebuggerUrl"])
    try:
        result = cdp.send("Runtime.evaluate", {"expression": _SNAPSHOT_JS})
        raw = result.get("result", {}).get("value", '{"lines":[],"map":{}}')
        data = json.loads(raw)
        return {
            "snapshot": "\n".join(data.get("lines", [])),
            "element_map": {int(k): v for k, v in data.get("map", {}).items()},
            "total_elements": data.get("total", 0),
            "visible_interactive": data.get("interactive", 0),
        }
    finally:
        cdp.close()


# browser_snapshot 的 JS 实现：元素索引 + 可见性过滤
_SNAPSHOT_JS = """
(() => {
    // 可见性检测链（从 browser-use 偷师）
    const isVisible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none') return false;
        if (style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) < 0.1) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return false;
        // 视口相交测试：元素至少部分可见（含 2 屏缓冲区）
        const buffer = window.innerHeight * 2;
        if (rect.bottom < -buffer || rect.top > window.innerHeight + buffer) return false;
        return true;
    };

    // 可交互元素选择器
    const interactiveSelector = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [onclick], [tabindex]:not([tabindex="-1"])';

    // 构建唯一 CSS selector（用于 click 回引）
    const getSelector = (el) => {
        if (el.id) return '#' + CSS.escape(el.id);
        const tag = el.tagName.toLowerCase();
        const parent = el.parentElement;
        if (!parent) return tag;
        const siblings = [...parent.children].filter(c => c.tagName === el.tagName);
        if (siblings.length === 1) return getSelector(parent) + ' > ' + tag;
        const idx = siblings.indexOf(el) + 1;
        return getSelector(parent) + ' > ' + tag + ':nth-of-type(' + idx + ')';
    };

    const lines = [];
    const map = {};
    let idx = 0;
    let total = 0;

    // Pass 1: 可交互元素（带索引）
    const interactives = document.querySelectorAll(interactiveSelector);
    interactives.forEach(el => {
        total++;
        if (!isVisible(el)) return;
        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const text = ariaLabel || el.textContent?.trim().substring(0, 80) || '';
        if (!text && tag !== 'input' && tag !== 'textarea') return;
        const type = el.type ? ' type="' + el.type + '"' : '';
        const val = el.value ? ' value="' + el.value.substring(0, 50) + '"' : '';
        const href = el.href ? ' href="' + el.href.substring(0, 60) + '"' : '';
        const roleStr = role ? '[' + role + ']' : '';

        lines.push('[' + idx + '] ' + tag + roleStr + type + href + ': ' + text + val);
        map[idx] = {tag, selector: getSelector(el), text: text.substring(0, 100)};
        idx++;
    });

    // Pass 2: 内容元素（无索引，仅展示）
    const contentTags = ['h1','h2','h3','h4','h5','h6','p','li','td','th','label','legend','figcaption'];
    contentTags.forEach(tag => {
        document.querySelectorAll(tag).forEach(el => {
            if (!isVisible(el)) return;
            const text = el.textContent?.trim().substring(0, 120);
            if (!text || text.length < 2) return;
            // 跳过已经被可交互元素覆盖的
            if (el.querySelector(interactiveSelector)) return;
            lines.push('    ' + tag + ': ' + text);
        });
    });

    return JSON.stringify({lines, map, total, interactive: idx});
})()
"""


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
