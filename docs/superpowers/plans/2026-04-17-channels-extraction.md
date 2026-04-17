# Channels Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract IM protocol adapters (`telegram/`, `wechat/`, `wecom/`) and their shared binary/protocol utilities from `orchestrator/src/channels/` into a new standalone pip-installable repo `orchestrator-channels/`, so orchestrator itself contains only agent-facing channel code (chat engine, session, routing, registry, bridge).

**Architecture:** New repo `orchestrator-channels/` is an independent Python package with **zero imports from orchestrator**. Orchestrator depends on it via editable pip install. The current coupling `telegram/handler.py → src.channels.chat` is broken with dependency injection: adapters accept a `chat_handler: Callable` in their constructor and invoke `self._chat_handler(...)` instead of importing orchestrator's agent engine. Similarly, `src.core.circuit_breaker` is injected as a constructor arg rather than imported. Orchestrator-side shim files (`src/channels/base.py`, `media.py`, `telegram/__init__.py`, etc.) re-export from the new package, so every existing call site in orchestrator (`from src.channels.media import MediaType`) keeps working without change.

**Tech Stack:** Python 3.11+, setuptools (`pyproject.toml`), pip editable install (`-e`), pytest.

---

## File Structure

**New repo** `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/`:

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata, deps, build config |
| `README.md` | One-paragraph description + install instructions |
| `.gitignore` | Python standard ignores |
| `src/orchestrator_channels/__init__.py` | Re-exports `Channel`, `ChannelMessage` |
| `src/orchestrator_channels/base.py` | `Channel` ABC + `ChannelMessage` dataclass (moved) |
| `src/orchestrator_channels/config.py` | Channel config schema + loader (moved) |
| `src/orchestrator_channels/media.py` | `MediaType`, `MediaAttachment`, `guess_mime`, `save_media_buffer` (moved) |
| `src/orchestrator_channels/boundary_nonce.py` | `wrap_untrusted_block` security util (moved) |
| `src/orchestrator_channels/message_splitter.py` | Text splitting for platform message-length limits (moved) |
| `src/orchestrator_channels/log_sanitizer.py` | Secret redaction in logs (moved) |
| `src/orchestrator_channels/telegram/__init__.py` | Re-exports `TelegramChannel` |
| `src/orchestrator_channels/telegram/tg_api.py` | Bot API HTTP wrapper (moved, breaker injected) |
| `src/orchestrator_channels/telegram/sender.py` | Outbound message formatter (moved) |
| `src/orchestrator_channels/telegram/handler.py` | Inbound update handler (moved, chat_handler injected) |
| `src/orchestrator_channels/telegram/channel.py` | Main adapter class (moved, both DI params) |
| `src/orchestrator_channels/wechat/__init__.py` | Re-exports `WeChatChannel`, `load_credentials` |
| `src/orchestrator_channels/wechat/api.py` | iLink Bot API (moved) |
| `src/orchestrator_channels/wechat/cdn.py` | Media CDN upload/download (moved) |
| `src/orchestrator_channels/wechat/utils.py` | SILK→WAV + text helpers (moved) |
| `src/orchestrator_channels/wechat/login.py` | Credential persistence (moved) |
| `src/orchestrator_channels/wechat/sender.py` | Outbound formatter (moved) |
| `src/orchestrator_channels/wechat/handler.py` | Inbound handler (moved, chat_handler injected) |
| `src/orchestrator_channels/wechat/channel.py` | Main adapter (moved, chat_handler injected) |
| `src/orchestrator_channels/wechat/wechat-login.bat` | Login launcher script (moved verbatim) |
| `src/orchestrator_channels/wecom/__init__.py` | Re-exports `WeComChannel` |
| `src/orchestrator_channels/wecom/channel.py` | Webhook adapter (moved) |
| `tests/test_smoke.py` | Import + construction smoke tests for all three adapters |

**Orchestrator changes** `D:/Users/Administrator/Documents/GitHub/orchestrator/`:

| File | Change |
|---|---|
| `requirements.txt` | Append `-e ../orchestrator-channels` |
| `src/channels/base.py` | Replace with shim re-export |
| `src/channels/config.py` | Replace with shim re-export |
| `src/channels/media.py` | Replace with shim re-export |
| `src/channels/boundary_nonce.py` | Replace with shim re-export |
| `src/channels/message_splitter.py` | Replace with shim re-export |
| `src/channels/log_sanitizer.py` | Replace with shim re-export |
| `src/channels/telegram/__init__.py` | Replace with shim re-export |
| `src/channels/telegram/{channel,handler,sender,tg_api}.py` | Move to `.trash/2026-04-17-channels-extraction/telegram/` |
| `src/channels/wechat/__init__.py` | Replace with shim re-export |
| `src/channels/wechat/{api,cdn,utils,login,sender,handler,channel}.py` | Move to `.trash/...` |
| `src/channels/wechat/wechat-login.bat` | Move to `.trash/...` |
| `src/channels/wecom/__init__.py` | Replace with shim re-export |
| `src/channels/wecom/channel.py` | Move to `.trash/...` |
| `src/channels/registry.py` | Inject `chat_handler` + `breaker` when constructing adapters |
| `tests/integration/test_channels_shim.py` | Create — verify all shim imports resolve to new package |

---

## Phase 0: Snapshot and prep

### Task 0: Verify current state + backup

**Files:**
- Read: `src/channels/telegram/`, `wechat/`, `wecom/`

- [ ] **Step 0.1: Confirm orchestrator working tree is clean**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && git status --porcelain`
Expected: empty output (clean tree)

- [ ] **Step 0.2: Create trash directory for removed originals**

Run: `mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator/.trash/2026-04-17-channels-extraction/{telegram,wechat,wecom,shared}`
Expected: silent success

- [ ] **Step 0.3: Create a safety branch for the extraction**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
git checkout -b refactor/channels-extraction
```

Expected: `Switched to a new branch 'refactor/channels-extraction'`

---

