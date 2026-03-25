import json
import pytest
from unittest.mock import MagicMock, patch
from src.core.browser_tools import (
    browser_navigate, browser_screenshot, browser_snapshot,
    browser_read_page, browser_click, browser_fill, browser_evaluate,
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
