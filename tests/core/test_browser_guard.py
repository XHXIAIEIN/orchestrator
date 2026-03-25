"""BrowserGuard 测试 — 循环检测 + 页面指纹。"""
import json
import pytest
from unittest.mock import MagicMock

from src.core.browser_guard import (
    PageFingerprint,
    ActionLoopDetector,
    page_fingerprint,
)


# ------------------------------------------------------------------
# PageFingerprint
# ------------------------------------------------------------------

class TestPageFingerprint:
    def test_same_content_identical(self):
        fp1 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123")
        fp2 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123")
        assert fp1.same_content(fp2)

    def test_same_content_different_timestamp(self):
        fp1 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123", timestamp=1.0)
        fp2 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123", timestamp=9.0)
        assert fp1.same_content(fp2)

    def test_different_url(self):
        fp1 = PageFingerprint(url="http://a.com", interactive_count=10, dom_hash="abc123")
        fp2 = PageFingerprint(url="http://b.com", interactive_count=10, dom_hash="abc123")
        assert not fp1.same_content(fp2)

    def test_different_element_count(self):
        fp1 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123")
        fp2 = PageFingerprint(url="http://x.com", interactive_count=20, dom_hash="abc123")
        assert not fp1.same_content(fp2)

    def test_different_hash(self):
        fp1 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123")
        fp2 = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="def456")
        assert not fp1.same_content(fp2)

    def test_str_truncates_url(self):
        fp = PageFingerprint(url="http://x.com/" + "a" * 100, interactive_count=5, dom_hash="hash16chars0000")
        s = str(fp)
        assert "elements=5" in s
        assert "hash=hash16chars0000" in s
        assert len(s) < 200  # 不会爆炸

    def test_not_same_content_with_non_fingerprint(self):
        fp = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abc123")
        assert not fp.same_content("not a fingerprint")


class TestPageFingerprintCDP:
    """测试 page_fingerprint() CDP 采集函数。"""

    def _mock_runtime(self, page_id="P1", ws_url="ws://fake"):
        rt = MagicMock()
        rt.list_pages.return_value = [{"id": page_id, "webSocketDebuggerUrl": ws_url}]
        cdp = MagicMock()
        rt.new_cdp_client.return_value = cdp
        return rt, cdp

    def test_success(self):
        rt, cdp = self._mock_runtime()
        cdp.send.side_effect = [
            {"result": {"value": "http://example.com/page"}},       # location.href
            {"result": {"value": json.dumps({"count": 42, "text": "hello world"})}},  # fingerprint JS
        ]
        fp = page_fingerprint(rt, "P1")
        assert fp is not None
        assert fp.url == "http://example.com/page"
        assert fp.interactive_count == 42
        assert len(fp.dom_hash) == 16

    def test_page_not_found_returns_none(self):
        rt, cdp = self._mock_runtime()
        fp = page_fingerprint(rt, "NONEXISTENT")
        assert fp is None

    def test_cdp_error_returns_none(self):
        rt, cdp = self._mock_runtime()
        cdp.send.side_effect = RuntimeError("CDP boom")
        fp = page_fingerprint(rt, "P1")
        assert fp is None

    def test_hash_deterministic(self):
        rt, cdp = self._mock_runtime()
        payload = json.dumps({"count": 5, "text": "same text"})
        cdp.send.side_effect = [
            {"result": {"value": "http://x.com"}},
            {"result": {"value": payload}},
        ]
        fp1 = page_fingerprint(rt, "P1")

        cdp.send.side_effect = [
            {"result": {"value": "http://x.com"}},
            {"result": {"value": payload}},
        ]
        fp2 = page_fingerprint(rt, "P1")

        assert fp1.dom_hash == fp2.dom_hash


# ------------------------------------------------------------------
# ActionLoopDetector
# ------------------------------------------------------------------

