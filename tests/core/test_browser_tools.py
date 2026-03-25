import json
import pytest
from unittest.mock import MagicMock, patch
from src.core.browser_tools import (
    browser_navigate, browser_screenshot, browser_snapshot,
    browser_read_page, browser_click, browser_fill, browser_evaluate,
    browser_scroll, browser_send_keys, browser_find_text,
    browser_click_at, browser_click_index, browser_search,
)

def _mock_runtime(page_id="PAGE1", ws_url="ws://fake/page"):
    """Create a mock BrowserRuntime."""
    rt = MagicMock()
    rt.open_page.return_value = {"id": page_id, "webSocketDebuggerUrl": ws_url}
    rt.list_pages.return_value = [{"id": page_id, "type": "page", "webSocketDebuggerUrl": ws_url}]

    mock_cdp = MagicMock()
    rt.new_cdp_client.return_value = mock_cdp
    return rt, mock_cdp


def test_browser_navigate():
    rt, cdp = _mock_runtime()
    # readyState returns "complete", title returns "Test Page"
    cdp.send.side_effect = [
        {},  # Page.enable
        {},  # Page.navigate
        {"result": {"value": "complete"}},  # readyState check
        {"result": {"value": "Test Page"}},  # document.title
    ]
    result = browser_navigate(rt, "http://example.com")
    assert result["title"] == "Test Page"
    assert result["page_id"] == "PAGE1"
    rt.open_page.assert_called_once()

def test_browser_screenshot():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"data": "iVBORw0KGgo="}
    result = browser_screenshot(rt, "PAGE1")
    assert result == "iVBORw0KGgo="
    cdp.send.assert_called_with("Page.captureScreenshot", {"format": "png"})

def test_browser_screenshot_page_not_found():
    rt, cdp = _mock_runtime()
    with pytest.raises(ValueError, match="not found"):
        browser_screenshot(rt, "NONEXISTENT")

def test_browser_click():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": None}}
    result = browser_click(rt, "PAGE1", "#submit")
    assert result["status"] == "ok"

def test_browser_click_not_found():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": "not_found"}}
    result = browser_click(rt, "PAGE1", "#missing")
    assert result["status"] == "error"

def test_browser_fill():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": "filled"}}
    result = browser_fill(rt, "PAGE1", "input[name='email']", "test@example.com")
    assert result["status"] == "ok"

def test_browser_evaluate():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": 42, "type": "number"}}
    result = browser_evaluate(rt, "PAGE1", "1+1")
    assert result["value"] == 42

def test_browser_read_page():
    rt, cdp = _mock_runtime()
    cdp.send.side_effect = [
        {},  # Page.enable
        {},  # Page.navigate
        {"result": {"value": "complete"}},  # readyState
        {"result": {"value": "Hello World page content"}},  # body.innerText
    ]
    result = browser_read_page(rt, "http://example.com")
    assert "Hello World" in result
    rt.close_page.assert_called_once_with("PAGE1")


# ------------------------------------------------------------------
# 新增工具测试
# ------------------------------------------------------------------

def test_browser_scroll_down():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": json.dumps({
        "scrollY": 500, "scrollHeight": 3000, "innerHeight": 800,
    })}}
    result = browser_scroll(rt, "PAGE1", "down", 500)
    assert result["status"] == "ok"
    assert result["scrollY"] == 500
    assert result["atBottom"] is False


def test_browser_scroll_up():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": json.dumps({
        "scrollY": 0, "scrollHeight": 3000, "innerHeight": 800,
    })}}
    result = browser_scroll(rt, "PAGE1", "up", 500)
    assert result["status"] == "ok"
    assert result["scrollY"] == 0


def test_browser_scroll_at_bottom():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": json.dumps({
        "scrollY": 2200, "scrollHeight": 3000, "innerHeight": 800,
    })}}
    result = browser_scroll(rt, "PAGE1", "down")
    assert result["atBottom"] is True


def test_browser_scroll_page_not_found():
    rt, cdp = _mock_runtime()
    result = browser_scroll(rt, "NONEXISTENT")
    assert "error" in result


def test_browser_send_keys_enter():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {}
    result = browser_send_keys(rt, "PAGE1", "Enter")
    assert result["status"] == "ok"
    assert result["keys"] == "Enter"
    # keyDown + keyUp = 2 calls
    calls = [c for c in cdp.send.call_args_list if c[0][0] == "Input.dispatchKeyEvent"]
    assert len(calls) == 2
    assert calls[0][0][1]["type"] == "keyDown"
    assert calls[1][0][1]["type"] == "keyUp"


def test_browser_send_keys_text():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {}
    result = browser_send_keys(rt, "PAGE1", "hi")
    assert result["status"] == "ok"
    # 2 chars × (keyDown + keyUp) = 4 calls
    calls = [c for c in cdp.send.call_args_list if c[0][0] == "Input.dispatchKeyEvent"]
    assert len(calls) == 4


