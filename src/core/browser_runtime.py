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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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

_TTL = {"read": 300, "interact": 600}


@dataclass
class TabLease:
    tab_id: str
    purpose: str           # "read" | "interact"
    department: str
    ttl_s: int = 300
    _created_at: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self._created_at) > self.ttl_s


class CDPClient:
    """同步 CDP 客户端 — 通过 WebSocket 发送 CDP 命令并等待响应。"""

    def __init__(self, ws_url: str, timeout: float = 30):
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws = None
        self._msg_id = 0

    def connect(self):
        """建立 WebSocket 连接。"""
        from websockets.sync.client import connect as ws_connect
        self._ws = ws_connect(self._ws_url, close_timeout=5)
        return self

    def close(self):
        """关闭连接。"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, method: str, params: dict = None) -> dict:
        """发送 CDP 命令，等待匹配 id 的响应（跳过事件消息）。"""
        if not self._ws:
            raise RuntimeError("CDPClient not connected")
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(msg))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            except TimeoutError:
                break
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error'].get('message', data['error'])}")
                return data.get("result", {})
            # else: it's an event, skip it
        raise TimeoutError(f"CDP timeout waiting for response to {method}")


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
        self._tabs: dict[str, TabLease] = {}

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
        """True 当且仅当：enabled=True 且 CDP 端口可响应。
        注意：Chrome 主进程在 Windows 上可能立即退出（多进程架构），
        实际工作由子进程完成，所以不能只检查 _process.poll()。
        """
        if not self.enabled:
            return False
        if not self._cdp_alive:
            return False
        return True

    @property
    def _cdp_alive(self) -> bool:
        """检查 CDP 端口是否响应。"""
        try:
            url = f"http://127.0.0.1:{self.debug_port}/json/version"
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

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
            # Windows 某些环境下 subprocess.DEVNULL 会触发 [WinError 6] 句柄无效
            # 改用显式打开 os.devnull 文件句柄
            devnull = open(os.devnull, 'w')
            self._process = subprocess.Popen(
                args,
                stdout=devnull,
                stderr=devnull,
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
        """优雅地终止 Chrome 进程。
        Windows 上 Chrome 主进程可能已退出（子进程接管），
        所以还需要通过 CDP 发送关闭命令或杀进程树。
        """
        # 先尝试通过 CDP 关闭浏览器（最可靠的方式）
        if self._cdp_alive:
            try:
                ws_url = self.cdp_url()
                if ws_url:
                    cdp = CDPClient(ws_url, timeout=5)
                    cdp.connect()
                    try:
                        cdp.send("Browser.close")
                    except Exception:
                        pass
                    finally:
                        cdp.close()
                    time.sleep(1)
            except Exception:
                pass

        # 再处理主进程
        if self._process is not None:
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
            log.info(f"browser: Chrome stopped (original PID={pid})")

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

    # ------------------------------------------------------------------
    # Tab pool management
    # ------------------------------------------------------------------

    def _reap_zombie_tabs_internal(self) -> int:
        """清除已过期的 tab lease，返回清除数量。"""
        expired_ids = [tid for tid, lease in self._tabs.items() if lease.expired]
        for tid in expired_ids:
            log.debug(f"browser: reaping zombie tab {tid} (purpose={self._tabs[tid].purpose}, dept={self._tabs[tid].department})")
            del self._tabs[tid]
        return len(expired_ids)

    def _acquire_tab_internal(self, purpose: str, department: str) -> Optional[TabLease]:
        """申请一个 tab lease。先清理僵尸，再检查容量上限。池满返回 None。"""
        self._reap_zombie_tabs_internal()
        if len(self._tabs) >= self.max_tabs:
            log.warning(f"browser: tab pool exhausted (max_tabs={self.max_tabs}), cannot acquire for {department}/{purpose}")
            return None
        ttl = _TTL.get(purpose, 300)
        tab_id = str(uuid.uuid4())
        lease = TabLease(tab_id=tab_id, purpose=purpose, department=department, ttl_s=ttl)
        self._tabs[tab_id] = lease
        log.debug(f"browser: acquired tab {tab_id} for {department}/{purpose} (ttl={ttl}s)")
        return lease

    def _release_tab_internal(self, tab_id: str) -> None:
        """释放指定 tab lease。"""
        if tab_id in self._tabs:
            lease = self._tabs.pop(tab_id)
            log.debug(f"browser: released tab {tab_id} (purpose={lease.purpose}, dept={lease.department})")

    # ------------------------------------------------------------------
    # CDP client & page management
    # ------------------------------------------------------------------

    def new_cdp_client(self, page_ws_url: str) -> "CDPClient":
        """创建连接到指定页面的 CDP 客户端（已连接）。"""
        client = CDPClient(page_ws_url, timeout=30)
        client.connect()
        return client

    def open_page(self, url: str = "about:blank") -> dict:
        """通过 CDP HTTP API 创建新 tab，返回 page info。"""
        if not self.available:
            raise RuntimeError("BrowserRuntime not available")
        import urllib.parse
        encoded = urllib.parse.quote(url, safe="")
        req_url = f"http://127.0.0.1:{self.debug_port}/json/new?{encoded}"
        with urllib.request.urlopen(req_url, timeout=10) as resp:
            return json.loads(resp.read())

    def close_page(self, page_id: str):
        """关闭指定页面。"""
        if not self.available:
            return
        req_url = f"http://127.0.0.1:{self.debug_port}/json/close/{page_id}"
        try:
            urllib.request.urlopen(req_url, timeout=5)
        except Exception:
            pass

    def list_pages(self) -> list[dict]:
        """列出所有打开的页面。"""
        if not self.available:
            return []
        req_url = f"http://127.0.0.1:{self.debug_port}/json/list"
        with urllib.request.urlopen(req_url, timeout=5) as resp:
            return json.loads(resp.read())


# 模块级单例
_runtime: BrowserRuntime | None = None


def get_browser_runtime() -> BrowserRuntime:
    global _runtime
    if _runtime is None:
        _runtime = BrowserRuntime.from_env()
    return _runtime