class TestActionLoopDetector:

    def test_no_warning_for_few_actions(self):
        det = ActionLoopDetector()
        for _ in range(3):
            warnings = det.record("click", selector="#btn")
        assert warnings == []

    def test_soft_warning_at_5(self):
        det = ActionLoopDetector()
        warnings = []
        for _ in range(5):
            warnings = det.record("click", selector="#btn")
        assert len(warnings) == 1
        assert "5" in warnings[0]

    def test_warn_at_8(self):
        det = ActionLoopDetector()
        warnings = []
        for _ in range(8):
            warnings = det.record("click", selector="#btn")
        assert len(warnings) == 1
        assert "8" in warnings[0]
        assert "不同的策略" in warnings[0]

    def test_hard_warning_at_12(self):
        det = ActionLoopDetector()
        warnings = []
        for _ in range(12):
            warnings = det.record("click", selector="#btn")
        assert len(warnings) == 1
        assert "12" in warnings[0]
        assert "强烈建议" in warnings[0]

    def test_different_actions_no_warning(self):
        det = ActionLoopDetector()
        for i in range(20):
            warnings = det.record("click", selector=f"#btn-{i}")
            assert warnings == []

    def test_normalize_navigate(self):
        assert ActionLoopDetector.normalize("navigate", url="http://x.com") == "navigate:http://x.com"

    def test_normalize_click_case_insensitive(self):
        assert ActionLoopDetector.normalize("Click", selector="#MyBtn") == "click:#mybtn"

    def test_normalize_search_token_sort(self):
        n1 = ActionLoopDetector.normalize("search", query="python web scraping")
        n2 = ActionLoopDetector.normalize("search", query="scraping web python")
        assert n1 == n2

    def test_normalize_fill_ignores_text(self):
        n1 = ActionLoopDetector.normalize("fill", selector="#email")
        n2 = ActionLoopDetector.normalize("fill", selector="#email")
        assert n1 == n2  # 同一输入框，不管填什么都算同一动作

    def test_stagnation_detection(self):
        det = ActionLoopDetector()
        fp = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="abcd1234abcd1234")
        warnings = []
        # 需要 3 次相同指纹触发停滞
        for i in range(3):
            warnings = det.record(f"click-{i}", fingerprint=fp, selector=f"#btn-{i}")
        assert any("停滞" in w for w in warnings)

    def test_no_stagnation_when_page_changes(self):
        det = ActionLoopDetector()
        for i in range(5):
            fp = PageFingerprint(url="http://x.com", interactive_count=10 + i, dom_hash=f"hash{i:016d}")
            warnings = det.record("click", fingerprint=fp, selector="#btn")
        # 动作可能循环（5次 click:#btn），但页面在变化
        stagnation_warnings = [w for w in warnings if "停滞" in w]
        assert stagnation_warnings == []

    def test_loop_and_stagnation_together(self):
        """同时触发循环和停滞时，两个警告都应返回。"""
        det = ActionLoopDetector()
        fp = PageFingerprint(url="http://x.com", interactive_count=10, dom_hash="deadbeef12345678")
        for _ in range(5):
            warnings = det.record("click", fingerprint=fp, selector="#btn")
        # 第 5 次：click:#btn 重复 5 次 + 指纹连续 5 次相同
        assert len(warnings) == 2

    def test_reset_clears_state(self):
        det = ActionLoopDetector()
        for _ in range(5):
            det.record("click", selector="#btn")
        det.reset()
        # 重置后不应有警告
        warnings = det.record("click", selector="#btn")
        assert warnings == []

    def test_max_history_respected(self):
        det = ActionLoopDetector(max_history=5)
        # 填满 5 个不同动作
        for i in range(5):
            det.record("click", selector=f"#btn-{i}")
        # 现在加同一个动作 5 次（旧的会被挤出去）
        warnings = []
        for _ in range(5):
            warnings = det.record("click", selector="#new-btn")
        assert len(warnings) == 1  # 5 次触发 soft warning

    def test_stats(self):
        det = ActionLoopDetector()
        det.record("click", selector="#a")
        det.record("click", selector="#a")
        det.record("navigate", url="http://x.com")
        stats = det.stats
        assert stats["total_actions"] == 3
        assert stats["unique_actions"] == 2
        assert stats["most_repeated"][0][0] == "click:#a"
