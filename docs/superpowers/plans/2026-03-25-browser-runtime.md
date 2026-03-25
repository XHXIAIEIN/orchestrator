# BrowserRuntime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Chrome browser as a detachable infrastructure component — instance management, CDP connection, tab pool, and health checks.

**Architecture:** BrowserRuntime sits alongside EventsDB/EventBus/LLMRouter in `src/core/`. It manages an isolated Chrome process via CDP over WebSocket, with a tab pool (acquire/release/reap) for concurrent department usage. Everything gated by `BROWSER_RUNTIME_ENABLED` env var.

**Tech Stack:** Python 3.12, `websockets` library, Chrome DevTools Protocol (CDP), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-browser-runtime-design.md`

---

## File Structure

```
src/core/browser_runtime.py    ← Chrome process management + CDP connection + Tab pool
tests/core/test_browser_runtime.py  ← Unit tests (mocked CDP)
requirements.txt               ← Add websockets dependency
src/core/health.py             ← Add _check_browser() section
src/scheduler.py               ← Register BrowserRuntime startup/shutdown
```

---

### Task 1: Add websockets dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add websockets to requirements.txt**

Add under `# Core (required)`:

```
websockets>=14.0
```

- [ ] **Step 2: Install and verify**

Run: `pip install websockets`
Expected: installs successfully, zero transitive dependencies

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add websockets for CDP communication"
```

---

### Task 2: BrowserRuntime — Chrome process lifecycle

**Files:**
- Create: `src/core/browser_runtime.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_browser_runtime.py`

- [ ] **Step 1: Write failing test for Chrome detection**

```python
# tests/core/test_browser_runtime.py
import pytest
from unittest.mock import patch, MagicMock
from src.core.browser_runtime import BrowserRuntime

def test_find_chrome_returns_path_when_exists():
    """Chrome 可执行文件存在时返回路径。"""
    rt = BrowserRuntime(enabled=True)
    with patch("shutil.which", return_value="/usr/bin/chromium"):
        path = rt._find_chrome()
    assert path == "/usr/bin/chromium"

def test_find_chrome_returns_none_when_missing():
    """Chrome 不存在时返回 None。"""
    rt = BrowserRuntime(enabled=True)
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.exists", return_value=False):
            path = rt._find_chrome()
    assert path is None

def test_runtime_disabled_by_env():
    """BROWSER_RUNTIME_ENABLED=false 时 available 返回 False。"""
    rt = BrowserRuntime(enabled=False)
    assert rt.available is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_browser_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.browser_runtime'`

- [ ] **Step 3: Write BrowserRuntime skeleton**

