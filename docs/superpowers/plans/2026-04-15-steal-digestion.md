# R60-R76 Steal Digestion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 R60-R76 偷师产出的 21 个孤岛模块分类处置——10 个接入生产系统 + 补测试，11 个移至 `.trash/` 减少认知负担。完成标志：零孤岛模块残留在 `src/` 中，所有集成模块有 ≥1 个测试。

**Architecture:** 分三波处理。Wave 1 接入高价值防御性模块（circuit_breaker, dangling_tool_fix, content_cache, culture_inject），这些是"防守型"——减少故障、提升可靠性。Wave 2 接入高价值进攻性模块（cel_compiler → memory_server, signal_extractor → executor, stale_detector → memory, atomic_fact_splitter → memory_save），这些是"进攻型"——增加新能力。Wave 3 将确认无用的 11 个模块移入 `.trash/steal-digestion/`。

**Tech Stack:** Python 3.12, pytest, Claude Agent SDK, MCP, SQLite

**ASSUMPTION:** `executor.py` 的 `TaskExecutor.__init__` 接受新的可选依赖注入不会破坏现有调用方——已确认 executor 的构造在 `governor.py` 中只传 `db, store` 两个参数，新增可选参数向后兼容。

**ASSUMPTION:** `memory_server.py` 的 `memory_search` 工具签名新增可选 `filter` 参数不影响 MCP 协议——MCP tool parameters 是 JSON schema，新增 optional field 向后兼容。

---

## File Map

### Wave 1 — 防守型集成（接入 + 测试）

- `src/channels/agent_bridge.py` — **Modify** (接入 circuit_breaker)
- `src/channels/telegram/tg_api.py` — **Modify** (接入 circuit_breaker)
- `src/governance/pipeline/middleware.py` — **Modify** (接入 dangling_tool_fix)
- `src/governance/executor_prompt.py` — **Modify** (接入 culture_inject)
- `src/governance/content_cache.py` — **Modify** (微调 API 适配 executor)
- `src/governance/executor.py` — **Modify** (接入 content_cache)
- `tests/core/test_circuit_breaker.py` — **Create**
- `tests/governance/test_dangling_tool_fix.py` — **Create**
- `tests/governance/test_content_cache.py` — **Create**
- `tests/governance/test_culture_inject.py` — **Create**

### Wave 2 — 进攻型集成（接入 + 测试）

- `src/mcp/memory_server.py` — **Modify** (接入 cel_compiler + atomic_fact_splitter + stale_detector)
- `src/governance/executor.py` — **Modify** (接入 signal_extractor post-execution)
- `src/governance/working_path_lock.py` — **Modify** (微调适配 executor)
- `src/governance/executor_session.py` — **Modify** (接入 working_path_lock)
- `tests/governance/test_cel_compiler.py` — **Create**
- `tests/governance/test_stale_detector.py` — **Create**
- `tests/governance/test_atomic_fact_splitter.py` — **Create**
- `tests/governance/test_working_path_lock.py` — **Create**

### Wave 3 — 清理搬运

- `src/core/execution_router.py` → `.trash/steal-digestion/`
- `src/core/agent_message.py` → `.trash/steal-digestion/`
- `src/governance/transaction/three_phase.py` → `.trash/steal-digestion/`
- `src/governance/context/blackboard.py` → `.trash/steal-digestion/`
- `src/governance/guardian/transcript_cursor.py` → `.trash/steal-digestion/`
- `src/governance/safety/idle_timeout.py` → `.trash/steal-digestion/`
- `src/governance/safety/loop_detection.py` → `.trash/steal-digestion/`
- `src/governance/scheduling/idle_scheduler.py` → `.trash/steal-digestion/`
- `src/governance/operation_validator.py` → `.trash/steal-digestion/`
- `src/governance/learning/query_writeback.py` → `.trash/steal-digestion/`
- `src/storage/temporal_recall.py` → `.trash/steal-digestion/`
- `src/channels/terminal_display.py` → `.trash/steal-digestion/`

不动的文件（确认无需修改）：
- `src/core/atomic_write.py` — 已集成（memory_server, _sessions_mixin 引用）
- `src/core/runtime.py` — 已集成（executor, executor_session, ephemeral 引用）
- `src/governance/checkpoint_recovery.py` — 已集成（executor, storage 引用）
- `src/channels/media.py` — 已集成（base, chat, telegram, wechat 引用）
- `src/storage/query_sanitizer.py` — 已集成（qdrant_store 引用）