## Phase 1: Scaffold the new repo

### Task 1: Initialize orchestrator-channels repository

**Files:**
- Create: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/.git/`
- Create: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/pyproject.toml`
- Create: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/.gitignore`
- Create: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/README.md`

- [ ] **Step 1.1: Create directory and git init**

```bash
mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator-channels
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git init -b main
```

Expected: `Initialized empty Git repository`

- [ ] **Step 1.2: Create `pyproject.toml`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "orchestrator-channels"
version = "0.1.0"
description = "IM protocol adapters (Telegram/WeChat/WeCom) extracted from orchestrator"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "httpx>=0.25",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 1.3: Create `.gitignore`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/.gitignore`

```
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.egg-info/
dist/
build/
.venv/
.env
```

- [ ] **Step 1.4: Create `README.md`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/README.md`

```markdown
# orchestrator-channels

IM protocol adapters extracted from [orchestrator](../orchestrator). Supports Telegram, WeChat (iLink), and WeCom webhook.

## Install (editable)

    pip install -e .

## Usage

    from orchestrator_channels.telegram import TelegramChannel

    tg = TelegramChannel(
        token="...",
        chat_id="...",
        chat_handler=my_async_handler,  # Callable[..., Awaitable[str]]
    )
    tg.start()

## Architecture

Each adapter subclasses `orchestrator_channels.base.Channel` and takes a `chat_handler` callback for inbound messages. The package has zero imports from orchestrator — all orchestrator-specific logic (agent dispatch, circuit breaker) is injected via constructor.
```

- [ ] **Step 1.5: Create package directory scaffold**

```bash
mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/telegram
mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/wechat
mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/wecom
mkdir -p D:/Users/Administrator/Documents/GitHub/orchestrator-channels/tests
```

Expected: silent success.

- [ ] **Step 1.6: Create top-level package `__init__.py`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/__init__.py`

```python
"""orchestrator-channels — IM protocol adapters (Telegram/WeChat/WeCom)."""
from orchestrator_channels.base import Channel, ChannelMessage

__all__ = ["Channel", "ChannelMessage"]
__version__ = "0.1.0"
```

- [ ] **Step 1.7: Install the package editable into orchestrator's Python env**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
pip install -e .
```

Expected: `Successfully installed orchestrator-channels-0.1.0`

- [ ] **Step 1.8: Verify the install**

Run: `python -c "import orchestrator_channels; print(orchestrator_channels.__version__, orchestrator_channels.__file__)"`
Expected: `0.1.0 <path containing orchestrator-channels>`

- [ ] **Step 1.9: Commit scaffold**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add pyproject.toml .gitignore README.md src/orchestrator_channels/__init__.py
git commit -m "feat: scaffold orchestrator-channels package"
```

---

## Phase 2: Move `base.py` (the contract) and write first smoke test

### Task 2: Establish the Channel ABC in the new repo

**Files:**
- Create: `orchestrator-channels/src/orchestrator_channels/base.py`
- Create: `orchestrator-channels/tests/test_smoke.py`

- [ ] **Step 2.1: Write failing smoke test**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/tests/test_smoke.py`

```python
"""Smoke tests — package is importable and Channel ABC is usable."""


def test_import_base():
    from orchestrator_channels.base import Channel, ChannelMessage

    assert Channel is not None
    assert ChannelMessage is not None


def test_channel_message_construction():
    from orchestrator_channels.base import ChannelMessage

    m = ChannelMessage(text="hello")
    assert m.text == "hello"
    assert m.priority == "NORMAL"
    assert m.media == []


def test_channel_is_abc():
    import abc
    from orchestrator_channels.base import Channel

    assert abc.ABC in Channel.__mro__
```

- [ ] **Step 2.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_channels.base'`

- [ ] **Step 2.3: Create `base.py` by copying orchestrator's version**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/base.py`

```python
"""
Channel abstract base class — adapter pattern.

Every messaging platform implements a Channel subclass; upstream code only sees
the unified ChannelMessage.
Outbound: orchestrator event bus → formatter → Channel.send()
Inbound:  Channel.start() polling → parse → chat_handler callback
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator_channels.media import MediaAttachment  # noqa: F401


@dataclass
class ChannelMessage:
    """Platform-agnostic message object."""
    text: str                          # Markdown body
    event_type: str = ""               # e.g. "task.completed"
    priority: str = "NORMAL"           # CRITICAL / HIGH / NORMAL / LOW
    department: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    media: list = field(default_factory=list)  # list[MediaAttachment]


class Channel(ABC):
    """Messaging platform adapter base class."""

    name: str = "base"
    enabled: bool = True

    @abstractmethod
    def send(self, message: ChannelMessage) -> bool:
        """Push a message. Return success."""

    def start(self):
        """Start inbound polling. No-op by default."""

    def stop(self):
        """Stop polling."""

    def get_platform_hints(self) -> str:
        """Return platform-specific prompt hints (subclasses override)."""
        return ""

    def __repr__(self):
        return f"<Channel:{self.name} enabled={self.enabled}>"
```

- [ ] **Step 2.4: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: 3 passed

- [ ] **Step 2.5: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/base.py tests/test_smoke.py
git commit -m "feat: add Channel ABC + ChannelMessage (moved from orchestrator)"
```

---

## Phase 3: Move shared utilities

### Task 3: Move `config.py`

**Files:**
- Read: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/config.py` (full content)
- Create: `orchestrator-channels/src/orchestrator_channels/config.py`
- Modify: `orchestrator-channels/tests/test_smoke.py` (append test)

- [ ] **Step 3.1: Append failing test to `test_smoke.py`**

Append to `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/tests/test_smoke.py`:

```python
def test_import_config():
    from orchestrator_channels import config as ch_cfg

    assert hasattr(ch_cfg, "get_channel_config") or callable(getattr(ch_cfg, "load_config", None)) or True
    # Just verify module imports cleanly; exact public API discovered during copy
```

- [ ] **Step 3.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_import_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_channels.config'`

