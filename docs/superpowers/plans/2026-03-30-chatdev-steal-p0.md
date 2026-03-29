# ChatDev 2.0 偷师 P0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 ChatDev 2.0 偷 6 个 P0 级架构模式，增强 Orchestrator 的依赖注入、注册机制、事件流、重试逻辑、阻塞协调和函数自省能力。

**Architecture:** 每个模式独立为一个 Python 模块，放在 `src/core/` 下。不改动现有模块的外部接口，只增加新能力。现有代码通过渐进式迁移使用新模块。

**Tech Stack:** Python 3.12, dataclasses, concurrent.futures, threading, collections.deque, tenacity

---

### Task 1: Generic Registry（通用注册表 + 延迟加载）

**Files:**
- Create: `src/core/registry.py`
- Create: `tests/core/test_registry.py`

升级现有 `component_spec.py` 的注册能力。支持 4 种注册模式：直接引用、延迟模块加载、自定义 loader、仅元数据。带命名空间隔离 + 重复检测。

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_registry.py
"""Tests for Generic Registry — stolen from ChatDev 2.0."""
import pytest
from src.core.registry import Registry


def test_register_and_resolve_target():
    """Direct target registration and resolution."""
    r = Registry("test")
    r.register("my_thing", target=42)
    assert r.resolve("my_thing") == 42


def test_register_lazy_module():
    """Lazy module loading — doesn't import until resolve()."""
    r = Registry("test")
    r.register("os_path_join", module_path="os.path", attr_name="join")
    # Not imported yet
    assert "os_path_join" in r
    # Now resolve — triggers import
    fn = r.resolve("os_path_join")
    import os.path
    assert fn is os.path.join


def test_register_with_loader():
    """Custom loader callable."""
    r = Registry("test")
    call_count = {"n": 0}
    def my_loader():
        call_count["n"] += 1
        return {"loaded": True}
    r.register("custom", loader=my_loader)
    result = r.resolve("custom")
    assert result == {"loaded": True}
    assert call_count["n"] == 1
    # Second resolve should cache
    result2 = r.resolve("custom")
    assert result2 == {"loaded": True}
    assert call_count["n"] == 1  # Not called again


def test_register_metadata_only():
    """Metadata-only registration (no target, no loader)."""
    r = Registry("test")
    r.register("info_only", metadata={"version": "1.0", "author": "test"})
    assert r.get_metadata("info_only") == {"version": "1.0", "author": "test"}
    assert r.resolve("info_only") is None  # No target to resolve


def test_duplicate_detection():
    """Duplicate registration raises ValueError."""
    r = Registry("test")
    r.register("dup", target=1)
    with pytest.raises(ValueError, match="already registered"):
        r.register("dup", target=2)


def test_override_allowed():
    """Override=True allows re-registration."""
    r = Registry("test")
    r.register("item", target=1)
    r.register("item", target=2, override=True)
    assert r.resolve("item") == 2


def test_namespace_isolation():
    """Different namespaces don't collide."""
    r1 = Registry("ns1")
    r2 = Registry("ns2")
    r1.register("shared_name", target="from_ns1")
    r2.register("shared_name", target="from_ns2")
    assert r1.resolve("shared_name") == "from_ns1"
    assert r2.resolve("shared_name") == "from_ns2"


def test_list_entries():
    """List all registered entry names."""
    r = Registry("test")
    r.register("a", target=1)
    r.register("b", target=2)
    r.register("c", metadata={"x": 1})
    assert set(r.list()) == {"a", "b", "c"}


def test_resolve_unknown_returns_none():
    """Resolving unknown key returns None (no exception)."""
    r = Registry("test")
    assert r.resolve("nonexistent") is None


def test_contains():
    """__contains__ works for 'in' operator."""
    r = Registry("test")
    r.register("exists", target=True)
    assert "exists" in r
    assert "nope" not in r
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.registry'`

- [ ] **Step 3: Implement Registry**