```python
# src/core/browser_runtime.py
"""
BrowserRuntime — Chrome 浏览器运行时。
可拆卸基础设施组件，跟 EventsDB、EventBus、LLMRouter 同级。
不可用时其他组件照常运行。
"""
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Well-known Chrome paths per platform
_CHROME_CANDIDATES = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "linux": [],  # rely on shutil.which("chromium", "google-chrome", "chromium-browser")
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    ],
}

_CHROME_NAMES = ["chromium", "google-chrome", "chromium-browser", "chrome"]

# Default Chrome flags for isolated debug instance
_CHROME_FLAGS = [
    "--remote-debugging-port={port}",
    "--user-data-dir={user_data_dir}",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-sync",
]
_CHROME_FLAGS_HEADLESS = [
    "--headless=new",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-gpu",
]


class BrowserRuntime:
    """
    Chrome 浏览器运行时 — 可拆卸基础设施组件。

    Usage:
        rt = BrowserRuntime.from_env()
        rt.start()         # 启动 Chrome
        assert rt.available
        rt.stop()          # 关闭 Chrome
    """

    def __init__(
        self,
        enabled: bool = True,
        chrome_path: Optional[str] = None,
        debug_port: int = 9222,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        max_tabs: int = 5,
    ):
        self._enabled = enabled
        self._chrome_path = chrome_path
        self._debug_port = debug_port
        self._headless = headless
        self._user_data_dir = user_data_dir or str(_REPO_ROOT / "data" / "browser_profile")
        self._max_tabs = max_tabs
        self._process: Optional[subprocess.Popen] = None
        self._chrome_version: Optional[str] = None

    @classmethod
    def from_env(cls) -> "BrowserRuntime":
        """从环境变量构造（docker-compose / .env 驱动）。"""
        return cls(
            enabled=os.environ.get("BROWSER_RUNTIME_ENABLED", "true").lower() == "true",
            chrome_path=os.environ.get("BROWSER_CHROME_PATH"),
            debug_port=int(os.environ.get("BROWSER_DEBUG_PORT", "9222")),
            headless=os.environ.get("BROWSER_HEADLESS", "false").lower() == "true",
            user_data_dir=os.environ.get("BROWSER_USER_DATA_DIR"),
            max_tabs=int(os.environ.get("BROWSER_MAX_TABS", "5")),
        )

    @property
    def available(self) -> bool:
        """运行时是否可用（已启用 + Chrome 进程存活）。"""
        if not self._enabled:
            return False
        if self._process is None:
            return False
        return self._process.poll() is None

    def _find_chrome(self) -> Optional[str]:
        """检测系统中已安装的 Chrome/Chromium。"""
        # 用户指定的路径优先
        if self._chrome_path:
            if Path(self._chrome_path).exists():
                return self._chrome_path
            log.warning(f"browser: specified chrome_path not found: {self._chrome_path}")

        # shutil.which 查找
        import sys
        for name in _CHROME_NAMES:
            found = shutil.which(name)
            if found:
                return found

        # 平台特定路径
        platform = sys.platform
        for candidate in _CHROME_CANDIDATES.get(platform, []):
            if Path(candidate).exists():
                return candidate

        return None

    def start(self) -> bool:
        """启动隔离 Chrome 实例。成功返回 True。"""
        if not self._enabled:
            log.info("browser: runtime disabled by config")
            return False

        chrome = self._find_chrome()
        if not chrome:
            log.warning("browser: no Chrome/Chromium found, runtime unavailable")
            self._enabled = False
            return False

        # 确保 user_data_dir 存在
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)

        # 构建启动参数
        flags = [f.format(port=self._debug_port, user_data_dir=self._user_data_dir)
                 for f in _CHROME_FLAGS]
        if self._headless:
            flags.extend(_CHROME_FLAGS_HEADLESS)

        cmd = [chrome] + flags
        log.info(f"browser: starting Chrome — {chrome} (port={self._debug_port}, headless={self._headless})")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.error(f"browser: failed to start Chrome: {e}")
            return False

        # 等待 CDP 端口就绪
        if not self._wait_for_cdp(timeout=15):
            log.error("browser: Chrome started but CDP port not responding")
            self.stop()
            return False

        log.info(f"browser: Chrome ready — version={self._chrome_version}, port={self._debug_port}")
        return True

    def stop(self):
        """优雅关闭 Chrome。"""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            log.info("browser: Chrome stopped")
        self._process = None

    def _wait_for_cdp(self, timeout: float = 15) -> bool:
        """等待 CDP /json/version 端点就绪。"""
        url = f"http://127.0.0.1:{self._debug_port}/json/version"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                    self._chrome_version = data.get("Browser", "unknown")
                    return True
            except (urllib.error.URLError, OSError, json.JSONDecodeError):
                time.sleep(0.5)
        return False

    def cdp_url(self) -> Optional[str]:
        """返回 CDP WebSocket URL（从 /json/version 获取）。"""
        if not self.available:
            return None
        try:
            url = f"http://127.0.0.1:{self._debug_port}/json/version"
            with urllib.request.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read())
                return data.get("webSocketDebuggerUrl")
        except Exception:
            return None

    def health(self) -> dict:
        """健康检查报告。"""
        if not self._enabled:
            return {"status": "disabled"}
        if not self.available:
            return {"status": "unavailable"}

        # 获取打开的页面数
        pages_open = 0
        try:
            url = f"http://127.0.0.1:{self._debug_port}/json/list"
            with urllib.request.urlopen(url, timeout=3) as resp:
                pages = json.loads(resp.read())
                pages_open = len([p for p in pages if p.get("type") == "page"])
        except Exception:
            pass

        return {
            "status": "healthy",
            "chrome_version": self._chrome_version,
            "debug_port": self._debug_port,
            "headless": self._headless,
            "tabs": f"{pages_open}/{self._max_tabs}",
        }
```

- [ ] **Step 4: Create tests/__init__.py and tests/core/__init__.py**

```bash
touch tests/core/__init__.py
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/core/test_browser_runtime.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/browser_runtime.py tests/core/__init__.py tests/core/test_browser_runtime.py
git commit -m "feat(browser): add BrowserRuntime — Chrome process lifecycle management"
```

---

### Task 3: Tab pool — acquire / release / reap

**Files:**
- Modify: `src/core/browser_runtime.py`
- Modify: `tests/core/test_browser_runtime.py`

- [ ] **Step 1: Write failing tests for tab pool**

Append to `tests/core/test_browser_runtime.py`:

```python
import time
from src.core.browser_runtime import TabLease

def test_tab_lease_expired():
    """Tab 超时后 expired 返回 True。"""
    lease = TabLease(tab_id="page1", purpose="read", department="engineering", ttl_s=1)
    assert not lease.expired
    time.sleep(1.1)
    assert lease.expired

def test_tab_pool_acquire_within_limit():
    """max_tabs 内可正常分配。"""
    rt = BrowserRuntime(enabled=True, max_tabs=2)
    rt._tabs = {}  # 模拟空池
    # acquire 需要 CDP 连接，这里测逻辑层
    rt._mock_cdp = True  # 测试钩子
    tab = rt._acquire_tab_internal("read", "engineering")
    assert tab is not None
    assert len(rt._tabs) == 1

def test_tab_pool_acquire_over_limit():
    """超过 max_tabs 时返回 None。"""
    rt = BrowserRuntime(enabled=True, max_tabs=1)
    rt._tabs = {"page1": TabLease("page1", "read", "eng", 300)}
    tab = rt._acquire_tab_internal("read", "operations")
    assert tab is None

def test_reap_zombie_tabs():
    """reap_zombie_tabs 清理过期 tab。"""
    rt = BrowserRuntime(enabled=True, max_tabs=5)
    rt._tabs = {
        "p1": TabLease("p1", "read", "eng", ttl_s=0),   # 已过期
        "p2": TabLease("p2", "interact", "ops", ttl_s=300),  # 未过期
    }
    # 让 p1 过期
    rt._tabs["p1"]._created_at = time.monotonic() - 10
    reaped = rt._reap_zombie_tabs_internal()
    assert reaped == 1
    assert "p1" not in rt._tabs
    assert "p2" in rt._tabs
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/core/test_browser_runtime.py -v -k "tab"`
Expected: FAIL — `ImportError: cannot import name 'TabLease'`

- [ ] **Step 3: Implement TabLease and tab pool methods**

Add to `src/core/browser_runtime.py`:

```python
@dataclass
class TabLease:
    """Tab 租约。"""
    tab_id: str
    purpose: str           # "read" | "interact"
    department: str
    ttl_s: int = 300       # read=300s, interact=600s
    _created_at: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self._created_at) > self.ttl_s
```

Add to `BrowserRuntime.__init__`:
```python
self._tabs: dict[str, TabLease] = {}
```

Add methods to `BrowserRuntime`:
```python
_TTL = {"read": 300, "interact": 600}

def _acquire_tab_internal(self, purpose: str, department: str) -> Optional[TabLease]:
    """内部分配 tab（不涉及 CDP 调用，纯逻辑）。"""
    # 先回收过期的
    self._reap_zombie_tabs_internal()
    if len(self._tabs) >= self._max_tabs:
        log.warning(f"browser: tab pool exhausted ({len(self._tabs)}/{self._max_tabs})")
        return None
    tab_id = f"tab_{int(time.monotonic() * 1000)}"
    ttl = self._TTL.get(purpose, 300)
    lease = TabLease(tab_id=tab_id, purpose=purpose, department=department, ttl_s=ttl)
    self._tabs[tab_id] = lease
    return lease

def _release_tab_internal(self, tab_id: str):
    """归还 tab。"""
    self._tabs.pop(tab_id, None)

def _reap_zombie_tabs_internal(self) -> int:
    """回收超时 tab，返回回收数量。"""
    expired = [tid for tid, lease in self._tabs.items() if lease.expired]
    for tid in expired:
        log.info(f"browser: reaping zombie tab {tid} (dept={self._tabs[tid].department})")
        self._tabs.pop(tid)
    return len(expired)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/core/test_browser_runtime.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/browser_runtime.py tests/core/test_browser_runtime.py
git commit -m "feat(browser): add tab pool with acquire/release/reap lifecycle"
```

---

### Task 4: Health check integration

**Files:**
- Modify: `src/core/health.py`
- Modify: `src/core/browser_runtime.py` (import)

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_browser_runtime.py (append)

def test_health_disabled():
    """禁用时 health 返回 disabled。"""
    rt = BrowserRuntime(enabled=False)
    assert rt.health()["status"] == "disabled"

def test_health_unavailable():
    """未启动时 health 返回 unavailable。"""
    rt = BrowserRuntime(enabled=True)
    assert rt.health()["status"] == "unavailable"
```

- [ ] **Step 2: Run and verify pass** (these should already pass with existing code)

Run: `python -m pytest tests/core/test_browser_runtime.py -v -k "health"`
Expected: PASS

- [ ] **Step 3: Add _check_browser to health.py**

Add to `HealthCheck.run()` report dict:
```python
"browser": self._check_browser(),
```

Add method:
```python
def _check_browser(self) -> dict:
    """检查浏览器运行时状态。"""
    try:
        from src.core.browser_runtime import BrowserRuntime
        rt = BrowserRuntime.from_env()
        info = rt.health()
        if info["status"] not in ("healthy", "disabled"):
            self.issues.append({
                "component": "browser_runtime",
                "severity": "low",
                "summary": f"Browser runtime: {info['status']}",
            })
        return info
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

