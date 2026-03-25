"""
BrowserAI — Chrome 内置 AI API 封装。
通过 CDP Runtime.evaluate 在浏览器中调用 Web AI API（Summarizer, Translator, LanguageDetector 等）。

重要：仅桌面环境（非 headless）可用。Docker/headless 下自动降级。
"""
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


class BrowserAI:
    """
    Chrome 内置 AI 能力封装。
    通过 BrowserRuntime 的 CDP 连接调用页面内 Web AI API。
    """

    def __init__(self, runtime):
        self._runtime = runtime
        self._capabilities_cache: Optional[dict] = None
        self._ai_page_id: Optional[str] = None
        self._ai_page_ws: Optional[str] = None

    def _ensure_ai_page(self):
        """确保有一个常驻的空白页用于 AI API 调用。"""
        if self._ai_page_id:
            # 检查页面是否还存在
            pages = self._runtime.list_pages()
            if any(p["id"] == self._ai_page_id for p in pages):
                return
        # 创建新的 AI 页面
        info = self._runtime.open_page("about:blank")
        self._ai_page_id = info["id"]
        self._ai_page_ws = info["webSocketDebuggerUrl"]
        log.info(f"browser_ai: created AI context page {self._ai_page_id}")

    def _eval(self, js: str, timeout: float = 30) -> dict:
        """在 AI 页面中执行 JS 并返回 CDP result 字典。

        CDPClient.send 已经剥离了外层的 {"id": ..., "result": ...}，
        直接返回 data["result"]，所以这里返回值就是 result 本身。
        调用方通过 result.get("value") 取值。
        """
        self._ensure_ai_page()
        cdp = self._runtime.new_cdp_client(self._ai_page_ws)
        try:
            result = cdp.send("Runtime.evaluate", {
                "expression": js,
                "awaitPromise": True,
                "timeout": int(timeout * 1000),
            })
            return result
        finally:
            cdp.close()

    def capabilities(self) -> dict:
        """探测哪些 Chrome AI API 可用。结果缓存。"""
        if self._capabilities_cache is not None:
            return self._capabilities_cache

        if not self._runtime.available:
            self._capabilities_cache = {
                "summarizer": "unavailable",
                "translator": "unavailable",
                "language_detector": "unavailable",
                "prompt": "unavailable",
                "writer": "unavailable",
                "rewriter": "unavailable",
            }
            return self._capabilities_cache

        js = """
        (async () => {
            const caps = {};
            try { caps.summarizer = typeof Summarizer !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.summarizer = 'unavailable'; }
            try { caps.translator = typeof Translator !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.translator = 'unavailable'; }
            try { caps.language_detector = typeof LanguageDetector !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.language_detector = 'unavailable'; }
            try { caps.prompt = typeof LanguageModel !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.prompt = 'unavailable'; }
            try { caps.writer = typeof Writer !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.writer = 'unavailable'; }
            try { caps.rewriter = typeof Rewriter !== 'undefined' ? 'available' : 'unavailable'; } catch(e) { caps.rewriter = 'unavailable'; }
            return JSON.stringify(caps);
        })()
        """
        try:
            result = self._eval(js)
            # CDPClient.send 返回的是 data["result"]，即 {"type": "string", "value": "..."}
            val = result.get("value", "{}")
            self._capabilities_cache = json.loads(val)
        except Exception as e:
            log.warning(f"browser_ai: capabilities probe failed: {e}")
            self._capabilities_cache = {
                "summarizer": "unavailable",
                "translator": "unavailable",
                "language_detector": "unavailable",
                "prompt": "unavailable",
                "writer": "unavailable",
                "rewriter": "unavailable",
            }
        return self._capabilities_cache

    def is_available(self, capability: str) -> bool:
        """检查指定 AI 能力是否可用。"""
        return self.capabilities().get(capability) == "available"

    def summarize(self, text: str, type: str = "key-points",
                  length: str = "medium", format: str = "markdown") -> Optional[str]:
        """使用 Chrome Summarizer API 生成摘要。不可用时返回 None。"""
        if not self.is_available("summarizer"):
            return None
        escaped = json.dumps(text)
        js = f"""
        (async () => {{
            const s = await Summarizer.create({{type: '{type}', format: '{format}', length: '{length}'}});
            return await s.summarize({escaped});
        }})()
        """
        try:
            result = self._eval(js, timeout=60)
            return result.get("value")
        except Exception as e:
            log.warning(f"browser_ai: summarize failed: {e}")
            return None

    def translate(self, text: str, source: str, target: str) -> Optional[str]:
        """使用 Chrome Translator API 翻译文本。不可用时返回 None。"""
        if not self.is_available("translator"):
            return None
        escaped = json.dumps(text)
        js = f"""
        (async () => {{
            const t = await Translator.create({{sourceLanguage: '{source}', targetLanguage: '{target}'}});
            return await t.translate({escaped});
        }})()
        """
        try:
            result = self._eval(js, timeout=30)
            return result.get("value")
        except Exception as e:
            log.warning(f"browser_ai: translate failed: {e}")
            return None

    def detect_language(self, text: str) -> Optional[list]:
        """检测文本语言。返回 [{detectedLanguage, confidence}, ...]。不可用时返回 None。"""
        if not self.is_available("language_detector"):
            return None
        escaped = json.dumps(text)
        js = f"""
        (async () => {{
            const d = await LanguageDetector.create();
            const results = await d.detect({escaped});
            return JSON.stringify(results);
        }})()
        """
        try:
            result = self._eval(js, timeout=15)
            val = result.get("value", "[]")
            return json.loads(val)
        except Exception as e:
            log.warning(f"browser_ai: detect_language failed: {e}")
            return None

    def prompt(self, system_prompt: str, user_message: str) -> Optional[str]:
        """使用 Chrome Prompt API (Gemini Nano) 生成回复。不可用时返回 None。"""
        if not self.is_available("prompt"):
            return None
        sys_escaped = json.dumps(system_prompt)
        user_escaped = json.dumps(user_message)
        js = f"""
        (async () => {{
            const session = await LanguageModel.create({{
                initialPrompts: [{{role: 'system', content: {sys_escaped}}}]
            }});
            return await session.prompt({user_escaped});
        }})()
        """
        try:
            result = self._eval(js, timeout=60)
            return result.get("value")
        except Exception as e:
            log.warning(f"browser_ai: prompt failed: {e}")
            return None

    # --- 同步桥接器（供 LLMRouter 调用）---

    def summarize_sync(self, text: str, **kwargs) -> Optional[str]:
        """同步版 summarize。"""
        return self.summarize(text, **kwargs)

    def translate_sync(self, text: str, source: str, target: str) -> Optional[str]:
        """同步版 translate。"""
        return self.translate(text, source, target)

    def detect_language_sync(self, text: str) -> Optional[list]:
        """同步版 detect_language。"""
        return self.detect_language(text)