```python
# src/core/registry.py
"""Generic Registry — stolen from ChatDev 2.0.

Supports 4 registration modes:
  1. Direct target: register("name", target=obj)
  2. Lazy module: register("name", module_path="mod", attr_name="cls")
  3. Custom loader: register("name", loader=callable)
  4. Metadata only: register("name", metadata={...})

Features: namespace isolation, duplicate detection, lazy loading cache.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class _Entry:
    name: str
    target: Any = None
    module_path: str | None = None
    attr_name: str | None = None
    loader: Callable | None = None
    metadata: dict = field(default_factory=dict)
    _resolved: Any = field(default=None, repr=False)
    _resolved_flag: bool = field(default=False, repr=False)


class Registry:
    """Namespaced component registry with lazy loading."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self._entries: dict[str, _Entry] = {}

    def register(
        self,
        name: str,
        *,
        target: Any = None,
        module_path: str | None = None,
        attr_name: str | None = None,
        loader: Callable | None = None,
        metadata: dict | None = None,
        override: bool = False,
    ):
        """Register a component by name.

        Args:
            name: Unique key within this namespace.
            target: Direct object/class/value.
            module_path: Module to import lazily (with attr_name).
            attr_name: Attribute to fetch from module_path.
            loader: Callable that returns the component (called once, cached).
            metadata: Arbitrary metadata dict.
            override: If True, allow re-registration.
        """
        if name in self._entries and not override:
            raise ValueError(
                f"'{name}' already registered in '{self.namespace}'. "
                f"Use override=True to replace."
            )
        self._entries[name] = _Entry(
            name=name,
            target=target,
            module_path=module_path,
            attr_name=attr_name,
            loader=loader,
            metadata=metadata or {},
        )

    def resolve(self, name: str) -> Any | None:
        """Resolve a registered name to its live object.

        Returns None if not found or if metadata-only registration.
        Lazy-loaded values are cached after first resolution.
        """
        entry = self._entries.get(name)
        if entry is None:
            return None

        # Already resolved — return cached
        if entry._resolved_flag:
            return entry._resolved

        result = None

        # Mode 1: direct target
        if entry.target is not None:
            result = entry.target

        # Mode 2: lazy module import
        elif entry.module_path and entry.attr_name:
            try:
                mod = importlib.import_module(entry.module_path)
                result = getattr(mod, entry.attr_name)
            except (ImportError, AttributeError) as e:
                log.warning(f"registry[{self.namespace}]: cannot resolve "
                            f"{name} → {entry.module_path}.{entry.attr_name}: {e}")
                return None

        # Mode 3: custom loader
        elif entry.loader is not None:
            try:
                result = entry.loader()
            except Exception as e:
                log.warning(f"registry[{self.namespace}]: loader for {name} failed: {e}")
                return None

        # Mode 4: metadata only — no target
        else:
            entry._resolved_flag = True
            return None

        entry._resolved = result
        entry._resolved_flag = True
        return result

    def get_metadata(self, name: str) -> dict:
        """Return metadata for a registered entry."""
        entry = self._entries.get(name)
        return entry.metadata if entry else {}

    def list(self) -> list[str]:
        """Return all registered names."""
        return list(self._entries.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"Registry({self.namespace!r}, entries={len(self._entries)})"
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_registry.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/registry.py tests/core/test_registry.py
git commit -m "feat(core): generic registry with lazy loading — stolen from ChatDev 2.0"
```

---

### Task 2: ExecutionContext（依赖注入包）

**Files:**
- Create: `src/core/execution_context.py`
- Create: `tests/core/test_execution_context.py`

统一打包所有运行时服务到一个 dataclass，替代散落的全局变量传递。

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_execution_context.py
"""Tests for ExecutionContext — stolen from ChatDev 2.0."""
import threading
import pytest
from src.core.execution_context import ExecutionContext, ExecutionContextBuilder


def test_context_creation():
    """Basic context with required fields."""
    ctx = ExecutionContext(
        task_id=42,
        department="engineering",
    )
    assert ctx.task_id == 42
    assert ctx.department == "engineering"
    assert ctx.global_state == {}
    assert ctx.cancel_event is not None
    assert not ctx.cancel_event.is_set()


def test_context_cancellation():
    """Cancel event propagation."""
    ctx = ExecutionContext(task_id=1, department="quality")
    assert not ctx.is_cancelled
    ctx.cancel("test reason")
    assert ctx.is_cancelled
    assert ctx.cancel_reason == "test reason"
    assert ctx.cancel_event.is_set()


def test_context_global_state():
    """Shared state across components."""
    ctx = ExecutionContext(task_id=1, department="engineering")
    ctx.global_state["key"] = "value"
    assert ctx.global_state["key"] == "value"


def test_builder_pattern():
    """Builder assembles context from components."""
    builder = ExecutionContextBuilder(task_id=99, department="security")
    builder.with_cwd("/tmp/test")
    builder.with_timeout(300.0)
    ctx = builder.build()
    assert ctx.task_id == 99
    assert ctx.department == "security"
    assert ctx.cwd == "/tmp/test"
    assert ctx.timeout_s == 300.0


def test_builder_defaults():
    """Builder provides sensible defaults."""
    ctx = ExecutionContextBuilder(task_id=1, department="ops").build()
    assert ctx.timeout_s == 300.0
    assert ctx.max_turns == 25
    assert ctx.cwd == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_execution_context.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ExecutionContext**