- [ ] **Step 3.3: Copy `config.py` with import rewrite**

Read full content of `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/config.py`. Write to `D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/config.py` verbatim **except** replace any occurrence of `from src.channels.` with `from orchestrator_channels.` and `import src.channels.` with `import orchestrator_channels.`.

- [ ] **Step 3.4: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: 4 passed

- [ ] **Step 3.5: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/config.py tests/test_smoke.py
git commit -m "feat: move channels config module"
```

### Task 4: Move `media.py`, `boundary_nonce.py`, `message_splitter.py`, `log_sanitizer.py`

**Files:**
- Read: 4 source files in `orchestrator/src/channels/`
- Create: 4 corresponding files in `orchestrator-channels/src/orchestrator_channels/`

- [ ] **Step 4.1: Append failing test**

Append to `tests/test_smoke.py`:

```python
def test_import_media():
    from orchestrator_channels.media import MediaType, MediaAttachment, guess_mime
    assert MediaType.IMAGE
    assert guess_mime("a.jpg") in ("image/jpeg", "image/jpg")


def test_import_boundary_nonce():
    from orchestrator_channels.boundary_nonce import wrap_untrusted_block
    wrapped = wrap_untrusted_block("hello")
    assert "hello" in wrapped


def test_import_message_splitter():
    from orchestrator_channels.message_splitter import split_message
    parts = split_message("x" * 10, max_len=3)
    assert all(len(p) <= 3 for p in parts)


def test_import_log_sanitizer():
    from orchestrator_channels.log_sanitizer import install
    assert callable(install)
```

- [ ] **Step 4.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: 4 FAIL (module not found), 4 prior PASS

- [ ] **Step 4.3: Copy `media.py`**

Read `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/media.py`. Write to `orchestrator-channels/src/orchestrator_channels/media.py` with `src.channels.` → `orchestrator_channels.` in every import line.

- [ ] **Step 4.4: Copy `boundary_nonce.py`**

Same procedure: read `orchestrator/src/channels/boundary_nonce.py`, write to `orchestrator-channels/src/orchestrator_channels/boundary_nonce.py` with import rewrite.

- [ ] **Step 4.5: Copy `message_splitter.py`**

Same procedure.

- [ ] **Step 4.6: Copy `log_sanitizer.py`**

Same procedure.

- [ ] **Step 4.7: Run tests to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: 8 passed

- [ ] **Step 4.8: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/{media,boundary_nonce,message_splitter,log_sanitizer}.py tests/test_smoke.py
git commit -m "feat: move shared channel utils (media, boundary_nonce, splitter, sanitizer)"
```

---

## Phase 4: Move Telegram adapter with DI refactor

### Task 5: Move `tg_api.py` with circuit_breaker DI

**Files:**
- Read: `orchestrator/src/channels/telegram/tg_api.py`
- Create: `orchestrator-channels/src/orchestrator_channels/telegram/__init__.py`
- Create: `orchestrator-channels/src/orchestrator_channels/telegram/tg_api.py`

- [ ] **Step 5.1: Append failing test**

Append to `tests/test_smoke.py`:

```python
def test_telegram_api_accepts_breaker():
    from orchestrator_channels.telegram.tg_api import TelegramAPI

    class FakeBreaker:
        def call(self, fn, *a, **k):
            return fn(*a, **k)

    api = TelegramAPI(token="fake", breaker=FakeBreaker(), breaker_error_cls=RuntimeError)
    assert api._breaker is not None
```

- [ ] **Step 5.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_api_accepts_breaker -v`
Expected: FAIL — module missing

- [ ] **Step 5.3: Create empty `telegram/__init__.py`**

Path: `orchestrator-channels/src/orchestrator_channels/telegram/__init__.py`

```python
"""Telegram adapter."""
```

(Leave `TelegramChannel` export for task 8.)

- [ ] **Step 5.4: Create `tg_api.py` with breaker injection**

Read original `orchestrator/src/channels/telegram/tg_api.py`. Write to `orchestrator-channels/src/orchestrator_channels/telegram/tg_api.py` with these edits:

1. Delete line: `from src.core.circuit_breaker import get_breaker, CircuitBreakerError`
2. Rewrite: `from src.channels import config as ch_cfg` → `from orchestrator_channels import config as ch_cfg`
3. In `TelegramAPI.__init__`, add params after existing ones: `breaker=None, breaker_error_cls=None`
4. Any line that calls `get_breaker(...)` — replace with `breaker` arg; store `self._breaker = breaker`
5. Any `except CircuitBreakerError` — replace with `except (breaker_error_cls,) if breaker_error_cls else Exception`. Use: `except (breaker_error_cls if breaker_error_cls else Exception) as e:` guarded with a module-level fallback:

```python
# At top of file, after imports:
class _NullBreaker:
    def call(self, fn, *a, **k):
        return fn(*a, **k)
```

6. Default `self._breaker = breaker if breaker is not None else _NullBreaker()`
7. Store `self._breaker_error_cls = breaker_error_cls`

- [ ] **Step 5.5: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_api_accepts_breaker -v`
Expected: PASS

- [ ] **Step 5.6: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/telegram/__init__.py src/orchestrator_channels/telegram/tg_api.py tests/test_smoke.py
git commit -m "feat: move telegram tg_api with breaker DI"
```

### Task 6: Move `sender.py` verbatim

**Files:**
- Read: `orchestrator/src/channels/telegram/sender.py`
- Create: `orchestrator-channels/src/orchestrator_channels/telegram/sender.py`

- [ ] **Step 6.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_telegram_sender_importable():
    from orchestrator_channels.telegram.sender import TelegramSender, PRIORITY_LEVELS
    assert isinstance(PRIORITY_LEVELS, dict)
    assert "CRITICAL" in PRIORITY_LEVELS
```

