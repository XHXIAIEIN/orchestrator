import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from src.core.browser_runtime import BrowserRuntime


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


def test_available_false_when_process_none():
    """enabled=True 但无进程时，available 应为 False。"""
    runtime = BrowserRuntime(enabled=True)
    assert runtime._process is None
    assert runtime.available is False


def test_available_false_when_process_exited():
    """进程已退出时，available 应为 False。"""
    runtime = BrowserRuntime(enabled=True)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 0  # 进程已退出
    runtime._process = mock_proc
    assert runtime.available is False


def test_available_true_when_process_running():
    """进程存活时，available 应为 True。"""
    runtime = BrowserRuntime(enabled=True)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None  # 进程存活
    runtime._process = mock_proc
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
    """进程存活且 CDP 可达时，health() 应返回 status='running' 及版本信息。"""
    import json
    import urllib.request

    runtime = BrowserRuntime(enabled=True, debug_port=9222)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    runtime._process = mock_proc

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

    responses = [version_resp, list_resp]
    with patch("urllib.request.urlopen", side_effect=responses):
        result = runtime.health()

    assert result["status"] == "running"
    assert result["chrome_version"] == "Chrome/120.0.0.0"
    assert result["tabs"] == 2
    assert result["debug_port"] == 9222