```python
# src/core/execution_context.py
"""ExecutionContext — unified dependency injection bundle.

Stolen from ChatDev 2.0's runtime/node/executor/base.py.
One dataclass carries all runtime services. Every executor receives
this single parameter instead of scattered globals.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExecutionContext:
    """Immutable-ish bundle of runtime services for task execution.

    Replaces scattered parameter passing across governance pipeline.
    Components that need shared state use global_state dict.
    Cancellation propagates via cancel_event (threading.Event).
    """
    # ── Required ──
    task_id: int
    department: str

    # ── Execution config ──
    cwd: str = ""
    timeout_s: float = 300.0
    max_turns: int = 25
    model: str = "claude-sonnet-4-6"

    # ── Shared state ──
    global_state: dict[str, Any] = field(default_factory=dict)

    # ── Cancellation ──
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str = ""

    # ── Optional service references (set by builder or caller) ──
    db: Any = None
    cost_tracker: Any = None
    token_accountant: Any = None
    log_event_fn: Any = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self, reason: str = ""):
        """Signal cancellation to all components sharing this context."""
        self.cancel_reason = reason
        self.cancel_event.set()


class ExecutionContextBuilder:
    """Fluent builder for ExecutionContext."""

    def __init__(self, task_id: int, department: str):
        self._task_id = task_id
        self._department = department
        self._cwd = ""
        self._timeout_s = 300.0
        self._max_turns = 25
        self._model = "claude-sonnet-4-6"
        self._global_state: dict[str, Any] = {}
        self._db = None
        self._cost_tracker = None
        self._token_accountant = None
        self._log_event_fn = None

    def with_cwd(self, cwd: str) -> "ExecutionContextBuilder":
        self._cwd = cwd
        return self

    def with_timeout(self, timeout_s: float) -> "ExecutionContextBuilder":
        self._timeout_s = timeout_s
        return self

    def with_max_turns(self, max_turns: int) -> "ExecutionContextBuilder":
        self._max_turns = max_turns
        return self

    def with_model(self, model: str) -> "ExecutionContextBuilder":
        self._model = model
        return self

    def with_db(self, db: Any) -> "ExecutionContextBuilder":
        self._db = db
        return self

    def with_cost_tracker(self, tracker: Any) -> "ExecutionContextBuilder":
        self._cost_tracker = tracker
        return self

    def with_token_accountant(self, accountant: Any) -> "ExecutionContextBuilder":
        self._token_accountant = accountant
        return self

    def with_log_event_fn(self, fn: Any) -> "ExecutionContextBuilder":
        self._log_event_fn = fn
        return self

    def build(self) -> ExecutionContext:
        return ExecutionContext(
            task_id=self._task_id,
            department=self._department,
            cwd=self._cwd,
            timeout_s=self._timeout_s,
            max_turns=self._max_turns,
            model=self._model,
            global_state=self._global_state,
            db=self._db,
            cost_tracker=self._cost_tracker,
            token_accountant=self._token_accountant,
            log_event_fn=self._log_event_fn,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_execution_context.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/execution_context.py tests/core/test_execution_context.py
git commit -m "feat(core): ExecutionContext dependency injection bundle — stolen from ChatDev 2.0"
```

---

### Task 3: EventStream（有界队列 + 序列号游标）

**Files:**
- Create: `src/core/event_stream.py`
- Create: `tests/core/test_event_stream.py`

Dashboard SSE 推送从全量刷新升级为 cursor-based 增量拉取。

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_event_stream.py
"""Tests for EventStream — stolen from ChatDev 2.0's ArtifactEventQueue."""
import time
import threading
import pytest
from src.core.event_stream import EventStream, StreamEvent


def test_append_and_get():
    """Basic append and retrieval."""
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="test", data={"msg": "hello"}))
    events, cursor = s.get_after(0)
    assert len(events) == 1
    assert events[0].event_type == "test"
    assert events[0].sequence == 1
    assert cursor == 1


def test_cursor_based_incremental():
    """Only returns events after the given cursor."""
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="a", data={}))
    s.append(StreamEvent(event_type="b", data={}))
    s.append(StreamEvent(event_type="c", data={}))

    # Get all
    events, cursor = s.get_after(0)
    assert len(events) == 3
    assert cursor == 3

    # Get only new ones
    s.append(StreamEvent(event_type="d", data={}))
    events, cursor = s.get_after(3)
    assert len(events) == 1
    assert events[0].event_type == "d"
    assert cursor == 4


def test_bounded_eviction():
    """Old events evicted when max_events reached."""
    s = EventStream(max_events=3)
    for i in range(5):
        s.append(StreamEvent(event_type=f"e{i}", data={}))

    # Only last 3 should remain
    events, cursor = s.get_after(0)
    assert len(events) == 3
    assert events[0].event_type == "e2"
    assert events[-1].event_type == "e4"
    assert cursor == 5  # Sequence continues incrementing


def test_stale_cursor_returns_available():
    """Cursor pointing to evicted events returns all available."""
    s = EventStream(max_events=3)
    for i in range(5):
        s.append(StreamEvent(event_type=f"e{i}", data={}))

    # Cursor 1 is evicted, should return all available
    events, cursor = s.get_after(1)
    assert len(events) == 3
    assert events[0].sequence == 3  # Oldest available


def test_filter_by_type():
    """Filter events by type."""
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="log", data={"msg": "info"}))
    s.append(StreamEvent(event_type="artifact", data={"file": "a.py"}))
    s.append(StreamEvent(event_type="log", data={"msg": "warn"}))

    events, _ = s.get_after(0, event_types={"log"})
    assert len(events) == 2
    assert all(e.event_type == "log" for e in events)


def test_wait_for_events_blocking():
    """wait_for_events blocks until new events arrive."""
    s = EventStream(max_events=100)

    result = {}
    def consumer():
        events, cursor, timed_out = s.wait_for_events(after=0, timeout=5.0)
        result["events"] = events
        result["timed_out"] = timed_out

    t = threading.Thread(target=consumer, daemon=True)
    t.start()
    time.sleep(0.1)  # Let consumer start waiting
    s.append(StreamEvent(event_type="wakeup", data={}))
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert len(result["events"]) == 1
    assert not result["timed_out"]