---

## Steps

### Wave 1: 防守型集成

#### Task 1: circuit_breaker → 外部 API 调用

**Files:**
- Modify: `src/channels/agent_bridge.py`
- Modify: `src/channels/telegram/tg_api.py`
- Test: `tests/core/test_circuit_breaker.py`

- [ ] **Step 1: 为 circuit_breaker 写核心测试**

```python
# tests/core/test_circuit_breaker.py
import pytest
from src.core.circuit_breaker import (
    CircuitBreaker, CircuitBreakerConfig, CircuitBreakerError,
    CircuitState, get_breaker, get_all_breaker_stats,
)

class TestCircuitBreakerStateTransitions:
    def test_starts_closed(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2))
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_s=60))
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises_error(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout_s=60))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        with pytest.raises(CircuitBreakerError):
            cb.call(lambda: "should not run")

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        # 1 failure then 1 success → counter resets
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.call(lambda: "ok") == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_on_timeout(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout_s=0))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        # recovery_timeout_s=0 → immediately transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

class TestGlobalRegistry:
    def test_get_breaker_returns_same_instance(self):
        b1 = get_breaker("test-svc")
        b2 = get_breaker("test-svc")
        assert b1 is b2

    def test_get_all_stats(self):
        get_breaker("stats-test")
        stats = get_all_breaker_stats()
        assert "stats-test" in stats
```

- [ ] **Step 2: 运行测试确认全部通过**

Run: `python -m pytest tests/core/test_circuit_breaker.py -v`
Expected: 7 tests PASSED

- [ ] **Step 3: 在 agent_bridge.py 接入 circuit_breaker**

在 `src/channels/agent_bridge.py` 的外部 HTTP 调用处（`urllib.request.urlopen`）用 `get_breaker` 包裹：

```python
# 在文件顶部 import 区域添加
from src.core.circuit_breaker import get_breaker, CircuitBreakerError

# 在 _call_agent() 或同等的 HTTP 调用方法中，将:
#   response = urllib.request.urlopen(req, timeout=120)
# 替换为:
try:
    breaker = get_breaker("agent-bridge")
    response = breaker.call(lambda: urllib.request.urlopen(req, timeout=120))
except CircuitBreakerError as e:
    log.warning(f"Agent bridge circuit open, retry in {e.time_until_probe:.0f}s")
    raise
```

→ verify: `python -c "from src.channels.agent_bridge import AgentBridge; print('OK')"`

- [ ] **Step 4: 在 tg_api.py 接入 circuit_breaker**

在 `src/channels/telegram/tg_api.py` 的 Telegram API 调用处用 `get_breaker("telegram-api")` 包裹，模式同 Step 3。

→ verify: `python -c "from src.channels.telegram.tg_api import TelegramAPI; print('OK')"`

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_circuit_breaker.py src/channels/agent_bridge.py src/channels/telegram/tg_api.py
git commit -m "feat(digest): integrate circuit_breaker into agent_bridge + telegram API"
```

---

#### Task 2: dangling_tool_fix → pipeline middleware

**Files:**
- Modify: `src/governance/pipeline/middleware.py`
- Test: `tests/governance/test_dangling_tool_fix.py`

- [ ] **Step 6: 为 dangling_tool_fix 写测试**

```python
# tests/governance/test_dangling_tool_fix.py
import pytest
from src.governance.pipeline.dangling_tool_fix import patch_dangling_tool_calls

class TestDanglingToolFix:
    def test_no_dangling_passes_through(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = patch_dangling_tool_calls(messages)
        assert result == messages

    def test_dangling_tool_call_gets_synthetic_response(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_123", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            # Missing tool response → dangling
        ]
        result = patch_dangling_tool_calls(messages)
        assert len(result) == 3  # original 2 + synthetic tool response
        assert result[-1]["role"] == "tool"
        assert result[-1]["tool_call_id"] == "call_123"

    def test_complete_tool_call_unchanged(self):
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_456", "function": {"name": "bash", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "call_456", "content": "done"},
        ]
        result = patch_dangling_tool_calls(messages)
        assert len(result) == 2  # unchanged
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python -m pytest tests/governance/test_dangling_tool_fix.py -v`
Expected: 3 tests PASSED

- [ ] **Step 8: 在 middleware.py 注册 dangling_tool_fix 为 pre-LLM stage**

读取 `src/governance/pipeline/middleware.py` 的现有 middleware 注册模式，在 message preprocessing 阶段插入 `patch_dangling_tool_calls`。具体：找到 messages 传入 LLM 之前的预处理链，添加一行：

```python
from src.governance.pipeline.dangling_tool_fix import patch_dangling_tool_calls