- [ ] **Step 6.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_sender_importable -v`
Expected: FAIL

- [ ] **Step 6.3: Copy `sender.py`**

Read `orchestrator/src/channels/telegram/sender.py`. Write to `orchestrator-channels/src/orchestrator_channels/telegram/sender.py` with only import-path rewrites (`src.channels.` → `orchestrator_channels.`). No DI changes — sender has no orchestrator imports except `channels.base`, `channels.config`, `channels.media`, all of which are now under the new package.

- [ ] **Step 6.4: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_sender_importable -v`
Expected: PASS

- [ ] **Step 6.5: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/telegram/sender.py tests/test_smoke.py
git commit -m "feat: move telegram sender"
```

### Task 7: Move `handler.py` with chat_handler DI

**Files:**
- Read: `orchestrator/src/channels/telegram/handler.py`
- Create: `orchestrator-channels/src/orchestrator_channels/telegram/handler.py`

- [ ] **Step 7.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_telegram_handler_accepts_chat_callback():
    from orchestrator_channels.telegram.handler import TelegramHandler

    async def fake_chat(user_id, platform, text, **kwargs):
        return f"echo: {text}"

    h = TelegramHandler(chat_handler=fake_chat, api=None, config={})
    assert h._chat_handler is fake_chat
```

- [ ] **Step 7.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_handler_accepts_chat_callback -v`
Expected: FAIL — module missing

- [ ] **Step 7.3: Copy `handler.py` with chat DI rewrite**

Read `orchestrator/src/channels/telegram/handler.py`. Write to `orchestrator-channels/src/orchestrator_channels/telegram/handler.py` with these edits:

1. Delete line: `from src.channels import chat as chat_engine`
2. Rewrite other `from src.channels.` → `from orchestrator_channels.` in imports
3. In `TelegramHandler.__init__`, add `chat_handler` as first explicit keyword-only param after self: `def __init__(self, *, chat_handler, api, config, ...):`. Store `self._chat_handler = chat_handler`.
4. Find every `chat_engine.do_chat(...)` call. Replace with `await self._chat_handler(...)` preserving the argument list exactly.
5. If any `chat_engine.<other_fn>(...)` exists (e.g. `chat_engine.save_to_inbox`), these are signals that MORE than just `do_chat` is used. For each, add a constructor param with matching name (e.g. `save_to_inbox_handler`) and do the same replacement. Enumerate them from the original file read.

Enumeration (from pre-plan grep): `channels.telegram.handler` only imports `chat as chat_engine` and `channels.chat`. Check the original file for actual `chat_engine.*` call sites:

Run (in orchestrator repo): `grep -n "chat_engine\." D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/telegram/handler.py`

Document the exact call sites in the handler's module docstring:
```python
"""
Telegram inbound handler.

Injected callbacks (via constructor):
- chat_handler: async fn(user_id, platform, text, attachments=None, username=None) -> str
  Replaces `chat_engine.do_chat` from orchestrator.
- [list any others found in the grep above with their replacement params]
"""
```

- [ ] **Step 7.4: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_handler_accepts_chat_callback -v`
Expected: PASS

- [ ] **Step 7.5: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/telegram/handler.py tests/test_smoke.py
git commit -m "feat: move telegram handler with chat_handler DI"
```

### Task 8: Move `channel.py` and wire up the adapter

**Files:**
- Read: `orchestrator/src/channels/telegram/channel.py`
- Create: `orchestrator-channels/src/orchestrator_channels/telegram/channel.py`
- Modify: `orchestrator-channels/src/orchestrator_channels/telegram/__init__.py`

- [ ] **Step 8.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_telegram_channel_full_construction():
    from orchestrator_channels.telegram import TelegramChannel

    async def fake_chat(user_id, platform, text, **kwargs):
        return f"echo: {text}"

    tc = TelegramChannel(
        token="fake",
        chat_id="0",
        chat_handler=fake_chat,
    )
    assert tc.name == "telegram"
    assert tc.enabled is True
```

- [ ] **Step 8.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_telegram_channel_full_construction -v`
Expected: FAIL (TelegramChannel not exported)

- [ ] **Step 8.3: Copy `channel.py` with DI wiring**

Read `orchestrator/src/channels/telegram/channel.py`. Write to `orchestrator-channels/src/orchestrator_channels/telegram/channel.py` with:

1. Delete: `from src.channels import chat as chat_engine`
2. Rewrite other `from src.channels.` → `from orchestrator_channels.` and `from src.channels.telegram.` → `from orchestrator_channels.telegram.`
3. In `TelegramChannel.__init__`, add keyword-only params: `chat_handler`, `breaker=None`, `breaker_error_cls=None`
4. When constructing `TelegramAPI(token=...)`, pass `breaker=breaker, breaker_error_cls=breaker_error_cls`
5. When constructing `TelegramHandler(...)`, pass `chat_handler=chat_handler`
6. Remove any `chat_engine` references in this file — if the channel itself calls `chat_engine.*` directly (not via handler), add a handler param. Enumerate from:

Run: `grep -n "chat_engine\." D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/telegram/channel.py`

For each hit, add a matching DI param.

- [ ] **Step 8.4: Update `telegram/__init__.py` to export**

Path: `orchestrator-channels/src/orchestrator_channels/telegram/__init__.py`

```python
"""Telegram adapter."""
from orchestrator_channels.telegram.channel import TelegramChannel

__all__ = ["TelegramChannel"]
```

- [ ] **Step 8.5: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: all tests pass

- [ ] **Step 8.6: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/telegram/channel.py src/orchestrator_channels/telegram/__init__.py tests/test_smoke.py
git commit -m "feat: move telegram channel with DI wiring (chat_handler + breaker)"
```

---

## Phase 5: Move WeChat adapter

### Task 9: Move WeChat protocol files (`api.py`, `cdn.py`, `utils.py`, `login.py`, `sender.py`)

**Files:**
- Read: 5 source files in `orchestrator/src/channels/wechat/`
- Create: 5 corresponding files in `orchestrator-channels/src/orchestrator_channels/wechat/`
- Create: `orchestrator-channels/src/orchestrator_channels/wechat/__init__.py` (initial empty stub)

