import json
import pytest
from unittest.mock import patch, MagicMock
from src.core.browser_runtime import CDPClient, BrowserRuntime

class TestCDPClient:
    def test_send_receives_matching_response(self):
        """send() 正确匹配 id 响应。"""
        mock_ws = MagicMock()
        mock_ws.recv.return_value = json.dumps({"id": 1, "result": {"data": "test"}})

        client = CDPClient("ws://fake", timeout=5)
        client._ws = mock_ws

        result = client.send("Page.navigate", {"url": "http://example.com"})
        assert result == {"data": "test"}
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["method"] == "Page.navigate"
        assert sent["params"]["url"] == "http://example.com"

    def test_send_skips_events(self):
        """send() 跳过事件消息，等待匹配 id。"""
        mock_ws = MagicMock()
        mock_ws.recv.side_effect = [
            json.dumps({"method": "Page.loadEventFired", "params": {}}),
            json.dumps({"method": "Network.requestWillBeSent", "params": {}}),
            json.dumps({"id": 1, "result": {"title": "Test"}}),
        ]

        client = CDPClient("ws://fake", timeout=5)
        client._ws = mock_ws

        result = client.send("Runtime.evaluate", {"expression": "document.title"})
        assert result == {"title": "Test"}
        assert mock_ws.recv.call_count == 3

    def test_send_raises_on_cdp_error(self):
        """CDP 返回 error 时抛出 RuntimeError。"""
        mock_ws = MagicMock()
        mock_ws.recv.return_value = json.dumps({
            "id": 1, "error": {"code": -32000, "message": "Not found"}
        })

        client = CDPClient("ws://fake", timeout=5)
        client._ws = mock_ws

        with pytest.raises(RuntimeError, match="CDP error"):
            client.send("DOM.getDocument")

    def test_send_raises_when_not_connected(self):
        """未连接时 send() 抛出 RuntimeError。"""
        client = CDPClient("ws://fake")
        with pytest.raises(RuntimeError, match="not connected"):
            client.send("Page.navigate")

    def test_context_manager(self):
        """with 语句自动 connect/close。"""
        mock_ws = MagicMock()
        with patch("websockets.sync.client.connect", return_value=mock_ws):
            with CDPClient("ws://fake") as client:
                assert client._ws is mock_ws
            mock_ws.close.assert_called()

    def test_list_pages_when_unavailable(self):
        """runtime 不可用时 list_pages 返回空列表。"""
        rt = BrowserRuntime(enabled=False)
        assert rt.list_pages() == []
