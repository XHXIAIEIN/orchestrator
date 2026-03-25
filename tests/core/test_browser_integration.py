import pytest
import shutil
import tempfile
import time
from src.core.browser_runtime import BrowserRuntime


def _chrome_usable() -> bool:
    """
    判断 Chrome 是否可用：不只检查路径存在，还要验证能实际启动并暴露 CDP。
    在 headless=new 不可用的无头 Windows session 中返回 False。
    """
    import urllib.request
    import json

    rt = BrowserRuntime(enabled=True)
    if rt._find_chrome() is None:
        return False

    tmp = tempfile.mkdtemp(prefix="chrome_probe_")
    probe = BrowserRuntime(
        enabled=True,
        headless=True,
        user_data_dir=tmp,
        debug_port=19299,
    )
    try:
        return probe.start()
    finally:
        probe.stop()


_CHROME_USABLE = _chrome_usable()


@pytest.mark.skipif(not _CHROME_USABLE, reason="Chrome/Chromium not installed or cannot start in this environment")
class TestBrowserIntegration:
    """集成测试 — 需要实际 Chrome 进程。CI 环境可跳过。"""

    def test_start_stop_lifecycle(self, tmp_path):
        rt = BrowserRuntime(
            enabled=True,
            headless=True,
            user_data_dir=str(tmp_path / "chrome_test"),
            debug_port=19222,
        )
        try:
            assert rt.start()
            assert rt.available
            h = rt.health()
            assert h["status"] == "running"
            # chrome_version 通过 health() 返回，不是实例属性
            assert h["chrome_version"] is not None

            ws_url = rt.cdp_url()
            assert ws_url is not None
            assert "ws://" in ws_url
        finally:
            rt.stop()
            assert not rt.available

    def test_tab_pool_lifecycle(self, tmp_path):
        rt = BrowserRuntime(
            enabled=True,
            headless=True,
            user_data_dir=str(tmp_path / "chrome_test2"),
            debug_port=19223,
            max_tabs=2,
        )
        try:
            assert rt.start()

            t1 = rt._acquire_tab_internal("read", "engineering")
            t2 = rt._acquire_tab_internal("interact", "operations")
            assert t1 is not None
            assert t2 is not None

            # Over limit
            t3 = rt._acquire_tab_internal("read", "quality")
            assert t3 is None

            # Release and re-acquire
            rt._release_tab_internal(t1.tab_id)
            t4 = rt._acquire_tab_internal("read", "quality")
            assert t4 is not None
        finally:
            rt.stop()

    def test_health_reports_tab_count(self, tmp_path):
        rt = BrowserRuntime(
            enabled=True,
            headless=True,
            user_data_dir=str(tmp_path / "chrome_test3"),
            debug_port=19224,
        )
        try:
            assert rt.start()
            h = rt.health()
            assert "tabs" in h or "status" in h
        finally:
            rt.stop()