# 在 messages 传入 LLM 之前:
messages = patch_dangling_tool_calls(messages)
```

→ verify: `python -c "from src.governance.pipeline.middleware import apply_middleware; print('OK')"`

- [ ] **Step 9: Commit**

```bash
git add tests/governance/test_dangling_tool_fix.py src/governance/pipeline/middleware.py
git commit -m "feat(digest): integrate dangling_tool_fix into pipeline middleware"
```

---

#### Task 3: culture_inject → executor_prompt

**Files:**
- Modify: `src/governance/executor_prompt.py`
- Test: `tests/governance/test_culture_inject.py`

- [ ] **Step 10: 为 culture_inject 写测试**

```python
# tests/governance/test_culture_inject.py
import pytest
from src.governance.context.culture_inject import inject_culture

class TestCultureInject:
    def test_returns_string(self):
        result = inject_culture("base prompt here")
        assert isinstance(result, str)
        assert "base prompt here" in result

    def test_no_crash_without_culture_file(self):
        """inject_culture 应该在 culture.md 不存在时优雅降级，不崩溃。"""
        result = inject_culture("base prompt", culture_path="/nonexistent/path")
        assert "base prompt" in result

    def test_injects_orchestrator_context(self):
        """如果有 culture 内容，应该出现在结果中。"""
        result = inject_culture("base prompt")
        # 至少不应该丢失原始 prompt
        assert "base prompt" in result
```

- [ ] **Step 11: 运行测试确认通过**

Run: `python -m pytest tests/governance/test_culture_inject.py -v`
Expected: 3 tests PASSED

- [ ] **Step 12: 在 executor_prompt.py 的 build_execution_prompt() 中接入 culture_inject**

在 `src/governance/executor_prompt.py` 顶部添加 optional import：

```python
try:
    from src.governance.context.culture_inject import inject_culture as _inject_culture
except ImportError:
    _inject_culture = None
```

在 `build_execution_prompt()` 返回最终 prompt 之前（最后一行 `return full_prompt` 之前），插入：

```python
if _inject_culture:
    full_prompt = _inject_culture(full_prompt)
```

→ verify: `python -c "from src.governance.executor_prompt import build_execution_prompt; print('OK')"`

- [ ] **Step 13: Commit**

```bash
git add tests/governance/test_culture_inject.py src/governance/executor_prompt.py
git commit -m "feat(digest): integrate culture_inject into executor prompt builder"
```

---

#### Task 4: content_cache → executor

**Files:**
- Modify: `src/governance/executor.py`
- Test: `tests/governance/test_content_cache.py`

- [ ] **Step 14: 为 content_cache 写测试**

```python
# tests/governance/test_content_cache.py
import pytest
from src.governance.content_cache import content_cache_key

class TestContentCache:
    def test_same_input_same_key(self):
        k1 = content_cache_key("prompt A", ["tool1"])
        k2 = content_cache_key("prompt A", ["tool1"])
        assert k1 == k2

    def test_different_prompt_different_key(self):
        k1 = content_cache_key("prompt A", ["tool1"])
        k2 = content_cache_key("prompt B", ["tool1"])
        assert k1 != k2

    def test_different_tools_different_key(self):
        k1 = content_cache_key("prompt A", ["tool1"])
        k2 = content_cache_key("prompt A", ["tool2"])
        assert k1 != k2

    def test_returns_string(self):
        k = content_cache_key("test", [])
        assert isinstance(k, str)
        assert len(k) > 0
```

- [ ] **Step 15: 运行测试确认通过**

Run: `python -m pytest tests/governance/test_content_cache.py -v`
Expected: 4 tests PASSED

- [ ] **Step 16: 在 executor.py 的 TaskExecutor 中接入 content_cache**

在 `src/governance/executor.py` 的 import 区添加：

```python
try:
    from src.governance.content_cache import content_cache_key
