import json
import pytest
from unittest.mock import MagicMock, patch
from src.core.browser_ai import BrowserAI


def _mock_runtime():
    rt = MagicMock()
    rt.available = True
    rt.list_pages.return_value = [{"id": "AI_PAGE", "webSocketDebuggerUrl": "ws://fake"}]
    rt.open_page.return_value = {"id": "AI_PAGE", "webSocketDebuggerUrl": "ws://fake"}
    mock_cdp = MagicMock()
    rt.new_cdp_client.return_value = mock_cdp
    return rt, mock_cdp


def test_capabilities_unavailable_when_runtime_down():
    rt = MagicMock()
    rt.available = False
    ai = BrowserAI(rt)
    caps = ai.capabilities()
    assert caps["summarizer"] == "unavailable"
    assert caps["translator"] == "unavailable"


def test_capabilities_probes_browser():
    rt, cdp = _mock_runtime()
    # CDPClient.send 返回的是已剥离外层的 result，即 {"type": "string", "value": "..."}
    cdp.send.return_value = {"value": json.dumps({
        "summarizer": "available",
        "translator": "available",
        "language_detector": "available",
        "prompt": "unavailable",
        "writer": "unavailable",
        "rewriter": "unavailable",
    })}
    ai = BrowserAI(rt)
    caps = ai.capabilities()
    assert caps["summarizer"] == "available"
    assert caps["prompt"] == "unavailable"


def test_capabilities_cached():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"value": json.dumps({
        "summarizer": "available",
        "translator": "available",
        "language_detector": "available",
        "prompt": "unavailable",
        "writer": "unavailable",
        "rewriter": "unavailable",
    })}
    ai = BrowserAI(rt)
    ai.capabilities()
    ai.capabilities()  # 第二次应命中缓存
    # open_page 只在第一次建立 AI 页面时调用一次
    assert rt.open_page.call_count == 1


def test_is_available():
    rt, cdp = _mock_runtime()
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"summarizer": "available", "translator": "unavailable"}
    assert ai.is_available("summarizer")
    assert not ai.is_available("translator")
    assert not ai.is_available("nonexistent")


def test_summarize_returns_none_when_unavailable():
    rt, cdp = _mock_runtime()
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"summarizer": "unavailable"}
    assert ai.summarize("some text") is None


def test_summarize_calls_api():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"value": "Summary: key points here"}
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"summarizer": "available"}
    ai._ai_page_id = "AI_PAGE"
    ai._ai_page_ws = "ws://fake"
    result = ai.summarize("long text here")
    assert result == "Summary: key points here"


def test_translate_calls_api():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"value": "你好世界"}
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"translator": "available"}
    ai._ai_page_id = "AI_PAGE"
    ai._ai_page_ws = "ws://fake"
    result = ai.translate("Hello world", "en", "zh")
    assert result == "你好世界"


def test_detect_language():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"value": json.dumps([{"detectedLanguage": "en", "confidence": 0.95}])}
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"language_detector": "available"}
    ai._ai_page_id = "AI_PAGE"
    ai._ai_page_ws = "ws://fake"
    result = ai.detect_language("Hello world")
    assert result[0]["detectedLanguage"] == "en"


def test_summarize_handles_error_gracefully():
    rt, cdp = _mock_runtime()
    cdp.send.side_effect = RuntimeError("CDP error: something broke")
    ai = BrowserAI(rt)
    ai._capabilities_cache = {"summarizer": "available"}
    ai._ai_page_id = "AI_PAGE"
    ai._ai_page_ws = "ws://fake"
    result = ai.summarize("text")
    assert result is None  # 优雅降级，不抛异常


def test_sync_wrappers():
    rt, cdp = _mock_runtime()
    ai = BrowserAI(rt)
    ai._capabilities_cache = {
        "summarizer": "unavailable",
        "translator": "unavailable",
        "language_detector": "unavailable",
    }
    assert ai.summarize_sync("text") is None
    assert ai.translate_sync("text", "en", "zh") is None
    assert ai.detect_language_sync("text") is None