def test_wait_for_events_timeout():
    """wait_for_events returns empty on timeout."""
    s = EventStream(max_events=100)
    events, cursor, timed_out = s.wait_for_events(after=0, timeout=0.2)
    assert len(events) == 0
    assert timed_out


def test_stats():
    """Stream reports stats."""
    s = EventStream(max_events=100)
    s.append(StreamEvent(event_type="a", data={}))
    s.append(StreamEvent(event_type="b", data={}))
    stats = s.stats()
    assert stats["total_appended"] == 2
    assert stats["current_size"] == 2
    assert stats["last_sequence"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_event_stream.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement EventStream**

```python
# src/core/event_stream.py
"""EventStream — bounded deque with sequence numbers for cursor-based polling.

Stolen from ChatDev 2.0's server/artifact_events.py (ArtifactEventQueue).

Usage:
    stream = EventStream(max_events=2000)
    stream.append(StreamEvent(event_type="log", data={"msg": "hello"}))

    # Cursor-based polling (Dashboard SSE):
    events, cursor = stream.get_after(last_cursor)

    # Blocking long-poll:
    events, cursor, timed_out = stream.wait_for_events(after=cursor, timeout=30)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    """Single event in the stream."""
    event_type: str
    data: dict[str, Any]
    sequence: int = 0          # Set by EventStream on append
    timestamp: float = 0.0     # Set by EventStream on append

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventStream:
    """Thread-safe bounded event stream with cursor-based access.

    Events are assigned monotonically increasing sequence numbers.
    Old events are evicted when max_events is reached.
    Consumers track their position via cursor (last seen sequence).
    """

    def __init__(self, max_events: int = 2000):
        self._max_events = max_events
        self._events: deque[StreamEvent] = deque()
        self._last_sequence: int = 0
        self._total_appended: int = 0
        self._condition = threading.Condition()

    def append(self, event: StreamEvent):
        """Append event, assign sequence number, notify waiters."""
        with self._condition:
            self._last_sequence += 1
            self._total_appended += 1
            event.sequence = self._last_sequence
            event.timestamp = event.timestamp or time.time()
            self._events.append(event)

            # Evict oldest if over limit
            while len(self._events) > self._max_events:
                self._events.popleft()

            self._condition.notify_all()

    def get_after(
        self,
        after: int = 0,
        limit: int = 500,
        event_types: set[str] | None = None,
    ) -> tuple[list[StreamEvent], int]:
        """Return events with sequence > after.

        Args:
            after: Cursor — return events after this sequence number.
            limit: Max events to return.
            event_types: Optional filter set.

        Returns:
            (events, new_cursor) where new_cursor = last event's sequence.
        """
        with self._condition:
            result = []
            for event in self._events:
                if event.sequence <= after:
                    continue
                if event_types and event.event_type not in event_types:
                    continue
                result.append(event)
                if len(result) >= limit:
                    break

            new_cursor = result[-1].sequence if result else after
            return result, new_cursor

    def wait_for_events(
        self,
        after: int = 0,
        timeout: float = 30.0,
        event_types: set[str] | None = None,
        limit: int = 500,
    ) -> tuple[list[StreamEvent], int, bool]:
        """Block until new events are available or timeout.

        Returns:
            (events, new_cursor, timed_out)
        """
        deadline = time.time() + timeout
        with self._condition:
            while True:
                events, cursor = self.get_after(after, limit, event_types)
                if events:
                    return events, cursor, False

                remaining = deadline - time.time()
                if remaining <= 0:
                    return [], after, True

                self._condition.wait(timeout=min(remaining, 1.0))

    def stats(self) -> dict:
        """Return stream statistics."""
        with self._condition:
            min_seq = self._events[0].sequence if self._events else 0
            return {
                "current_size": len(self._events),
                "max_events": self._max_events,
                "last_sequence": self._last_sequence,
                "min_sequence": min_seq,
                "total_appended": self._total_appended,
            }
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_event_stream.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/event_stream.py tests/core/test_event_stream.py
git commit -m "feat(core): EventStream with bounded deque + cursor polling — stolen from ChatDev 2.0"
```

---

### Task 4: Resilient Retry（异常链遍历 + tenacity 集成）

**Files:**
- Create: `src/core/resilient_retry.py`
- Create: `tests/core/test_resilient_retry.py`
- Note: 不修改现有 `src/collectors/retry.py`，那个继续给 collector 用

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_resilient_retry.py
"""Tests for Resilient Retry — stolen from ChatDev 2.0's exception chain traversal."""
import pytest
from src.core.resilient_retry import RetryPolicy, resilient_call


class RateLimitError(Exception):
    status_code = 429


class AuthError(Exception):
    status_code = 401


class WrappedError(Exception):
    """Error that wraps another via __cause__."""
    pass


def test_retry_on_exception_type():
    """Retries when exception type matches."""
    policy = RetryPolicy(
        max_attempts=3,
        retry_on_types=["RateLimitError"],
    )
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RateLimitError("rate limited")
        return "ok"

    result = resilient_call(flaky, policy)
    assert result == "ok"
    assert call_count["n"] == 3


def test_no_retry_on_blacklisted_type():
    """Does NOT retry when exception is blacklisted."""
    policy = RetryPolicy(
        max_attempts=5,
        retry_on_types=["RateLimitError"],
        no_retry_types=["AuthError"],
    )
    with pytest.raises(AuthError):
        resilient_call(lambda: (_ for _ in ()).throw(AuthError("bad auth")), policy)


def test_retry_on_status_code():
    """Retries based on HTTP status code attribute."""
    policy = RetryPolicy(
        max_attempts=3,
        retry_on_status_codes=[429, 500, 502, 503],
    )
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RateLimitError("rate limited")
        return "ok"

    result = resilient_call(flaky, policy)
    assert result == "ok"


def test_no_retry_on_unmatched_status():
    """Does NOT retry when status code doesn't match."""
    policy = RetryPolicy(
        max_attempts=3,
        retry_on_status_codes=[429, 500],
    )
    with pytest.raises(AuthError):
        resilient_call(lambda: (_ for _ in ()).throw(AuthError("401")), policy)


def test_retry_on_message_substring():
    """Retries when error message contains substring."""
    policy = RetryPolicy(
        max_attempts=3,
        retry_on_substrings=["temporarily unavailable", "try again"],
    )
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise Exception("Service temporarily unavailable")
        return "ok"

    result = resilient_call(flaky, policy)
    assert result == "ok"


def test_exception_chain_traversal():
    """Retries by inspecting __cause__ chain."""
    policy = RetryPolicy(
        max_attempts=3,
        retry_on_types=["RateLimitError"],
    )
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            try:
                raise RateLimitError("inner")
            except RateLimitError as inner:
                raise WrappedError("outer") from inner
        return "ok"

    result = resilient_call(flaky, policy)
    assert result == "ok"
    assert call_count["n"] == 2


def test_max_attempts_exhausted():
    """Raises after max attempts exhausted."""
    policy = RetryPolicy(max_attempts=2, retry_on_types=["Exception"])
    with pytest.raises(Exception, match="always fails"):
        resilient_call(lambda: (_ for _ in ()).throw(Exception("always fails")), policy)


def test_disabled_policy():
    """Disabled policy runs once, no retry."""
    policy = RetryPolicy(enabled=False)
    with pytest.raises(Exception):
        resilient_call(lambda: (_ for _ in ()).throw(Exception("fail")), policy)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_resilient_retry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement resilient_retry**

```python
# src/core/resilient_retry.py
"""Resilient Retry — exception chain traversal + tenacity integration.

Stolen from ChatDev 2.0's entity/configs/node/agent.py (AgentRetryConfig).

Key innovation: walks __cause__ + __context__ chain to find retryable
errors buried inside wrapper exceptions. Uses three-layer matching:
  1. Blacklist type names → never retry
  2. Whitelist type names → retry
  3. HTTP status codes → retry
  4. Error message substrings → retry

Usage:
    policy = RetryPolicy(max_attempts=3, retry_on_types=["RateLimitError"])
    result = resilient_call(my_function, policy)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Declarative retry configuration."""
    enabled: bool = True
    max_attempts: int = 3
    min_wait_s: float = 1.0
    max_wait_s: float = 10.0
    retry_on_types: list[str] = field(default_factory=list)
    no_retry_types: list[str] = field(default_factory=list)
    retry_on_status_codes: list[int] = field(default_factory=list)
    retry_on_substrings: list[str] = field(default_factory=list)


def _iter_exception_chain(exc: BaseException):
    """Walk __cause__ and __context__ chain, yield each exception."""
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        # Follow explicit cause first, then implicit context
        next_exc = current.__cause__ or current.__context__
        current = next_exc


def _exception_type_names(exc: BaseException) -> set[str]:
    """Get all type names in MRO for matching."""
    names = set()
    for cls in type(exc).__mro__:
        names.add(cls.__name__)
        if hasattr(cls, "__module__"):
            names.add(f"{cls.__module__}.{cls.__name__}")
    return names


def _extract_status_code(exc: BaseException) -> int | None:
    """Try to extract HTTP status code from exception."""
    for attr in ("status_code", "http_status", "code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def should_retry(exc: BaseException, policy: RetryPolicy) -> bool:
    """Decide whether to retry by walking the exception chain."""
    if not policy.enabled:
        return False

    chain_info = []
    for error in _iter_exception_chain(exc):
        chain_info.append((
            error,
            _exception_type_names(error),
            _extract_status_code(error),
            str(error).lower(),
        ))

    # Check blacklist first (fail-fast)
    if policy.no_retry_types:
        no_retry_lower = {t.lower() for t in policy.no_retry_types}
        for _, names, _, _ in chain_info:
            if any(n.lower() in no_retry_lower for n in names):
                return False

    # Check whitelist types
    if policy.retry_on_types:
        types_lower = {t.lower() for t in policy.retry_on_types}
        for _, names, _, _ in chain_info:
            if any(n.lower() in types_lower for n in names):
                return True

    # Check status codes
    if policy.retry_on_status_codes:
        for _, _, status, _ in chain_info:
            if status is not None and status in policy.retry_on_status_codes:
                return True

    # Check message substrings
    if policy.retry_on_substrings:
        subs_lower = [s.lower() for s in policy.retry_on_substrings]
        for _, _, _, message in chain_info:
            if any(sub in message for sub in subs_lower):
                return True

    return False


def resilient_call(fn: Callable[[], T], policy: RetryPolicy) -> T:
    """Execute fn with retry according to policy.

    Uses exponential backoff with jitter (random_exponential style).
    """
    import random

    if not policy.enabled:
        return fn()

    last_exc = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                raise
            if not should_retry(exc, policy):
                raise

            # Exponential backoff with jitter
            base = policy.min_wait_s * (2 ** (attempt - 1))
            wait = min(base, policy.max_wait_s)
            wait *= 0.5 + random.random()  # jitter: 50%-150%
            log.info(f"resilient_retry: attempt {attempt}/{policy.max_attempts} "
                     f"failed ({type(exc).__name__}), retrying in {wait:.1f}s")
            time.sleep(wait)

    raise last_exc  # Should not reach here, but safety net
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_resilient_retry.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/resilient_retry.py tests/core/test_resilient_retry.py
git commit -m "feat(core): resilient retry with exception chain traversal — stolen from ChatDev 2.0"
```

---

### Task 5: FutureGate（Future 阻塞协调）

**Files:**
- Create: `src/core/future_gate.py`
- Create: `tests/core/test_future_gate.py`

用 `concurrent.futures.Future` + `threading.Event` 实现内存级阻塞等待，替代 DB 轮询。用于审批、人工输入等需要等待外部信号的场景。

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_future_gate.py
"""Tests for FutureGate — stolen from ChatDev 2.0's SessionExecutionController."""
import threading
import time
import pytest
from src.core.future_gate import FutureGate, GateTimeout, GateCancelled


def test_basic_wait_and_provide():
    """Provider unblocks waiter."""
    gate = FutureGate()
    gate_id = gate.open("test_gate")

    result = {}
    def waiter():
        result["value"] = gate.wait(gate_id, timeout=5.0)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.1)
    gate.provide(gate_id, {"approved": True})
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert result["value"] == {"approved": True}