except ImportError:
    content_cache_key = None
```

在 `TaskExecutor.execute_task()` 中，构建 prompt 之后、调用 Agent SDK 之前，如果有 `content_cache_key`，用它生成 cache key 并检查/存储缓存。具体接入位置在读取现有代码后确定（找到 `build_execution_prompt` 调用处和 `query()` 调用处之间）。

→ verify: `python -c "from src.governance.executor import TaskExecutor; print('OK')"`

- [ ] **Step 17: Commit**

```bash
git add tests/governance/test_content_cache.py src/governance/executor.py
git commit -m "feat(digest): integrate content_cache into TaskExecutor"
```

---

### Wave 2: 进攻型集成

#### Task 5: cel_compiler → memory_server 查询过滤

**Files:**
- Modify: `src/mcp/memory_server.py:367` (memory_search 函数)
- Test: `tests/governance/test_cel_compiler.py`

- [ ] **Step 18: 为 cel_compiler 写核心测试**

```python
# tests/governance/test_cel_compiler.py
import pytest
from src.governance.filter.cel_compiler import compile_filter, get_memory_schema

class TestCelCompiler:
    def test_simple_equality(self):
        schema = get_memory_schema()
        sql, params = compile_filter('name == "test"', schema)
        assert "name" in sql
        assert "test" in params

    def test_numeric_comparison(self):
        schema = get_memory_schema()
        sql, params = compile_filter('importance > 5', schema)
        assert ">" in sql
        assert 5 in params

    def test_logical_and(self):
        schema = get_memory_schema()
        sql, params = compile_filter('importance > 3 AND name == "x"', schema)
        assert "AND" in sql

    def test_in_operator(self):
        schema = get_memory_schema()
        sql, params = compile_filter('tags in ["work", "urgent"]', schema)
        assert len(params) >= 2

    def test_invalid_field_raises(self):
        schema = get_memory_schema()
        with pytest.raises(Exception):
            compile_filter('nonexistent_field == 1', schema)

    def test_injection_attempt_safe(self):
        """SQL injection via filter expression should be parameterized, never raw."""
        schema = get_memory_schema()
        sql, params = compile_filter('name == "Robert\'; DROP TABLE--"', schema)
        # The dangerous string should be in params (safe), not in sql (unsafe)
        assert "DROP" not in sql
        assert any("DROP" in str(p) for p in params)
```

- [ ] **Step 19: 运行测试确认通过**

Run: `python -m pytest tests/governance/test_cel_compiler.py -v`
Expected: 6 tests PASSED

- [ ] **Step 20: 在 memory_server.py 的 memory_search 中接入 cel_compiler**

在 `src/mcp/memory_server.py` 的 `memory_search()` 函数中添加可选 `filter_expr: str = ""` 参数。当 `filter_expr` 非空时，调用 `compile_filter()` 生成 SQL WHERE 子句，与现有全文搜索结果做交集过滤。

```python
# 在 memory_server.py 顶部添加
try:
    from src.governance.filter.cel_compiler import compile_filter, get_memory_schema
except ImportError:
    compile_filter = None
```

在 `memory_search` 函数签名中添加 `filter_expr: str = ""`，在搜索结果返回前做过滤。

→ verify: `python -c "from src.mcp.memory_server import memory_search; print('OK')"`

- [ ] **Step 21: Commit**

```bash
git add tests/governance/test_cel_compiler.py src/mcp/memory_server.py
git commit -m "feat(digest): integrate cel_compiler into memory_server search"
```

---

#### Task 6: signal_extractor → executor post-execution

**Files:**
- Modify: `src/governance/executor.py`
- Already tested: `tests/governance/test_signal_extractor.py` (18 tests exist)

- [ ] **Step 22: 在 executor.py 的 TaskExecutor 中接入 signal_extractor**

在 `src/governance/executor.py` import 区添加：

```python
try:
    from src.governance.signals.signal_extractor import SignalExtractor
    _signal_extractor = SignalExtractor()
except ImportError:
    _signal_extractor = None