- [ ] **Step 9.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_wechat_protocol_imports():
    from orchestrator_channels.wechat.api import get_updates
    from orchestrator_channels.wechat.cdn import CDN_BASE_URL
    from orchestrator_channels.wechat.utils import _silk_to_wav, _split_message
    from orchestrator_channels.wechat.login import load_credentials
    from orchestrator_channels.wechat.sender import WeChatSender, PRIORITY_LEVELS
    assert callable(get_updates)
    assert isinstance(PRIORITY_LEVELS, dict)
```

- [ ] **Step 9.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_wechat_protocol_imports -v`
Expected: FAIL

- [ ] **Step 9.3: Create empty `wechat/__init__.py`**

Path: `orchestrator-channels/src/orchestrator_channels/wechat/__init__.py`

```python
"""WeChat (iLink) adapter."""
```

- [ ] **Step 9.4: Copy `api.py`**

Read `orchestrator/src/channels/wechat/api.py`. Write to `orchestrator-channels/src/orchestrator_channels/wechat/api.py` with `src.channels.` → `orchestrator_channels.` in every import.

- [ ] **Step 9.5: Copy `cdn.py`**

Same procedure.

- [ ] **Step 9.6: Copy `utils.py`**

Same procedure.

- [ ] **Step 9.7: Copy `login.py`**

Same procedure.

- [ ] **Step 9.8: Copy `sender.py`**

Same procedure.

- [ ] **Step 9.9: Copy `wechat-login.bat` verbatim**

```bash
cp D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/wechat/wechat-login.bat \
   D:/Users/Administrator/Documents/GitHub/orchestrator-channels/src/orchestrator_channels/wechat/wechat-login.bat
```

- [ ] **Step 9.10: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py::test_wechat_protocol_imports -v`
Expected: PASS

- [ ] **Step 9.11: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/wechat/ tests/test_smoke.py
git commit -m "feat: move wechat protocol modules (api, cdn, utils, login, sender)"
```

### Task 10: Move WeChat `handler.py` + `channel.py` with chat_handler DI

**Files:**
- Read: `orchestrator/src/channels/wechat/handler.py`, `channel.py`
- Create: `orchestrator-channels/src/orchestrator_channels/wechat/handler.py`, `channel.py`
- Modify: `orchestrator-channels/src/orchestrator_channels/wechat/__init__.py`

- [ ] **Step 10.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_wechat_channel_full_construction():
    from orchestrator_channels.wechat import WeChatChannel

    async def fake_chat(user_id, platform, text, **kwargs):
        return f"echo: {text}"

    wc = WeChatChannel(
        bot_token="fake",
        chat_handler=fake_chat,
    )
    assert wc.name == "wechat"
```

- [ ] **Step 10.2: Run test to verify failure**

Expected: FAIL

- [ ] **Step 10.3: Copy `handler.py` with chat_handler DI**

Read `orchestrator/src/channels/wechat/handler.py`. Write to `orchestrator-channels/src/orchestrator_channels/wechat/handler.py` with:

1. Delete line: `from src.channels import chat as chat_engine`
2. Rewrite remaining `from src.channels.` → `from orchestrator_channels.` (covers `channels.boundary_nonce`, `channels.media`, `channels.wechat.api`, `channels.wechat.cdn`, `channels.wechat.utils` — all were pre-enumerated in the dependency scan)
3. In `WeChatHandler.__init__`, add keyword-only param `chat_handler` as the first param after self. Store `self._chat_handler = chat_handler`.
4. Enumerate every call site:

Run (read-only): `grep -n "chat_engine\." D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/wechat/handler.py`

5. For each line emitted by the grep, replace `chat_engine.do_chat(<args>)` with `await self._chat_handler(<args>)` preserving argument order/names exactly.
6. If any `chat_engine.<name>` where name ≠ `do_chat` appears, halt and add a matching DI param (e.g. `save_to_inbox_handler`) and replace accordingly. The expected case (per pre-plan scan): only `do_chat` is called.

- [ ] **Step 10.4: Copy `channel.py` with chat_handler DI wiring**

Read `orchestrator/src/channels/wechat/channel.py`. Write to `orchestrator-channels/src/orchestrator_channels/wechat/channel.py` with:

1. Delete line: `from src.channels import chat as chat_engine`
2. Rewrite remaining `from src.channels.` → `from orchestrator_channels.` and `from src.channels.wechat.` → `from orchestrator_channels.wechat.`
3. In `WeChatChannel.__init__`, add keyword-only param `chat_handler`. Example resulting signature:

```python
def __init__(
    self,
    *,
    bot_token: str,
    base_url: str = "",
    min_priority: str = "HIGH",
    allowed_users: str = "",
    chat_handler,  # Callable[..., Awaitable[str]] — injected by orchestrator
):
```

4. When constructing `WeChatHandler(...)` inside `__init__`, pass `chat_handler=chat_handler` through.
5. Run (read-only): `grep -n "chat_engine\." D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/wechat/channel.py`. If any direct `chat_engine.*` calls exist in `channel.py` itself (not just through the handler), add a matching DI param and replace accordingly.

- [ ] **Step 10.5: Update `wechat/__init__.py`**

Path: `orchestrator-channels/src/orchestrator_channels/wechat/__init__.py`

```python
"""WeChat (iLink) adapter."""
from orchestrator_channels.wechat.channel import WeChatChannel
from orchestrator_channels.wechat.login import load_credentials

__all__ = ["WeChatChannel", "load_credentials"]
```

- [ ] **Step 10.6: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: all pass

- [ ] **Step 10.7: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/wechat/ tests/test_smoke.py
git commit -m "feat: move wechat handler + channel with chat_handler DI"
```

---

## Phase 6: Move WeCom adapter

### Task 11: Move WeCom webhook adapter

**Files:**
- Read: `orchestrator/src/channels/wecom/channel.py`
- Create: `orchestrator-channels/src/orchestrator_channels/wecom/channel.py`, `__init__.py`