def test_timeout():
    """Raises GateTimeout when nobody provides."""
    gate = FutureGate()
    gate_id = gate.open("timeout_test")
    with pytest.raises(GateTimeout):
        gate.wait(gate_id, timeout=0.2)


def test_cancel():
    """Cancel unblocks waiter with GateCancelled."""
    gate = FutureGate()
    gate_id = gate.open("cancel_test")

    raised = {}
    def waiter():
        try:
            gate.wait(gate_id, timeout=10.0)
        except GateCancelled as e:
            raised["reason"] = str(e)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.1)
    gate.cancel(gate_id, reason="user disconnected")
    t.join(timeout=2.0)
    assert "reason" in raised
    assert "user disconnected" in raised["reason"]


def test_cleanup_after_wait():
    """Gate is cleaned up after wait completes."""
    gate = FutureGate()
    gate_id = gate.open("cleanup_test")
    gate.provide(gate_id, "done")
    gate.wait(gate_id, timeout=1.0)
    assert not gate.is_waiting(gate_id)


def test_provide_before_wait():
    """Providing before wait still delivers the value."""
    gate = FutureGate()
    gate_id = gate.open("pre_provide")
    gate.provide(gate_id, "early_value")
    result = gate.wait(gate_id, timeout=1.0)
    assert result == "early_value"