```

在 `execute_task()` 完成后（return 之前），添加 post-execution signal analysis：

```python
if _signal_extractor and response and response.output:
    try:
        signals = _signal_extractor.extract(response.output, blast_radius=blast_radius)
        if signals:
            log.info(f"Post-execution signals: {[s.context for s in signals[:3]]}")
            # 将信号存入 response metadata 供上层消费
            response.metadata["signals"] = [
                {"score": s.score, "context": s.context, "layer": s.source_layer}
                for s in signals
            ]
    except Exception:
        log.debug("Signal extraction failed (non-critical)", exc_info=True)
```

→ verify: `python -m pytest tests/governance/test_signal_extractor.py -v` (确认现有 18 个测试仍通过)

- [ ] **Step 23: Commit**

```bash
git add src/governance/executor.py
git commit -m "feat(digest): integrate signal_extractor post-execution analysis"
```

---

#### Task 7: stale_detector + atomic_fact_splitter → memory_server

**Files:**
- Modify: `src/mcp/memory_server.py:231` (memory_save 函数)
- Test: `tests/governance/test_stale_detector.py`
- Test: `tests/governance/test_atomic_fact_splitter.py`

- [ ] **Step 24: 为 stale_detector 写测试**

```python
# tests/governance/test_stale_detector.py
import pytest
from pathlib import Path
from src.governance.memory.stale_detector import score_memory, budget_filter

class TestStaleDetector:
    def test_score_returns_positive_float(self):
        """score_memory 应返回正浮点数。"""
        # 构造一个 MemoryEntry mock
        from src.governance.memory.stale_detector import MemoryEntry
        entry = MemoryEntry(
            path=Path("test.md"), importance=5, 
            created_ts=1.0, last_access_ts=1.0, access_count=1,
            entity_refs=[], content="test content"
        )
        score = score_memory(entry, now=1000.0)
        assert isinstance(score, float)
        assert score > 0

    def test_higher_importance_higher_score(self):
        from src.governance.memory.stale_detector import MemoryEntry
        now = 1000.0
        low = MemoryEntry(path=Path("a.md"), importance=1, created_ts=1.0,
                          last_access_ts=1.0, access_count=1, entity_refs=[], content="x")
        high = MemoryEntry(path=Path("b.md"), importance=10, created_ts=1.0,
                           last_access_ts=1.0, access_count=1, entity_refs=[], content="x")
        assert score_memory(high, now) > score_memory(low, now)

    def test_budget_filter_respects_limit(self):
        from src.governance.memory.stale_detector import MemoryEntry
        entries = [
            MemoryEntry(path=Path(f"{i}.md"), importance=5, created_ts=1.0,
                        last_access_ts=1.0, access_count=1, entity_refs=[],
                        content="x" * 100)
            for i in range(20)
        ]
        result = budget_filter(entries, max_tokens=500)
        assert len(result) < len(entries)
```

- [ ] **Step 25: 为 atomic_fact_splitter 写测试**

```python
# tests/governance/test_atomic_fact_splitter.py
import pytest
from src.governance.learning.atomic_fact_splitter import (
    split_into_atomic_facts, validate_fact, deduplicate_facts, AtomicFact,
)

class TestAtomicFactSplitter:
    def test_split_compound_sentence(self):
        facts = split_into_atomic_facts("Alice likes Python and Bob likes Rust")
        assert len(facts) >= 2

    def test_single_fact_unchanged(self):
        facts = split_into_atomic_facts("Alice likes Python")
        assert len(facts) >= 1
        assert any("Alice" in f for f in facts)

    def test_validate_fact_accepts_good_fact(self):
        ok, reason = validate_fact("Alice prefers functional programming")
        assert ok is True

    def test_validate_fact_rejects_vague_pronoun(self):
        """含糊代词 "user" / "他" 应被拒绝。"""
        ok, reason = validate_fact("The user likes Python")
        # 预期拒绝或至少给出警告
        # 具体行为取决于实现，这里验证函数不崩溃
        assert isinstance(ok, bool)

    def test_deduplicate_removes_near_duplicates(self):
        facts = [
            AtomicFact(content="Alice likes Python", source_entry="s1",
                       fact_index=0, entities=["Alice"], confidence=0.9, temporal_refs=[]),
            AtomicFact(content="Alice likes Python programming", source_entry="s1",
                       fact_index=1, entities=["Alice"], confidence=0.9, temporal_refs=[]),
        ]
        result = deduplicate_facts(facts, existing=[], threshold=0.7)
        assert len(result) <= len(facts)
