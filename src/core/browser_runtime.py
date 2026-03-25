"""
BrowserRuntime — Chrome 进程生命周期管理。
管理一个通过 CDP（Chrome DevTools Protocol）通信的隔离 Chrome 实例。
不依赖任何第三方库，纯 stdlib。
"""
import json
import logging
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# 找 repo 根目录（包含 departments/ 和 src/ 的目录）
def _find_repo_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "departments").exists() and (p / "src").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent.parent

_REPO_ROOT = _find_repo_root()

_DEFAULT_USER_DATA_DIR = str(_REPO_ROOT / ".chrome_data")

# Windows 常见 Chrome 安装路径
_WINDOWS_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
]

# macOS 常见路径
_MACOS_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

_CHROME_WHICH_NAMES = ["chromium", "google-chrome", "chromium-browser", "chrome"]


class BrowserRuntime:
    def __init__(
        self,
        enabled: bool = False,
        chrome_path: str | None = None,
        debug_port: int = 9222,
        headless: bool = True,
        user_data_dir: str = _DEFAULT_USER_DATA_DIR,
        max_tabs: int = 5,
    ):
        self.enabled = enabled
        self.chrome_path = chrome_path
        self.debug_port = debug_port
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.max_tabs = max_tabs

        self._process: subprocess.Popen | None = None

    @classmethod
    def from_env(cls) -> "BrowserRuntime":
        """从环境变量构建实例。"""
        enabled = os.environ.get("BROWSER_RUNTIME_ENABLED", "").lower() in ("1", "true", "yes")
        chrome_path = os.environ.get("BROWSER_CHROME_PATH") or None
        debug_port = int(os.environ.get("BROWSER_DEBUG_PORT", "9222"))
        headless = os.environ.get("BROWSER_HEADLESS", "true").lower() not in ("0", "false", "no")
        user_data_dir = os.environ.get("BROWSER_USER_DATA_DIR", _DEFAULT_USER_DATA_DIR)
        max_tabs = int(os.environ.get("BROWSER_MAX_TABS", "5"))
        return cls(
            enabled=enabled,
            chrome_path=chrome_path,
            debug_port=debug_port,
            headless=headless,
            user_data_dir=user_data_dir,
            max_tabs=max_tabs,
        )

    @property
    def available(self) -> bool:
        """True 当且仅当：enabled=True 且 Chrome 进程存活。"""
        if not self.enabled:
            return False
        if self._process is None:
            return False
        return self._process.poll() is None

    def _find_chrome(self) -> str | None:
        """自动检测系统中可用的 Chrome/Chromium 路径。"""
        # 1. 用户指定路径
        if self.chrome_path:
            if Path(self.chrome_path).exists():
                return self.chrome_path
            log.warning(f"browser: user-specified chrome_path not found: {self.chrome_path}")

        # 2. PATH 中搜索
        for name in _CHROME_WHICH_NAMES:
            found = shutil.which(name)
            if found:
                log.debug(f"browser: found chrome via which: {found}")
                return found

        # 3. 平台特定路径
        system = platform.system()
        if system == "Windows":
            for path in _WINDOWS_CHROME_PATHS:
                if Path(path).exists():
                    log.debug(f"browser: found chrome at well-known Windows path: {path}")
                    return path
        elif system == "Darwin":
            for path in _MACOS_CHROME_PATHS:
                if Path(path).exists():
                    log.debug(f"browser: found chrome at well-known macOS path: {path}")
                    return path

        log.warning("browser: Chrome/Chromium not found on this system")
        return None

    def start(self) -> bool:
        """启动 Chrome 进程，等待 CDP 就绪。返回是否成功。"""
        if not self.enabled:
            log.info("browser: BrowserRuntime is disabled, skipping start")
            return False

        chrome_exe = self._find_chrome()
        if not chrome_exe:
            log.error("browser: cannot start — Chrome not found")
            return False

        # 确保 user_data_dir 存在
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        args = [
            chrome_exe,
            f"--remote-debugging-port={self.debug_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
        ]

        if self.headless:
            args += [
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-session-crashed-bubble",
                "--disable-gpu",
            ]

        log.info(f"browser: launching Chrome on port {self.debug_port} (headless={self.headless})")
        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            log.error(f"browser: failed to launch Chrome: {e}")
            return False

        if not self._wait_for_cdp():
            log.error(f"browser: Chrome launched but CDP not ready on port {self.debug_port}")
            self.stop()
            return False

        log.info(f"browser: Chrome ready, PID={self._process.pid}")
        return True

    def stop(self) -> None:
        """优雅地终止 Chrome 进程。"""
        if self._process is None:
            return

        pid = self._process.pid
        if self._process.poll() is None:
            log.info(f"browser: terminating Chrome PID={pid}")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning(f"browser: Chrome PID={pid} didn't exit in 5s, killing")
                self._process.kill()
                self._process.wait()

        self._process = None
        log.info(f"browser: Chrome PID={pid} stopped")

    def _wait_for_cdp(self, timeout: int = 15) -> bool:
        """轮询 CDP /json/version 直到就绪或超时。"""
        url = f"http://127.0.0.1:{self.debug_port}/json/version"
        deadline = time.time() + timeout
        interval = 0.3

        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    data = json.loads(resp.read().decode())
                    if data:
                        log.debug(f"browser: CDP ready, browser={data.get('Browser', '?')}")
                        return True
            except Exception:
                pass
            time.sleep(interval)

        return False

    def cdp_url(self) -> str | None:
        """返回 WebSocket debugger URL（来自 /json/version）。"""
        if not self.available:
            return None

        url = f"http://127.0.0.1:{self.debug_port}/json/version"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            ws_url = data.get("webSocketDebuggerUrl")
            return ws_url
        except Exception as e:
            log.warning(f"browser: failed to get CDP url: {e}")
            return None

    def health(self) -> dict:
        """返回运行时健康状态字典。"""
        if not self.enabled:
            return {
                "status": "disabled",
                "chrome_version": None,
                "debug_port": self.debug_port,
                "headless": self.headless,
                "tabs": 0,
            }

        if not self.available:
            return {
                "status": "unavailable",
                "chrome_version": None,
                "debug_port": self.debug_port,
                "headless": self.headless,
                "tabs": 0,
            }

        # 获取 Chrome 版本和 tab 数
        chrome_version = None
        tabs_count = 0

        try:
            version_url = f"http://127.0.0.1:{self.debug_port}/json/version"
            with urllib.request.urlopen(version_url, timeout=3) as resp:
                data = json.loads(resp.read().decode())
            chrome_version = data.get("Browser")
        except Exception as e:
            log.warning(f"browser: health check version failed: {e}")

        try:
            list_url = f"http://127.0.0.1:{self.debug_port}/json/list"
            with urllib.request.urlopen(list_url, timeout=3) as resp:
                tabs = json.loads(resp.read().decode())
            tabs_count = len([t for t in tabs if t.get("type") == "page"])
        except Exception as e:
            log.warning(f"browser: health check tabs failed: {e}")

        return {
            "status": "running",
            "chrome_version": chrome_version,
            "debug_port": self.debug_port,
            "headless": self.headless,
            "tabs": tabs_count,
        }


# 模块级单例
_runtime: BrowserRuntime | None = None


def get_browser_runtime() -> BrowserRuntime:
    global _runtime
    if _runtime is None:
        _runtime = BrowserRuntime.from_env()
    return _runtime