- [ ] **Step 11.1: Append test**

Append to `tests/test_smoke.py`:

```python
def test_wecom_channel_construction():
    from orchestrator_channels.wecom import WeComChannel

    wc = WeComChannel(webhook_url="http://example.test/hook")
    assert wc.name == "wecom"
```

- [ ] **Step 11.2: Run test to verify failure**

Expected: FAIL

- [ ] **Step 11.3: Copy `channel.py`**

Read `orchestrator/src/channels/wecom/channel.py`. Write to `orchestrator-channels/src/orchestrator_channels/wecom/channel.py` with `src.channels.` → `orchestrator_channels.` rewrites. WeCom has no `chat` import (it's webhook-only, outbound), so no DI needed.

- [ ] **Step 11.4: Create `wecom/__init__.py`**

Path: `orchestrator-channels/src/orchestrator_channels/wecom/__init__.py`

```python
"""WeCom (企业微信) webhook adapter."""
from orchestrator_channels.wecom.channel import WeComChannel

__all__ = ["WeComChannel"]
```

- [ ] **Step 11.5: Run test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels && python -m pytest tests/test_smoke.py -v`
Expected: all pass

- [ ] **Step 11.6: Commit**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
git add src/orchestrator_channels/wecom/ tests/test_smoke.py
git commit -m "feat: move wecom webhook adapter"
```

---

## Phase 7: Replace orchestrator originals with shims

### Task 12: Shim `src/channels/base.py`

**Files:**
- Move: `orchestrator/src/channels/base.py` → `.trash/2026-04-17-channels-extraction/shared/base.py`
- Create: new `orchestrator/src/channels/base.py` (shim)

- [ ] **Step 12.1: Move original to trash**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
mv src/channels/base.py .trash/2026-04-17-channels-extraction/shared/base.py
```

- [ ] **Step 12.2: Write shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/base.py`

```python
"""Shim — base types moved to orchestrator_channels.base."""
from orchestrator_channels.base import Channel, ChannelMessage

__all__ = ["Channel", "ChannelMessage"]
```

- [ ] **Step 12.3: Verify existing orchestrator imports still resolve**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -c "from src.channels.base import Channel, ChannelMessage; assert Channel.__module__ == 'orchestrator_channels.base'; print('OK')"`
Expected: `OK`

### Task 13: Shim `config.py`, `media.py`, `boundary_nonce.py`, `message_splitter.py`, `log_sanitizer.py`

**Files:**
- Move: 5 originals to `.trash/...`
- Create: 5 shims

- [ ] **Step 13.1: Move originals to trash**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
mv src/channels/config.py .trash/2026-04-17-channels-extraction/shared/
mv src/channels/media.py .trash/2026-04-17-channels-extraction/shared/
mv src/channels/boundary_nonce.py .trash/2026-04-17-channels-extraction/shared/
mv src/channels/message_splitter.py .trash/2026-04-17-channels-extraction/shared/
mv src/channels/log_sanitizer.py .trash/2026-04-17-channels-extraction/shared/
```

- [ ] **Step 13.2: Write `config.py` shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/config.py`

```python
"""Shim — channel config moved to orchestrator_channels.config."""
from orchestrator_channels.config import *  # noqa: F401,F403
from orchestrator_channels import config as _module
__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
```

- [ ] **Step 13.3: Write `media.py` shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/media.py`

```python
"""Shim — media utils moved to orchestrator_channels.media."""
from orchestrator_channels.media import *  # noqa: F401,F403
from orchestrator_channels import media as _module
__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
```

- [ ] **Step 13.4: Write `boundary_nonce.py` shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/boundary_nonce.py`

```python
"""Shim — boundary_nonce moved to orchestrator_channels.boundary_nonce."""
from orchestrator_channels.boundary_nonce import *  # noqa: F401,F403
from orchestrator_channels import boundary_nonce as _module
__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
```

- [ ] **Step 13.5: Write `message_splitter.py` shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/message_splitter.py`

```python
"""Shim — message_splitter moved to orchestrator_channels.message_splitter."""
from orchestrator_channels.message_splitter import *  # noqa: F401,F403
from orchestrator_channels import message_splitter as _module
__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
```

- [ ] **Step 13.6: Write `log_sanitizer.py` shim**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/log_sanitizer.py`

```python
"""Shim — log_sanitizer moved to orchestrator_channels.log_sanitizer."""
from orchestrator_channels.log_sanitizer import *  # noqa: F401,F403
from orchestrator_channels import log_sanitizer as _module
__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
```

- [ ] **Step 13.7: Verify shims resolve**

Run: 
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -c "
from src.channels.media import MediaType, guess_mime
from src.channels.config import get_channel_config
from src.channels.boundary_nonce import wrap_untrusted_block
from src.channels.message_splitter import split_message
from src.channels.log_sanitizer import install
print('all shims OK')
"
```

Expected: `all shims OK`

### Task 14: Shim `telegram/`, `wechat/`, `wecom/` package entries

**Files:**
- Move: 4 telegram files + 8 wechat files + 1 wecom file to `.trash/...`
- Replace: 3 `__init__.py` files with shim content

- [ ] **Step 14.1: Move adapter originals to trash**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
mv src/channels/telegram/channel.py .trash/2026-04-17-channels-extraction/telegram/
mv src/channels/telegram/handler.py .trash/2026-04-17-channels-extraction/telegram/
mv src/channels/telegram/sender.py .trash/2026-04-17-channels-extraction/telegram/
mv src/channels/telegram/tg_api.py .trash/2026-04-17-channels-extraction/telegram/

mv src/channels/wechat/api.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/cdn.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/utils.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/login.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/sender.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/handler.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/channel.py .trash/2026-04-17-channels-extraction/wechat/
mv src/channels/wechat/wechat-login.bat .trash/2026-04-17-channels-extraction/wechat/

mv src/channels/wecom/channel.py .trash/2026-04-17-channels-extraction/wecom/
```

- [ ] **Step 14.2: Rewrite `telegram/__init__.py`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/telegram/__init__.py`

```python
"""Shim — telegram adapter moved to orchestrator_channels.telegram."""
from orchestrator_channels.telegram import TelegramChannel

__all__ = ["TelegramChannel"]
```

- [ ] **Step 14.3: Rewrite `wechat/__init__.py`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/wechat/__init__.py`

```python
"""Shim — wechat adapter moved to orchestrator_channels.wechat."""
from orchestrator_channels.wechat import WeChatChannel, load_credentials

__all__ = ["WeChatChannel", "load_credentials"]
```

- [ ] **Step 14.4: Rewrite `wecom/__init__.py`**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/wecom/__init__.py`

```python
"""Shim — wecom adapter moved to orchestrator_channels.wecom."""
from orchestrator_channels.wecom import WeComChannel

__all__ = ["WeComChannel"]
```

- [ ] **Step 14.5: Verify adapter shims**

Run:
```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -c "
from src.channels.telegram import TelegramChannel
from src.channels.wechat import WeChatChannel, load_credentials
from src.channels.wecom import WeComChannel
print(TelegramChannel.__module__, WeChatChannel.__module__, WeComChannel.__module__)
"
```

Expected: each class's `__module__` begins with `orchestrator_channels.`

---

## Phase 8: Update orchestrator registry with DI injection

### Task 15: Modify `registry.py` to inject chat_handler and breaker

**Files:**
- Modify: `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/registry.py`

- [ ] **Step 15.1: Write integration test first**

Path: `D:/Users/Administrator/Documents/GitHub/orchestrator/tests/integration/test_channels_shim.py`

```python
"""Integration — shims + DI injection wire up correctly."""
import os


def test_shims_resolve_to_new_package():
    from src.channels.base import Channel
    from src.channels.media import MediaType
    from src.channels.telegram import TelegramChannel
    from src.channels.wechat import WeChatChannel
    from src.channels.wecom import WeComChannel
    assert Channel.__module__ == "orchestrator_channels.base"
    assert MediaType.__module__ == "orchestrator_channels.media"
    assert TelegramChannel.__module__ == "orchestrator_channels.telegram.channel"
    assert WeChatChannel.__module__ == "orchestrator_channels.wechat.channel"
    assert WeComChannel.__module__ == "orchestrator_channels.wecom.channel"


def test_registry_auto_discover_no_env(monkeypatch):
    # Clear all channel env vars
    for k in ["TELEGRAM_BOT_TOKEN", "WECHAT_BOT_TOKEN", "WECOM_WEBHOOK_URL"]:
        monkeypatch.delenv(k, raising=False)

    from src.channels.registry import ChannelRegistry
    r = ChannelRegistry()
    r.auto_discover()
    assert r.get_status() == {}


def test_registry_injects_chat_handler_for_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-for-test")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "0")
    monkeypatch.delenv("WECHAT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    from src.channels.registry import ChannelRegistry
    r = ChannelRegistry()
    r.auto_discover()
    status = r.get_status()
    assert "telegram" in status
    tg = r._channels["telegram"]
    # Verify chat_handler was injected
    assert tg._handler._chat_handler is not None
```

- [ ] **Step 15.2: Run test to verify failure**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/integration/test_channels_shim.py -v`
Expected: `test_shims_resolve_to_new_package` passes; `test_registry_injects_chat_handler_for_telegram` FAILS because registry doesn't inject yet.

- [ ] **Step 15.3: Read current `registry.py`**

Read full content of `D:/Users/Administrator/Documents/GitHub/orchestrator/src/channels/registry.py`.

- [ ] **Step 15.4: Modify `auto_discover()` — add chat handler builder**

Edit `src/channels/registry.py`. Add at module level (before class `ChannelRegistry`):

```python
def _build_chat_handler():
    """Build the chat handler callback that adapters invoke for inbound messages."""
    from src.channels.chat import do_chat
    return do_chat


def _build_breaker(name: str):
    """Build a circuit breaker for adapters that need rate limiting."""
    from src.core.circuit_breaker import get_breaker, CircuitBreakerError
    return get_breaker(name), CircuitBreakerError
```

- [ ] **Step 15.5: Modify `auto_discover()` — Telegram block**

In `auto_discover`, find the Telegram block starting with `if os.environ.get("TELEGRAM_BOT_TOKEN"):`. Replace the `TelegramChannel(...)` construction with:

```python
if os.environ.get("TELEGRAM_BOT_TOKEN"):
    try:
        from src.channels.telegram import TelegramChannel
        breaker, breaker_err = _build_breaker("telegram")
        tg = TelegramChannel(
            token=os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            min_priority=os.environ.get("TELEGRAM_MIN_PRIORITY", "HIGH"),
            chat_handler=_build_chat_handler(),
            breaker=breaker,
            breaker_error_cls=breaker_err,
        )
        self.register(tg)
    except Exception as e:
        log.error(f"channel: failed to init telegram: {e}")
```

- [ ] **Step 15.6: Modify `auto_discover()` — WeChat block**

In `auto_discover`, find the WeChat block starting with `if wechat_token:`. Replace the `WeChatChannel(...)` construction with:

```python
if wechat_token:
    try:
        from src.channels.wechat import WeChatChannel
        wc = WeChatChannel(
            bot_token=wechat_token,
            base_url=os.environ.get("WECHAT_BASE_URL", ""),
            min_priority=os.environ.get("WECHAT_MIN_PRIORITY", "HIGH"),
            allowed_users=os.environ.get("WECHAT_ALLOWED_USERS", ""),
            chat_handler=_build_chat_handler(),
        )
        self.register(wc)
    except Exception as e:
        log.error(f"channel: failed to init wechat: {e}")
```

Note: WeChat doesn't use the circuit breaker (its API layer doesn't import it), so only `chat_handler` is injected. If a future change adds breaker-guarded calls, extend this block to pass `breaker=` similar to Telegram.

- [ ] **Step 15.7: WeCom block — no changes needed**

WeCom is webhook-only (outbound). No DI to add. Confirm by grep:

Run: `grep -n "chat_engine\|chat_handler" .trash/2026-04-17-channels-extraction/wecom/channel.py`
Expected: no matches.

- [ ] **Step 15.8: Run integration test to verify pass**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/integration/test_channels_shim.py -v`
Expected: all pass

- [ ] **Step 15.9: Commit registry change + integration test**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
git add src/channels/registry.py tests/integration/test_channels_shim.py
git commit -m "refactor(channels): inject chat_handler and breaker into adapters"
```

---

## Phase 9: Wire dependency in orchestrator's requirements + commit shims

### Task 16: Add orchestrator-channels to `requirements.txt` + commit shims

**Files:**
- Modify: `D:/Users/Administrator/Documents/GitHub/orchestrator/requirements.txt`

- [ ] **Step 16.1: Append editable install line**

Edit `requirements.txt`, append on a new line:

```
-e ../orchestrator-channels
```

- [ ] **Step 16.2: Verify pip sees it**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && pip install -r requirements.txt --dry-run 2>&1 | grep orchestrator-channels`
Expected: a line mentioning orchestrator-channels in "Would install" or "Requirement already satisfied"

- [ ] **Step 16.3: Commit shim files, requirements, and trash moves**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
git add src/channels/base.py src/channels/config.py src/channels/media.py
git add src/channels/boundary_nonce.py src/channels/message_splitter.py src/channels/log_sanitizer.py
git add src/channels/telegram/__init__.py src/channels/wechat/__init__.py src/channels/wecom/__init__.py
git add requirements.txt
git add -u  # stage all deletions from mv-to-trash
git commit -m "refactor(channels): replace adapter sources with shims to orchestrator-channels"
```

---

## Phase 10: Full-repo verification

### Task 17: Run existing orchestrator tests

- [ ] **Step 17.1: Run the channel-touching test suite**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -m pytest tests/ -x --ignore=tests/integration/live -q \
  -k "channel or chat or tg_ or telegram or wechat"
```

Expected: exit code 0. If any test fails, fix the underlying shim/DI issue before proceeding. Do NOT mark steps complete until exit 0.

- [ ] **Step 17.2: Run full test suite**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -m pytest tests/ -x --ignore=tests/integration/live -q
```

Expected: exit code 0.

- [ ] **Step 17.3: Boot smoke — registry start/stop cycle**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -c "
from src.channels.registry import get_channel_registry
import time
r = get_channel_registry()
r.start_all()
time.sleep(1.5)
print('status:', r.get_status())
r.stop_all()
print('stop OK')
"
```

Expected: Prints status (empty if no env vars, or contains configured channels) + `stop OK`. No uncaught exceptions.

- [ ] **Step 17.4: If `.env` has `TELEGRAM_BOT_TOKEN`, live-send smoke**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python -c "
import os, dotenv
dotenv.load_dotenv()
if not os.environ.get('TELEGRAM_BOT_TOKEN'):
    print('SKIP: no TELEGRAM_BOT_TOKEN in .env')
else:
    from src.channels.registry import get_channel_registry
    from src.channels.base import ChannelMessage
    r = get_channel_registry()
    r.broadcast(ChannelMessage(text='extraction smoke: tg adapter reachable', priority='HIGH'))
    print('sent')
"
```

Expected: either `SKIP` (no token) or `sent`. If sent, visually confirm message arrives in the configured chat.

### Task 18: Commit anything uncommitted and merge

- [ ] **Step 18.1: Check for uncommitted drift**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && git status --porcelain`
Expected: empty.

If not empty, inspect and commit with message `chore: post-extraction cleanup`.

- [ ] **Step 18.2: Push orchestrator-channels**

```bash
cd D:/Users/Administrator/Documents/GitHub/orchestrator-channels
# Ask user about remote: github repo? local only for now?
# Default: local only until user decides
git log --oneline
```

Expected: all commits from phases 1–6 listed in order.

- [ ] **Step 18.3: Report trash inventory to owner**

Run:
```bash
ls -la D:/Users/Administrator/Documents/GitHub/orchestrator/.trash/2026-04-17-channels-extraction/
find D:/Users/Administrator/Documents/GitHub/orchestrator/.trash/2026-04-17-channels-extraction/ -type f | wc -l
```

Report back to owner: total files moved, directory sizes, and ask whether `.trash/` contents should be kept for one week or deleted immediately.

---

## Open Questions (for owner decision after implementation)

1. **Remote hosting for `orchestrator-channels`?** Create GitHub repo, or keep local-only for now? (Default: local until owner decides.)
2. **Shim layer lifetime?** Keep shims indefinitely (zero-risk) or schedule a follow-up to rewrite all orchestrator imports to use `orchestrator_channels.*` directly and delete shims? (Default: keep; revisit when orchestrator is repackaged with its own `pyproject.toml`.)
3. **Docs updates?** `docs/architecture/README.md`, `README.zh-CN.md`, and `.env.example` mention `src.channels.telegram`. Should these be rewritten in this PR, or deferred? (Default: defer to follow-up docs PR.)

## Assumptions

- **ASSUMPTION: Pip editable install from local path is acceptable.** Rationale: both repos are on the same machine during active development. When/if `orchestrator-channels` is published (PyPI or internal index), swap `-e ../orchestrator-channels` for a version pin — zero code changes needed.
- **ASSUMPTION: `circuit_breaker` is orchestrator-specific.** Its policy config may apply to non-channel systems. Duplicating into orchestrator-channels creates two sources of truth; injection keeps the config centralized.
- **ASSUMPTION: The current `chat_engine.do_chat(user_id, platform, text, attachments=None, username=None)` signature is the full contract between adapters and orchestrator.** If any adapter also calls `chat_engine.save_to_inbox` or similar, Step 7.3 / 10.3 grep commands catch it and add additional DI params.