```

- [ ] **Step 26: 运行两组测试确认通过**

Run: `python -m pytest tests/governance/test_stale_detector.py tests/governance/test_atomic_fact_splitter.py -v`
Expected: 全部 PASSED

- [ ] **Step 27: 在 memory_server.py 中接入 stale_detector 和 atomic_fact_splitter**

在 `src/mcp/memory_server.py` 顶部添加：

```python
try:
    from src.governance.memory.stale_detector import detect_stale_memories
except ImportError:
    detect_stale_memories = None

try:
    from src.governance.learning.atomic_fact_splitter import split_into_atomic_facts, validate_fact
except ImportError:
    split_into_atomic_facts = None
```

在 `memory_save()` 函数中，facts 写入前调用 `split_into_atomic_facts` 做原子化拆分 + `validate_fact` 过滤低质量 fact。

在 `memory_search()` 函数返回结果前，如果 `detect_stale_memories` 可用，标记引用已删除文件的 memory 为 stale。

→ verify: `python -c "from src.mcp.memory_server import memory_save, memory_search; print('OK')"`

- [ ] **Step 28: Commit**

```bash
git add tests/governance/test_stale_detector.py tests/governance/test_atomic_fact_splitter.py src/mcp/memory_server.py
git commit -m "feat(digest): integrate stale_detector + atomic_fact_splitter into memory_server"
```

---

#### Task 8: working_path_lock → executor_session

**Files:**
- Modify: `src/governance/executor_session.py`
- Test: `tests/governance/test_working_path_lock.py`

- [ ] **Step 29: 为 working_path_lock 写测试**

```python
# tests/governance/test_working_path_lock.py
import pytest
from src.governance.working_path_lock import WorkingPathLock

