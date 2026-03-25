import os
import subprocess
import time
import pytest
from unittest.mock import patch, MagicMock
from src.core.browser_runtime import BrowserRuntime, TabLease


def test_find_chrome_returns_path_when_exists():
    """shutil.which 能找到 chromium 时，应返回其路径。"""
    runtime = BrowserRuntime(enabled=True)
    with patch("shutil.which", side_effect=lambda name: "/usr/bin/chromium" if name == "chromium" else None):
        result = runtime._find_chrome()
    assert result == "/usr/bin/chromium"


def test_find_chrome_returns_none_when_missing():
    """系统中没有任何 Chrome/Chromium 时，应返回 None。"""
    runtime = BrowserRuntime(enabled=True)
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.exists", return_value=False):
            result = runtime._find_chrome()
    assert result is None


def test_runtime_disabled_by_env():
    """BROWSER_RUNTIME_ENABLED 未设置时，from_env() 应创建 enabled=False 的实例。"""
    env = {k: v for k, v in os.environ.items() if k != "BROWSER_RUNTIME_ENABLED"}
    with patch.dict("os.environ", env, clear=True):
        runtime = BrowserRuntime.from_env()
    assert runtime.enabled is False


def test_health_disabled():
    """enabled=False 时，health() 应返回 status='disabled'。"""
    runtime = BrowserRuntime(enabled=False)
    result = runtime.health()
    assert result["status"] == "disabled"
    assert result["chrome_version"] is None
    assert result["tabs"] == 0


def test_health_unavailable():
    """enabled=True 但没有进程时，health() 应返回 status='unavailable'。"""
    runtime = BrowserRuntime(enabled=True)
    # _process 为 None → available=False
    result = runtime.health()
    assert result["status"] == "unavailable"
    assert result["chrome_version"] is None
    assert result["tabs"] == 0


def test_from_env_reads_envvars():
    """from_env() 应正确读取所有 BROWSER_* 环境变量。"""
    env_overrides = {
        "BROWSER_RUNTIME_ENABLED": "true",
        "BROWSER_CHROME_PATH": "/opt/chrome/chrome",
        "BROWSER_DEBUG_PORT": "9333",
        "BROWSER_HEADLESS": "false",
        "BROWSER_USER_DATA_DIR": "/tmp/chrome_test",
        "BROWSER_MAX_TABS": "10",
    }
    with patch.dict("os.environ", env_overrides):
        runtime = BrowserRuntime.from_env()

    assert runtime.enabled is True
    assert runtime.chrome_path == "/opt/chrome/chrome"
    assert runtime.debug_port == 9333
    assert runtime.headless is False
    assert runtime.user_data_dir == "/tmp/chrome_test"
    assert runtime.max_tabs == 10


def test_available_false_when_disabled():
    """disabled 实例的 available 属性应始终为 False。"""
    runtime = BrowserRuntime(enabled=False)
    assert runtime.available is False


def test_available_false_when_cdp_not_responding():
    """CDP 端口无响应时，available 应为 False。"""
    runtime = BrowserRuntime(enabled=True)
    assert runtime.available is False


def test_available_true_when_cdp_responding():
    """CDP 端口可响应时，available 应为 True。"""
    runtime = BrowserRuntime(enabled=True)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert runtime.available is True


def test_start_returns_false_when_disabled():
    """disabled 时 start() 应直接返回 False，不尝试启动 Chrome。"""
    runtime = BrowserRuntime(enabled=False)
    with patch.object(runtime, "_find_chrome") as mock_find:
        result = runtime.start()
    assert result is False
    mock_find.assert_not_called()


def test_start_returns_false_when_chrome_not_found():
    """找不到 Chrome 时 start() 应返回 False。"""
    runtime = BrowserRuntime(enabled=True)
    with patch.object(runtime, "_find_chrome", return_value=None):
        result = runtime.start()
    assert result is False


def test_stop_handles_no_process():
    """没有进程时 stop() 应安全地无操作。"""
    runtime = BrowserRuntime(enabled=True)
    runtime._process = None
    runtime.stop()  # 不应抛出任何异常


def test_stop_terminates_process():
    """stop() 应先 terminate，进程正常退出后 _process 置 None。"""
    runtime = BrowserRuntime(enabled=True)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None  # 进程存活
    mock_proc.wait.return_value = 0
    runtime._process = mock_proc

    runtime.stop()

    mock_proc.terminate.assert_called_once()
    assert runtime._process is None


def test_health_running():
    """CDP 可达时，health() 应返回 status='running' 及版本信息。"""
    import json
    import urllib.request

    runtime = BrowserRuntime(enabled=True, debug_port=9222)

    # _cdp_alive 检查（available 属性用）
    alive_resp = MagicMock()
    alive_resp.status = 200
    alive_resp.__enter__ = lambda s: s
    alive_resp.__exit__ = MagicMock(return_value=False)

    version_resp = MagicMock()
    version_resp.read.return_value = json.dumps({"Browser": "Chrome/120.0.0.0"}).encode()
    version_resp.__enter__ = lambda s: s
    version_resp.__exit__ = MagicMock(return_value=False)

    list_resp = MagicMock()
    list_resp.read.return_value = json.dumps([
        {"type": "page", "id": "1"},
        {"type": "page", "id": "2"},
        {"type": "background_page", "id": "3"},
    ]).encode()
    list_resp.__enter__ = lambda s: s
    list_resp.__exit__ = MagicMock(return_value=False)

    responses = [alive_resp, version_resp, list_resp]
    with patch("urllib.request.urlopen", side_effect=responses):
        result = runtime.health()

    assert result["status"] == "running"
    assert result["chrome_version"] == "Chrome/120.0.0.0"
    assert result["tabs"] == 2
    assert result["debug_port"] == 9222


# ------------------------------------------------------------------
# Tab pool tests
# ------------------------------------------------------------------

def test_tab_lease_expired():
    lease = TabLease(tab_id="page1", purpose="read", department="engineering", ttl_s=0)
    # ttl_s=0 means immediately expired
    time.sleep(0.01)
    assert lease.expired


def test_tab_lease_not_expired():
    lease = TabLease(tab_id="page1", purpose="read", department="engineering", ttl_s=300)
    assert not lease.expired


def test_tab_pool_acquire_within_limit():
    rt = BrowserRuntime(enabled=True, max_tabs=2)
    tab = rt._acquire_tab_internal("read", "engineering")
    assert tab is not None
    assert len(rt._tabs) == 1
    assert tab.purpose == "read"
    assert tab.department == "engineering"


def test_tab_pool_acquire_over_limit():
    rt = BrowserRuntime(enabled=True, max_tabs=1)
    t1 = rt._acquire_tab_internal("read", "engineering")
    assert t1 is not None
    t2 = rt._acquire_tab_internal("read", "operations")
    assert t2 is None


def test_release_tab():
    rt = BrowserRuntime(enabled=True, max_tabs=5)
    t1 = rt._acquire_tab_internal("read", "engineering")
    assert len(rt._tabs) == 1
    rt._release_tab_internal(t1.tab_id)
    assert len(rt._tabs) == 0


def test_reap_zombie_tabs():
    rt = BrowserRuntime(enabled=True, max_tabs=5)
    t1 = rt._acquire_tab_internal("read", "engineering")
    t2 = rt._acquire_tab_internal("interact", "operations")
    # Make t1 expired by setting _created_at in the past
    rt._tabs[t1.tab_id]._created_at = time.monotonic() - 400
    reaped = rt._reap_zombie_tabs_internal()
    assert reaped == 1
    assert t1.tab_id not in rt._tabs
    assert t2.tab_id in rt._tabs