- [ ] **Step 4: Run full health test**

Run: `python -m pytest tests/ -v -k "health" --no-header`
Expected: PASS (browser section returns "disabled" or "unavailable" in test env)

- [ ] **Step 5: Commit**

```bash
git add src/core/health.py tests/core/test_browser_runtime.py
git commit -m "feat(browser): integrate BrowserRuntime into health checks"
```

---

### Task 5: Scheduler registration

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: Add BrowserRuntime startup to scheduler**

After the Channel layer init block (~line 53), add:

```python
# BrowserRuntime — 可选，浏览器感官层
browser_runtime = None
try:
    from src.core.browser_runtime import BrowserRuntime
    browser_runtime = BrowserRuntime.from_env()
    if browser_runtime._enabled:
        if browser_runtime.start():
            db.write_log(f"BrowserRuntime started: {browser_runtime.health()}", "INFO", "browser")
            log.info(f"BrowserRuntime started: port={browser_runtime._debug_port}")
        else:
            log.info("BrowserRuntime: Chrome not available, running without browser")
    else:
        log.info("BrowserRuntime: disabled by BROWSER_RUNTIME_ENABLED=false")
except Exception as e:
    log.warning(f"BrowserRuntime init failed (non-fatal): {e}")
```

- [ ] **Step 2: Add zombie tab reaper job**

After the other scheduler jobs, add:

```python
if browser_runtime and browser_runtime.available:
    s.add_job(
        lambda: browser_runtime._reap_zombie_tabs_internal(),
        "interval", seconds=60, id="browser_tab_reaper"
    )
```

- [ ] **Step 3: Add graceful shutdown**

Add atexit or signal handler at end of `start()` before `s.start()`:

```python
import atexit
if browser_runtime:
    atexit.register(browser_runtime.stop)
```

- [ ] **Step 4: Verify no import errors**

Run: `python -c "from src.scheduler import start; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/scheduler.py
git commit -m "feat(browser): register BrowserRuntime in scheduler lifecycle"
```

---

### Task 6: Integration smoke test

**Files:**
- Create: `tests/core/test_browser_integration.py`

- [ ] **Step 1: Write integration test (skip if no Chrome)**

```python
# tests/core/test_browser_integration.py
import pytest
import shutil
from src.core.browser_runtime import BrowserRuntime

def _has_chrome() -> bool:
    rt = BrowserRuntime(enabled=True)
    return rt._find_chrome() is not None

@pytest.mark.skipif(not _has_chrome(), reason="Chrome/Chromium not installed")
class TestBrowserIntegration:
    """集成测试 — 需要实际 Chrome 进程。CI 环境可跳过。"""

    def test_start_stop_lifecycle(self, tmp_path):
        rt = BrowserRuntime(
            enabled=True,
            headless=True,
            user_data_dir=str(tmp_path / "chrome_test"),
            debug_port=19222,  # 避免冲突
        )
        assert rt.start()
        assert rt.available
        assert rt.health()["status"] == "healthy"
        assert rt._chrome_version is not None

        # CDP URL 可获取
        ws_url = rt.cdp_url()
        assert ws_url is not None
        assert "ws://" in ws_url

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
        assert rt.start()

        # 分配 tab
        t1 = rt._acquire_tab_internal("read", "engineering")
        t2 = rt._acquire_tab_internal("interact", "operations")
        assert t1 is not None
        assert t2 is not None

        # 超出限制
        t3 = rt._acquire_tab_internal("read", "quality")
        assert t3 is None

        # 释放后可再分配
        rt._release_tab_internal(t1.tab_id)
        t4 = rt._acquire_tab_internal("read", "quality")
        assert t4 is not None

        rt.stop()
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/core/test_browser_integration.py -v`
Expected: PASS (or SKIP if no Chrome)

- [ ] **Step 3: Commit**

```bash
git add tests/core/test_browser_integration.py
git commit -m "test(browser): add integration smoke tests for BrowserRuntime"
```

---

## Summary

After these 6 tasks, we have:
- `BrowserRuntime` — Chrome process lifecycle (start/stop/restart)
- Tab pool — acquire/release/reap with per-department tracking
- Health check integration — shows in existing health report
- Scheduler registration — auto-start with zombie reaper
- Integration tests — validates real Chrome works

**Next phase (separate plan):** BrowserTools — navigate/screenshot/snapshot/click/fill via CDP WebSocket.