def test_browser_send_keys_page_not_found():
    rt, cdp = _mock_runtime()
    result = browser_send_keys(rt, "NONEXISTENT", "Enter")
    assert "error" in result


def test_browser_find_text_found():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": json.dumps({
        "found": True, "tag": "p", "text": "Hello World", "y": 1200,
    })}}
    result = browser_find_text(rt, "PAGE1", "Hello")
    assert result["status"] == "ok"
    assert result["found"] is True
    assert result["tag"] == "p"


def test_browser_find_text_not_found():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {"result": {"value": json.dumps({"found": False})}}
    result = browser_find_text(rt, "PAGE1", "Nonexistent")
    assert result["status"] == "not_found"


def test_browser_find_text_page_not_found():
    rt, cdp = _mock_runtime()
    result = browser_find_text(rt, "NONEXISTENT", "text")
    assert "error" in result


def test_browser_click_at():
    rt, cdp = _mock_runtime()
    cdp.send.return_value = {}
    result = browser_click_at(rt, "PAGE1", 100, 200)
    assert result["status"] == "ok"
    assert result["x"] == 100
    assert result["y"] == 200
    # mousePressed + mouseReleased = 2 calls
    calls = [c for c in cdp.send.call_args_list if c[0][0] == "Input.dispatchMouseEvent"]
    assert len(calls) == 2


def test_browser_click_at_page_not_found():
    rt, cdp = _mock_runtime()
    result = browser_click_at(rt, "NONEXISTENT", 0, 0)
    assert "error" in result


def test_browser_search_google():
    rt, cdp = _mock_runtime()
    cdp.send.side_effect = [
        {},  # Page.enable
        {},  # Page.navigate
        {"result": {"value": "complete"}},
        {"result": {"value": "python web scraping - Google Search"}},
    ]
    result = browser_search(rt, "python web scraping")
    assert result["query"] == "python web scraping"
    assert result["engine"] == "google"
    assert "page_id" in result


def test_browser_search_bing():
    rt, cdp = _mock_runtime()
    cdp.send.side_effect = [
        {},  # Page.enable
        {},  # Page.navigate
        {"result": {"value": "complete"}},
        {"result": {"value": "Results - Bing"}},
    ]
    result = browser_search(rt, "test query", engine="bing")
    assert result["engine"] == "bing"


def test_browser_search_unknown_engine():
    rt, cdp = _mock_runtime()
    result = browser_search(rt, "test", engine="yahoo")
    assert "error" in result


# ------------------------------------------------------------------
# browser_snapshot (indexed) + browser_click_index
# ------------------------------------------------------------------

def test_browser_snapshot_indexed():
    rt, cdp = _mock_runtime()
    snapshot_data = json.dumps({
        "lines": [
            '[0] button: Submit',
            '[1] a href="http://x.com": Link',
            '    h1: Page Title',
        ],
        "map": {
            "0": {"tag": "button", "selector": "#submit", "text": "Submit"},
            "1": {"tag": "a", "selector": "a:nth-of-type(1)", "text": "Link"},
        },
        "total": 5,
        "interactive": 2,
    })
    cdp.send.return_value = {"result": {"value": snapshot_data}}
    result = browser_snapshot(rt, "PAGE1")
    assert result["total_elements"] == 5
    assert result["visible_interactive"] == 2
    assert 0 in result["element_map"]
    assert result["element_map"][0]["tag"] == "button"
    assert "[0] button: Submit" in result["snapshot"]


def test_browser_snapshot_page_not_found():
    rt, cdp = _mock_runtime()
    with pytest.raises(ValueError, match="not found"):
        browser_snapshot(rt, "NONEXISTENT")


def test_browser_click_index_js():
    rt, cdp = _mock_runtime()
    # First call: snapshot to get element_map
    snapshot_data = json.dumps({
        "lines": ["[0] button: Submit"],
        "map": {"0": {"tag": "button", "selector": "#submit", "text": "Submit"}},
        "total": 1, "interactive": 1,
    })
    # click_index calls snapshot (1 CDP call), then browser_click (1 CDP call)
    cdp.send.side_effect = [
        {"result": {"value": snapshot_data}},  # snapshot
        {"result": {"value": None}},            # click
    ]
    result = browser_click_index(rt, "PAGE1", 0)
    assert result["status"] == "ok"


def test_browser_click_index_not_found():
    rt, cdp = _mock_runtime()
    snapshot_data = json.dumps({
        "lines": [], "map": {}, "total": 0, "interactive": 0,
    })
    cdp.send.return_value = {"result": {"value": snapshot_data}}
    result = browser_click_index(rt, "PAGE1", 99)
    assert result["status"] == "error"
    assert "99" in result["message"]