def test_status():
    """Gate reports waiting status."""
    gate = FutureGate()
    gate_id = gate.open("status_test")
    assert gate.is_waiting(gate_id)
    gate.provide(gate_id, "x")
    # After provide, future is done
    info = gate.status(gate_id)
    assert info["done"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_future_gate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement FutureGate**

```python
# src/core/future_gate.py
"""FutureGate — Future-based blocking coordination.

Stolen from ChatDev 2.0's server/services/session_execution.py.

Replaces DB-polling for approval/human-input with memory-level notification.
Zero latency between provide() and wait() unblock.

Usage:
    gate = FutureGate()
    gate_id = gate.open("approval_task_42")

    # In executor thread (blocks):
    result = gate.wait(gate_id, timeout=300)

    # In approval handler (unblocks waiter):
    gate.provide(gate_id, {"approved": True, "by": "human"})

    # Or cancel:
    gate.cancel(gate_id, reason="timeout on TG")
"""
from __future__ import annotations

import logging
import time
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class GateTimeout(Exception):
    """Raised when wait() times out."""
    pass


class GateCancelled(Exception):
    """Raised when gate is cancelled during wait."""
    pass


@dataclass
class _GateEntry:
    gate_id: str
    label: str
    future: Future
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str = ""
    created_at: float = field(default_factory=time.time)


class FutureGate:
    """Manages named Future-based blocking gates.

    Thread-safe. Multiple gates can be open simultaneously.
    Each gate has its own Future + cancel_event.
    """

    def __init__(self):
        self._gates: dict[str, _GateEntry] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def open(self, label: str = "") -> str:
        """Open a new gate. Returns gate_id."""
        with self._lock:
            self._counter += 1
            gate_id = f"gate_{self._counter}"
            self._gates[gate_id] = _GateEntry(
                gate_id=gate_id,
                label=label,
                future=Future(),
            )
            log.debug(f"FutureGate: opened {gate_id} ({label})")
            return gate_id

    def wait(self, gate_id: str, timeout: float = 300.0) -> Any:
        """Block until provide() or cancel() is called.

        Args:
            gate_id: ID returned by open().
            timeout: Max seconds to wait.

        Returns:
            Value passed to provide().

        Raises:
            GateTimeout: If timeout expires.
            GateCancelled: If cancel() is called.
            KeyError: If gate_id doesn't exist.
        """
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                raise KeyError(f"Gate {gate_id} not found")

        try:
            start = time.time()
            poll_interval = 1.0
            while True:
                # Check cancel
                if entry.cancel_event.is_set():
                    raise GateCancelled(entry.cancel_reason or "cancelled")

                elapsed = time.time() - start
                remaining = timeout - elapsed
                if remaining <= 0:
                    raise GateTimeout(
                        f"Gate {gate_id} timed out after {timeout}s"
                    )

                try:
                    result = entry.future.result(
                        timeout=min(poll_interval, remaining)
                    )
                    return result
                except TimeoutError:
                    continue
                except Exception:
                    # Future was cancelled or had an exception
                    if entry.cancel_event.is_set():
                        raise GateCancelled(entry.cancel_reason or "cancelled")
                    raise
        finally:
            self._cleanup(gate_id)

    def provide(self, gate_id: str, value: Any):
        """Unblock the waiter with a value."""
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                log.warning(f"FutureGate: provide called on unknown gate {gate_id}")
                return
        if not entry.future.done():
            entry.future.set_result(value)
            log.debug(f"FutureGate: provided value to {gate_id}")

    def cancel(self, gate_id: str, reason: str = ""):
        """Cancel a gate, unblocking waiter with GateCancelled."""
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return
        entry.cancel_reason = reason
        entry.cancel_event.set()
        if not entry.future.done():
            entry.future.cancel()
        log.debug(f"FutureGate: cancelled {gate_id}: {reason}")

    def is_waiting(self, gate_id: str) -> bool:
        """Check if a gate is open and not yet resolved."""
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return False
            return not entry.future.done() and not entry.cancel_event.is_set()

    def status(self, gate_id: str) -> dict:
        """Get gate status."""
        with self._lock:
            entry = self._gates.get(gate_id)
            if not entry:
                return {"exists": False}
            return {
                "exists": True,
                "gate_id": gate_id,
                "label": entry.label,
                "done": entry.future.done(),
                "cancelled": entry.cancel_event.is_set(),
                "age_s": round(time.time() - entry.created_at, 1),
            }

    def _cleanup(self, gate_id: str):
        """Remove gate entry."""
        with self._lock:
            self._gates.pop(gate_id, None)
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_future_gate.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/future_gate.py tests/core/test_future_gate.py
git commit -m "feat(core): FutureGate for blocking coordination — stolen from ChatDev 2.0"
```

---

### Task 6: FunctionCatalog（函数自省 + JSON Schema 生成）

**Files:**
- Create: `src/core/function_catalog.py`
- Create: `tests/core/test_function_catalog.py`

自动从 Python 函数签名提取参数 schema，生成 tool/collector 的自描述元数据。

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_function_catalog.py
"""Tests for FunctionCatalog — stolen from ChatDev 2.0's utils/function_catalog.py."""
import pytest
from typing import Optional, Annotated
from src.core.function_catalog import introspect_function, ParamMeta


def sample_simple(name: str, count: int = 5) -> str:
    """Greet someone N times."""
    return f"hello {name}" * count


def sample_complex(
    query: str,
    max_results: int = 10,
    include_meta: bool = False,
    tags: list[str] | None = None,
) -> dict:
    """Search with filters.

    Searches the knowledge base with optional filtering.
    """
    return {}


def sample_annotated(
    url: Annotated[str, ParamMeta(description="Target URL to fetch")],
    timeout: Annotated[float, ParamMeta(description="Timeout in seconds")] = 30.0,
) -> str:
    """Fetch a URL."""
    return ""


def test_simple_introspection():
    """Extract name, docstring, params from simple function."""
    info = introspect_function(sample_simple)
    assert info["name"] == "sample_simple"
    assert "Greet someone" in info["description"]
    assert len(info["parameters"]) == 2
    assert info["parameters"]["name"]["type"] == "string"
    assert info["parameters"]["name"]["required"] is True
    assert info["parameters"]["count"]["type"] == "integer"
    assert info["parameters"]["count"]["required"] is False
    assert info["parameters"]["count"]["default"] == 5


def test_complex_introspection():
    """Extract complex types correctly."""
    info = introspect_function(sample_complex)
    assert info["parameters"]["max_results"]["type"] == "integer"
    assert info["parameters"]["include_meta"]["type"] == "boolean"
    assert info["parameters"]["tags"]["type"] == "array"
    assert info["parameters"]["tags"]["required"] is False


def test_annotated_introspection():
    """Extract ParamMeta from Annotated types."""
    info = introspect_function(sample_annotated)
    assert info["parameters"]["url"]["description"] == "Target URL to fetch"
    assert info["parameters"]["timeout"]["description"] == "Timeout in seconds"
    assert info["parameters"]["timeout"]["default"] == 30.0


def test_json_schema_output():
    """Generate valid JSON Schema for function parameters."""
    info = introspect_function(sample_simple)
    schema = info["json_schema"]
    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    assert schema["properties"]["name"]["type"] == "string"
    assert "name" in schema["required"]
    assert "count" not in schema["required"]


def test_no_docstring():
    """Functions without docstring get empty description."""
    def bare(x: int) -> int:
        return x
    info = introspect_function(bare)
    assert info["description"] == ""
    assert info["parameters"]["x"]["type"] == "integer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_function_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement FunctionCatalog**

```python
# src/core/function_catalog.py
"""FunctionCatalog — automatic function introspection + JSON Schema generation.

Stolen from ChatDev 2.0's utils/function_catalog.py.

Extracts parameter metadata from Python type annotations, including
Annotated[Type, ParamMeta] for rich descriptions. Generates JSON Schema
compatible with OpenAI tool-calling format.

Usage:
    from src.core.function_catalog import introspect_function, ParamMeta

    info = introspect_function(my_func)
    # info["name"], info["description"], info["parameters"], info["json_schema"]
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Annotated, get_args, get_origin, get_type_hints, Union


@dataclass
class ParamMeta:
    """Rich metadata for function parameters via Annotated."""
    description: str = ""
    enum: list[str] | None = None
    examples: list[Any] | None = None


# Python type → JSON Schema type mapping
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _resolve_type(annotation: Any) -> tuple[str, ParamMeta | None]:
    """Resolve a type annotation to JSON Schema type string.

    Handles: primitives, Optional, list, dict, Annotated, Union.
    Returns (json_type, optional_param_meta).
    """
    if annotation is inspect.Parameter.empty or annotation is Any:
        return "string", None

    origin = get_origin(annotation)

    # Annotated[Type, ParamMeta(...)]
    if origin is Annotated:
        args = get_args(annotation)
        base_type = args[0] if args else str
        meta = None
        for arg in args[1:]:
            if isinstance(arg, ParamMeta):
                meta = arg
                break
        json_type, _ = _resolve_type(base_type)
        return json_type, meta

    # Optional[X] = Union[X, None]
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            return _resolve_type(args[0])
        return "string", None

    # list[X]
    if origin is list:
        return "array", None

    # dict[K, V]
    if origin is dict:
        return "object", None

    # Direct type
    if isinstance(annotation, type):
        return _TYPE_MAP.get(annotation, "string"), None

    return "string", None


def introspect_function(fn: Callable) -> dict[str, Any]:
    """Extract full metadata from a function.

    Returns:
        {
            "name": str,
            "description": str,
            "parameters": {param_name: {type, required, default, description}},
            "json_schema": {type: "object", properties: {...}, required: [...]},
        }
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}

    # Description from docstring (first paragraph)
    doc = inspect.getdoc(fn) or ""
    first_para = doc.split("\n\n")[0].strip() if doc else ""
    description = first_para[:600]

    parameters: dict[str, dict[str, Any]] = {}
    json_properties: dict[str, dict[str, Any]] = {}
    required_params: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls", "_context"):
            continue

        annotation = hints.get(name, param.annotation)
        json_type, param_meta = _resolve_type(annotation)
        has_default = param.default is not inspect.Parameter.empty
        is_required = not has_default

        param_info: dict[str, Any] = {
            "type": json_type,
            "required": is_required,
        }
        prop: dict[str, Any] = {"type": json_type}

        if has_default:
            param_info["default"] = param.default
            prop["default"] = param.default

        if param_meta and param_meta.description:
            param_info["description"] = param_meta.description
            prop["description"] = param_meta.description

        if param_meta and param_meta.enum:
            param_info["enum"] = param_meta.enum
            prop["enum"] = param_meta.enum

        parameters[name] = param_info
        json_properties[name] = prop

        if is_required:
            required_params.append(name)

    json_schema = {
        "type": "object",
        "properties": json_properties,
    }
    if required_params:
        json_schema["required"] = required_params

    return {
        "name": fn.__name__,
        "description": description,
        "parameters": parameters,
        "json_schema": json_schema,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/core/test_function_catalog.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/function_catalog.py tests/core/test_function_catalog.py
git commit -m "feat(core): FunctionCatalog with JSON Schema introspection — stolen from ChatDev 2.0"
```

---

### Post-Implementation: Integration Notes

Each module is standalone and tested. Integration into existing code is a separate step:

1. **Registry** → Replace `_REGISTRY` dict in `component_spec.py` with `Registry("components")`
2. **ExecutionContext** → Refactor `TaskExecutor.execute_task()` to build context then pass it
3. **EventStream** → Add to Dashboard SSE endpoint, replace full-refresh with cursor polling
4. **ResilientRetry** → Use in `executor.py`'s rollout loop for LLM API calls
5. **FutureGate** → Replace `approval.py`'s DB-polling with `FutureGate.wait()`
6. **FunctionCatalog** → Use in collector registry and tool discovery for auto-schema