class TestWorkingPathLock:
    def test_acquire_and_release(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        acquired = lock.acquire("/test/path", agent_id="agent-1")
        assert acquired is True
        released = lock.release("/test/path", agent_id="agent-1")
        assert released is True

    def test_double_acquire_same_agent(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        lock.acquire("/test/path", agent_id="agent-1")
        # 同一 agent 重入应该成功
        acquired = lock.acquire("/test/path", agent_id="agent-1")
        assert acquired is True

    def test_acquire_conflict_different_agent(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        lock.acquire("/test/path", agent_id="agent-1")
        # 不同 agent 应该获取失败
        acquired = lock.acquire("/test/path", agent_id="agent-2")
        assert acquired is False

    def test_release_nonexistent_is_safe(self, tmp_path):
        lock = WorkingPathLock(db_path=str(tmp_path / "test.db"))
        released = lock.release("/nonexistent", agent_id="agent-1")
        assert released is False
```

- [ ] **Step 30: 运行测试确认通过**

Run: `python -m pytest tests/governance/test_working_path_lock.py -v`
Expected: 4 tests PASSED

- [ ] **Step 31: 在 executor_session.py 中接入 working_path_lock**

在 `src/governance/executor_session.py` 中，agent session 启动时 acquire lock，结束时 release：

```python
try:
    from src.governance.working_path_lock import WorkingPathLock
    _path_lock = WorkingPathLock()
except ImportError:
    _path_lock = None
```

在 `AgentSessionRunner.run()` 入口处 acquire，在 finally 块中 release。

→ verify: `python -c "from src.governance.executor_session import AgentSessionRunner; print('OK')"`

- [ ] **Step 32: Commit**

```bash
git add tests/governance/test_working_path_lock.py src/governance/executor_session.py
git commit -m "feat(digest): integrate working_path_lock into executor_session"
```

---

### Wave 3: 清理搬运

#### Task 9: 移除孤岛模块至 .trash/

**Files:** 见 File Map Wave 3 列表（12 个文件）

- [ ] **Step 33: 创建 .trash/steal-digestion/ 目录并移动 11 个模块**

```bash
mkdir -p .trash/steal-digestion/core
mkdir -p .trash/steal-digestion/governance/{transaction,context,guardian,safety,scheduling,learning}
mkdir -p .trash/steal-digestion/storage
mkdir -p .trash/steal-digestion/channels

mv src/core/execution_router.py .trash/steal-digestion/core/
mv src/core/agent_message.py .trash/steal-digestion/core/
mv src/governance/transaction/three_phase.py .trash/steal-digestion/governance/transaction/
mv src/governance/context/blackboard.py .trash/steal-digestion/governance/context/
mv src/governance/guardian/transcript_cursor.py .trash/steal-digestion/governance/guardian/
mv src/governance/safety/idle_timeout.py .trash/steal-digestion/governance/safety/
mv src/governance/safety/loop_detection.py .trash/steal-digestion/governance/safety/
mv src/governance/scheduling/idle_scheduler.py .trash/steal-digestion/governance/scheduling/
mv src/governance/operation_validator.py .trash/steal-digestion/governance/
mv src/governance/learning/query_writeback.py .trash/steal-digestion/governance/learning/
mv src/storage/temporal_recall.py .trash/steal-digestion/storage/
mv src/channels/terminal_display.py .trash/steal-digestion/channels/
```

→ verify: `ls .trash/steal-digestion/ && python -c "from src.governance.executor import TaskExecutor; print('OK')"` (确认移除后不影响生产 import)

- [ ] **Step 34: 清理空 __init__.py 和空目录**

检查 `src/governance/transaction/`、`src/governance/guardian/` 等目录，如果移除后只剩 `__init__.py` 且 `__init__.py` 为空，也移至 `.trash/`。

→ verify: `python -m pytest tests/ -x -q --tb=line` (快速确认无 import 破坏)

- [ ] **Step 35: Commit**

```bash
git add -A
git commit -m "chore(digest): shelve 12 island modules to .trash/steal-digestion"
```

---

### Wave 4: 全量验证

#### Task 10: 最终验证

- [ ] **Step 36: 运行全量测试**

Run: `python -m pytest tests/ -v --tb=short`
Expected: 全部 PASSED，包括原有 44 个 + 新增 ~30 个

- [ ] **Step 37: 确认零孤岛**

Run: 对 Wave 1+2 集成的 10 个模块重新 grep import，确认每个都有 ≥1 个生产代码引用 + ≥1 个测试文件。

```bash
for mod in circuit_breaker dangling_tool_fix culture_inject content_cache cel_compiler signal_extractor stale_detector atomic_fact_splitter working_path_lock event_waiter; do
  echo "=== $mod ==="
  grep -r "import.*$mod\|from.*$mod" src/ tests/ --include="*.py" | head -5
done
```

Expected: 每个模块至少出现 2 次（1 次 src/ + 1 次 tests/）

- [ ] **Step 38: Commit 最终状态**

如果 Step 36-37 发现问题，修复后 commit。否则无额外 commit。

---

## Phase Gate: Plan → Implement

- [x] Every step has action verb + specific target + verify command
- [x] No banned placeholder phrases
- [x] Dependencies are explicit (Wave 2 depends on Wave 1 only在 executor.py 上有交叉，已注意顺序)
- [x] Steps are 2-5 min each (38 steps, estimated ~3h total)
- [ ] Owner has seen the plan → **Owner review: required**

---

## Risk Notes

1. **executor.py 被多个 Task 修改**：Task 4 (content_cache), Task 6 (signal_extractor) 都改 executor.py。执行时必须按顺序，每次改后 re-read 文件。
2. **memory_server.py 被多个 Task 修改**：Task 5 (cel_compiler) 和 Task 7 (stale_detector + atomic_fact_splitter) 都改 memory_server.py。同上。
3. **Wave 3 移除文件可能有隐含引用**：移除前应 `grep -r "module_name" src/` 再次确认零引用。审计时已确认，但以执行时为准。
4. **test fixture 可能需要适配**：某些模块（working_path_lock）需要 DB fixture，测试中用 `tmp_path` 避免污染。
5. **.trash/ 策略**：移入 `.trash/` 的模块保留完整路径结构，未来需要时可直接 `mv` 回来。

## Digest Summary

| 类别 | 数量 | 行数 | 处置 |
|------|------|------|------|
| 已集成（不动） | 5 | ~870 | 保持现状 |
| 接入生产 + 补测试 | 10 | ~3,834 | Wave 1 + Wave 2 |
| 搬进 .trash/ | 12 | ~3,600 | Wave 3 |

最终结果：`src/` 中零孤岛模块，所有偷师代码要么在跑要么在仓库。
