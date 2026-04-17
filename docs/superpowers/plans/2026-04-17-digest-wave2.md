# Plan: Digest Wave 2 — 恢复 4 个被低估的归档模块

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Branch:** `feat/digest-wave2`（从 main 切出，全部工作在此分支完成，最后由 owner 决定合并时机）
>
> **Upstream context（不重复评估）:** 本计划是 `docs/superpowers/plans/2026-04-15-steal-digestion.md` 的 Wave 2 后续。Wave 1 已合并（R60–R76 digestion wave 1-4, commit `5dbc470`）。本 Wave 只处理 4 个在复盘中被判定为"低估"的归档模块，不扩大范围。
>
> **Wave 3 互斥提醒:** `executor_session.py`（Task 2 修改）与 `src/mcp/memory_server.py`（Task 4 修改）在规划中的 Wave 3 仍会被触碰。本 Wave 的修改必须保持局部、以函数/行号为锚，避免 Wave 3 合并冲突。每个 Task 独立 commit。

## Goal

将 `.trash/steal-digestion/` 下的 4 个归档模块（`idle_timeout` / `query_writeback` / `blackboard` / `three_phase`）恢复到 `src/governance/` 对应位置，每个模块带单元测试 + 一处具体集成点修改，分 4 个独立 commit 完成，`pytest tests/governance/test_idle_timeout.py tests/governance/test_query_writeback.py tests/governance/test_blackboard.py tests/governance/test_three_phase.py` 全绿。

## Architecture

4 个模块各自独立，通过 `mv`（非 `cp`）从 `.trash/` 移出。所有模块原始代码已实现并通过原作者的内部验证，本 Wave 仅补齐测试 + 粘合到现有调用点。集成点数量严格限制：每个模块仅修改 1 个上游文件（query_writeback 在 `executor_session.py` 内修改 2 处函数，但仍算作同一文件）。

## Tech Stack

Python 3.11+ / pytest / asyncio / FastMCP (`src/mcp/memory_server.py`) / 现有 governance 包骨架（`src/governance/safety/`、`src/governance/context/`、`src/governance/learning/` 已存在；`src/governance/transaction/` 本 Wave 新建）。

---

## File Map

**Create (新增文件):**

- `src/governance/safety/idle_timeout.py` — 从 `.trash/steal-digestion/governance/safety/idle_timeout.py` 移入（7256 字节）
- `src/governance/learning/query_writeback.py` — 从 `.trash/steal-digestion/governance/learning/query_writeback.py` 移入（4992 字节）
- `src/governance/context/blackboard.py` — 从 `.trash/steal-digestion/governance/context/blackboard.py` 移入（7474 字节）
- `src/governance/transaction/__init__.py` — 新建空 `__init__.py`（使 transaction 成为 Python 包）
- `src/governance/transaction/three_phase.py` — 从 `.trash/steal-digestion/governance/transaction/three_phase.py` 移入（8756 字节）
- `tests/governance/test_idle_timeout.py` — idle_timeout 单元测试（3 个测试用例）
- `tests/governance/test_query_writeback.py` — query_writeback 单元测试（3 个测试用例）
- `tests/governance/test_blackboard.py` — blackboard 单元测试（4 个测试用例）
- `tests/governance/test_three_phase.py` — three_phase 单元测试（3 个测试用例）

**Modify (集成点修改):**

- `src/governance/executor_stream.py:98-162` — 在 `ExecutionStream` 类上新增 `execute_guarded(task_id, timeout_s)` 方法，用 `with_idle_timeout` 包裹现有 `execute()` 生成器
- `src/governance/executor_session.py:205-254`（`prefill`）+ `src/governance/executor_session.py:256-331`（`finalize`）— prefill 把 `prompt` 放进返回字典；finalize 在 return 前调用 `save_query_result`
- `src/governance/council.py:499-502`（`deliberate` 调用 `_stage3_synthesize` 之前）— 用 opinions 构造 reflexion blackboard，将其 `format_for_prompt` 输出追加到传给 Stage 3 的 context
- `src/mcp/memory_server.py:251-402`（`memory_save`）— 把函数转为 async，抽出 `_prepare_supersede` / `_commit_writes` / `_supplement_audit` 三个内部 async 闭包，经 `three_phase_write` 执行

**Do NOT touch（显式越界保护）:**

- `.trash/steal-digestion/governance/safety/loop_detection.py`、`.trash/steal-digestion/governance/orchestration/*`、`.trash/steal-digestion/governance/terminal/*`、`.trash/steal-digestion/governance/memory/transcript_cursor.py` — 已确认废弃，留在 .trash
- Wave 2b 候选模块（operation_validator / idle_scheduler / temporal_recall）— 留作后续

---

--- PHASE GATE: Plan → Implement ---
- [x] Goal 一句话可证伪（pytest 4 个测试文件全绿 + 4 次 commit）
- [x] File Map 完整（9 个 Create + 4 个 Modify，已列全）
- [x] 无歧义（owner 已在 brief 中锁定 4 个模块、集成点、分支名）
- [x] 简化预检：最小实现 = "mv 4 文件 + 写 4 个测试 + 改 4 个集成点"；本计划步数 27，无冗余抽象
- [x] 每步有动词 + 具体目标 + 可复制 verify 命令
- [x] 无 banned placeholder
- [x] 依赖显式（步骤内用 `depends on: step N` 标注跨 Task 依赖）
- [x] Owner review: not required（plan IS the approval，符合 plan_template.md 默认 Gate 配置）

---

## Steps

### Task 0: 分支准备

- [ ] **Step 1: 创建并切换到 feat/digest-wave2 分支**

```bash
git checkout main && git pull --ff-only
git checkout -b feat/digest-wave2
```

→ verify: `git branch --show-current` 输出 `feat/digest-wave2`

---

### Task 1: `idle_timeout` → `src/governance/safety/` + 集成到 `executor_stream.py`

**Files:**
- Create: `src/governance/safety/idle_timeout.py`（来源：`.trash/steal-digestion/governance/safety/idle_timeout.py`）
- Create: `tests/governance/test_idle_timeout.py`
- Modify: `src/governance/executor_stream.py`（在 `ExecutionStream` 类上新增 `execute_guarded` 方法）

- [ ] **Step 2: 写失败测试 `tests/governance/test_idle_timeout.py`**

```python
"""Tests for R63 idle timeout deadlock detection."""
import asyncio
import pytest
from src.governance.safety.idle_timeout import with_idle_timeout, IdleTimeoutGuard


async def _producing_gen():
    for i in range(3):
        await asyncio.sleep(0.01)
        yield i


async def _hanging_gen():
    yield 0
    await asyncio.sleep(10)  # 模拟死锁


@pytest.mark.asyncio
async def test_with_idle_timeout_passes_through_values():
    results = []
    async for v in with_idle_timeout(_producing_gen(), timeout_s=1.0, label="ok"):
        results.append(v)
    assert results == [0, 1, 2]


@pytest.mark.asyncio
async def test_with_idle_timeout_exits_cleanly_on_deadlock():
    fired = []
    async for v in with_idle_timeout(
        _hanging_gen(),
        timeout_s=0.1,
        on_timeout=lambda: fired.append(True),
        label="deadlock",
    ):
        pass
    assert fired == [True]


@pytest.mark.asyncio
async def test_idle_timeout_guard_heartbeat_prevents_timeout():
    async with IdleTimeoutGuard(timeout_s=0.2, label="hb") as g:
        for _ in range(3):
            await asyncio.sleep(0.1)
            g.heartbeat()
    assert g.timed_out is False
```

→ verify: `git status tests/governance/test_idle_timeout.py` 显示 `??`（未追踪）

- [ ] **Step 3: 跑测试确认 FAIL (ImportError)**

Run: `pytest tests/governance/test_idle_timeout.py -v`
Expected: FAIL，错误消息包含 `ModuleNotFoundError: No module named 'src.governance.safety.idle_timeout'`

- [ ] **Step 4: `mv` 文件从 .trash 到 src 正式路径**

```bash
mv .trash/steal-digestion/governance/safety/idle_timeout.py src/governance/safety/idle_timeout.py
```

→ verify: `ls src/governance/safety/idle_timeout.py && ! ls .trash/steal-digestion/governance/safety/idle_timeout.py 2>/dev/null`（源文件存在、.trash 中已移除）
- depends on: step 3

- [ ] **Step 5: 跑测试确认 PASS**

Run: `pytest tests/governance/test_idle_timeout.py -v`
Expected: PASS，3 passed
- depends on: step 4

- [ ] **Step 6: 集成到 `src/governance/executor_stream.py` — 新增 `execute_guarded` 方法**

在 `src/governance/executor_stream.py` 第 12-16 行 import 区追加：

```python
from src.governance.safety.idle_timeout import with_idle_timeout, DEFAULT_TIMEOUT_S
```

在 `ExecutionStream` 类内、`execute` 方法（当前 112-161 行）之后，`_run_sync` 之前（即当前文件第 163 行前），插入新方法：

```python
    async def execute_guarded(
        self,
        task_id: int,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ):
        """Streaming variant with idle-timeout deadlock protection (R63 Archon).

        Wraps ``execute()`` with ``with_idle_timeout`` so a hung subprocess or
        MCP stream does not silently deadlock the consumer.
        """
        async for event in with_idle_timeout(
            self.execute(task_id),
            timeout_s=timeout_s,
            label=f"stream#{task_id}",
        ):
            yield event
```

→ verify: `python -c "from src.governance.executor_stream import ExecutionStream; import inspect; assert 'execute_guarded' in dir(ExecutionStream); assert inspect.isasyncgenfunction(ExecutionStream.execute_guarded)"` 无报错
- depends on: step 5

- [ ] **Step 7: 提交 Task 1**

```bash
git add src/governance/safety/idle_timeout.py tests/governance/test_idle_timeout.py src/governance/executor_stream.py
git commit -m "$(cat <<'EOF'
feat(safety): reinstate idle_timeout deadlock detector (Wave 2)

Restore R63 Archon's async-generator idle timeout from .trash/ and wire
it into ExecutionStream.execute_guarded() so MCP/subprocess hangs surface
cleanly instead of deadlocking consumers.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

→ verify: `git log -1 --stat` 包含 3 个改动文件
- depends on: step 6

---

### Task 2: `query_writeback` → `src/governance/learning/` + 集成到 `executor_session.py`

**Files:**
- Create: `src/governance/learning/query_writeback.py`（来源：`.trash/steal-digestion/governance/learning/query_writeback.py`）
- Create: `tests/governance/test_query_writeback.py`
- Modify: `src/governance/executor_session.py:249-254`（`prefill` 的返回字典）+ `src/governance/executor_session.py:321`（`finalize` 的 return 前）

- [ ] **Step 8: 写失败测试 `tests/governance/test_query_writeback.py`**

```python
"""Tests for R75 Graphify query result writeback."""
import pytest
from pathlib import Path
from src.governance.learning.query_writeback import (
    save_query_result,
    list_query_results,
    prune_old_results,
)


def test_save_query_result_writes_markdown(tmp_path):
    out = save_query_result(
        question="How does X work?",
        answer="X works by Y.",
        source_refs=["src/x.py"],
        memory_dir=tmp_path,
        tags=["diagnostic"],
        department="engineering",
    )
    assert out is not None
    assert out.parent == tmp_path
    body = out.read_text(encoding="utf-8")
    assert "How does X work?" in body
    assert "X works by Y." in body
    assert 'department: "engineering"' in body
    assert "src/x.py" in body


def test_save_query_result_returns_none_on_empty_input(tmp_path):
    assert save_query_result("", "answer", memory_dir=tmp_path) is None
    assert save_query_result("q", "", memory_dir=tmp_path) is None


def test_prune_old_results_keeps_newest(tmp_path):
    for i in range(5):
        save_query_result(f"q{i}", f"a{i}", memory_dir=tmp_path)
    removed = prune_old_results(max_files=2, memory_dir=tmp_path)
    assert removed == 3
    assert len(list_query_results(memory_dir=tmp_path)) == 2
```

→ verify: `git status tests/governance/test_query_writeback.py` 显示 `??`

- [ ] **Step 9: 跑测试确认 FAIL (ImportError)**

Run: `pytest tests/governance/test_query_writeback.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.governance.learning.query_writeback'`

- [ ] **Step 10: `mv` 文件 + 跑测试确认 PASS**

```bash
mv .trash/steal-digestion/governance/learning/query_writeback.py src/governance/learning/query_writeback.py
pytest tests/governance/test_query_writeback.py -v
```

→ verify: pytest 输出 `3 passed`
- depends on: step 9

- [ ] **Step 11: 修改 `executor_session.py:249-254`（`prefill` 的返回字典）**

把 `prefill` 方法末尾（当前 249-254 行）的返回字典：

```python
        return {
            "agent_env": agent_env,
            "session": session,
            "wal_signals": wal_signals,
            "_saved_claudecode": saved_claudecode,
        }
```

改为追加 `"prompt": prompt`：

```python
        return {
            "agent_env": agent_env,
            "session": session,
            "wal_signals": wal_signals,
            "_saved_claudecode": saved_claudecode,
            "prompt": prompt,
        }
```

→ verify: `grep -n '"prompt": prompt' src/governance/executor_session.py` 返回 1 行命中
- depends on: step 10

- [ ] **Step 12: 修改 `executor_session.py:321`（`finalize` return 前插入 writeback 调用）**

在 `finalize` 方法的 `return ExecutionResponse(...)` 语句之前（当前第 321 行），插入：

```python
        # ── Query Writeback (R75): feed successful answers back to memory ──
        if final_status == "done" and result_text:
            try:
                from src.governance.learning.query_writeback import save_query_result
                q = prefill_ctx.get("prompt", "")
                if q:
                    save_query_result(
                        question=q[:500],
                        answer=result_text,
                        department=f"task#{task_id}",
                    )
            except Exception as e:
                log.debug(f"query_writeback: skipped ({e})")
```

→ verify: `grep -n "save_query_result" src/governance/executor_session.py` 返回 ≥ 2 行（import + 调用）
- depends on: step 11

- [ ] **Step 13: 冒烟验证 prefill→finalize 串联不报错**

```bash
python -c "from src.governance.executor_session import AgentSessionRunner; import inspect; sig = inspect.signature(AgentSessionRunner.finalize); assert 'prefill_ctx' in sig.parameters; from src.governance.learning.query_writeback import save_query_result; print('ok')"
```

→ verify: 输出 `ok`，无 ImportError 或 AttributeError
- depends on: step 12

- [ ] **Step 14: 提交 Task 2**

```bash
git add src/governance/learning/query_writeback.py tests/governance/test_query_writeback.py src/governance/executor_session.py
git commit -m "$(cat <<'EOF'
feat(learning): reinstate query_writeback memory feedback loop (Wave 2)

Restore R75 Graphify's Q&A writeback from .trash/ and hook it into
executor_session.finalize() so successful task results feed .remember/
query_results/ for the next memory synthesis cycle.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

→ verify: `git log -1 --stat` 包含 3 个改动文件
- depends on: step 13

---

### Task 3: `blackboard` → `src/governance/context/` + 集成到 `council.py`

**Files:**
- Create: `src/governance/context/blackboard.py`（来源：`.trash/steal-digestion/governance/context/blackboard.py`）
- Create: `tests/governance/test_blackboard.py`
- Modify: `src/governance/council.py:499-502`（`deliberate` 中 Stage 3 调用前）

- [ ] **Step 15: 写失败测试 `tests/governance/test_blackboard.py`**

```python
"""Tests for R74 ChatDev BlackboardMemory."""
from src.governance.context.blackboard import (
    BlackboardMemory,
    create_reflexion_blackboard,
)


def test_write_denied_without_permission():
    bb = BlackboardMemory("test")
    bb.grant("reader", read=True, write=False)
    assert bb.write("reader", "hello") is False


def test_write_and_read_respects_permissions():
    bb = BlackboardMemory("test")
    bb.grant("writer", read=False, write=True)
    bb.grant("reader", read=True, write=False)
    assert bb.write("writer", "lesson one") is True
    entries = bb.read("reader", top_k=5)
    assert len(entries) == 1
    assert entries[0].content == "lesson one"
    assert bb.read("writer", top_k=5) == []  # writer lacks read


def test_dedup_suppresses_duplicate_content():
    bb = BlackboardMemory("test", dedup=True)
    bb.grant("w", read=True, write=True)
    assert bb.write("w", "same") is True
    assert bb.write("w", "same") is False
    assert len(bb.read("w")) == 1


def test_reflexion_factory_sets_expected_roles():
    bb = create_reflexion_blackboard()
    stats = bb.get_stats()
    assert set(stats["roles"].keys()) == {
        "actor", "evaluator", "reflection_writer", "synthesizer",
    }
    assert stats["roles"]["reflection_writer"] == {"read": False, "write": True}
```

→ verify: `git status tests/governance/test_blackboard.py` 显示 `??`

- [ ] **Step 16: 跑测试确认 FAIL (ImportError)**

Run: `pytest tests/governance/test_blackboard.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.governance.context.blackboard'`

- [ ] **Step 17: `mv` 文件 + 跑测试确认 PASS**

```bash
mv .trash/steal-digestion/governance/context/blackboard.py src/governance/context/blackboard.py
pytest tests/governance/test_blackboard.py -v
```

→ verify: pytest 输出 `4 passed`
- depends on: step 16

- [ ] **Step 18: 集成到 `src/governance/council.py:499` — Stage 2 完成后构造 blackboard，喂给 Stage 3**

在 `deliberate` 方法中，定位当前第 499-502 行：

```python
        # ── Stage 3: Chairman synthesis ──
        synthesis, decision, confidence, action_items = self._stage3_synthesize(
            question, context, opinions, rankings, label_to_elder, timeout,
        )
```

替换为：

```python
        # ── Shared Board (R74 ChatDev): opinions as blackboard for chairman ──
        from src.governance.context.blackboard import create_reflexion_blackboard
        bb = create_reflexion_blackboard()
        for op in opinions:
            bb.write(
                "reflection_writer",
                f"[{op.stance} conf={op.confidence:.2f}] {op.text[:300]}",
                metadata={"elder": op.elder_key, "label": op.label},
            )
        board_text = bb.format_for_prompt("synthesizer", top_k=len(opinions))
        synth_context = context + ("\n\n" + board_text if board_text else "")

        # ── Stage 3: Chairman synthesis ──
        synthesis, decision, confidence, action_items = self._stage3_synthesize(
            question, synth_context, opinions, rankings, label_to_elder, timeout,
        )
```

→ verify: `grep -n "create_reflexion_blackboard\|synth_context" src/governance/council.py` 至少返回 3 行命中
- depends on: step 17

- [ ] **Step 19: 冒烟导入 + council 模块加载无 SyntaxError**

```bash
python -c "from src.governance.council import ElderCouncil; from src.governance.context.blackboard import create_reflexion_blackboard; bb = create_reflexion_blackboard(); assert bb.name == 'reflexion'; print('ok')"
```

→ verify: 输出 `ok`
- depends on: step 18

- [ ] **Step 20: 提交 Task 3**

```bash
git add src/governance/context/blackboard.py tests/governance/test_blackboard.py src/governance/council.py
git commit -m "$(cat <<'EOF'
feat(context): reinstate blackboard shared-state memory (Wave 2)

Restore R74 ChatDev's BlackboardMemory from .trash/ with role-based
append-log. Wire into ElderCouncil.deliberate so Stage-1 opinions are
handed to Stage-3 chairman synthesis via a formatted shared board.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

→ verify: `git log -1 --stat` 包含 3 个改动文件
- depends on: step 19

---

### Task 4: `three_phase` → `src/governance/transaction/` + 集成到 `memory_server.py`

**Files:**
- Create: `src/governance/transaction/__init__.py`（新建空文件）
- Create: `src/governance/transaction/three_phase.py`（来源：`.trash/steal-digestion/governance/transaction/three_phase.py`）
- Create: `tests/governance/test_three_phase.py`
- Modify: `src/mcp/memory_server.py:251-402`（`memory_save` 改 async，拆三阶段）

- [ ] **Step 21: 写失败测试 `tests/governance/test_three_phase.py`**

```python
"""Tests for R64 Hindsight three-phase transaction executor."""
import pytest
from src.governance.transaction.three_phase import (
    Phase,
    PhaseSpec,
    TransactionPlan,
    ThreePhaseExecutor,
    three_phase_write,
)


@pytest.mark.asyncio
async def test_three_phases_run_in_order():
    order = []

    async def prep(ctx, acc): order.append("p"); return {"pv": 1}
    async def commit(ctx, acc): order.append("c"); return {"cv": acc["pv"] + 1}
    async def supp(ctx, acc): order.append("s"); return {"sv": acc["cv"] + 1}

    results = await three_phase_write(prep, commit, supp, context={})
    assert order == ["p", "c", "s"]
    assert [r.phase for r in results] == [Phase.PREPARE, Phase.COMMIT, Phase.SUPPLEMENT]
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_prepare_failure_aborts_plan():
    calls = []

    async def prep(ctx, acc): calls.append("p"); raise RuntimeError("boom")
    async def commit(ctx, acc): calls.append("c"); return {}

    results = await three_phase_write(prep, commit, context={})
    assert calls == ["p"]
    assert len(results) == 1
    assert results[0].success is False
    assert "boom" in (results[0].error or "")


@pytest.mark.asyncio
async def test_supplement_failure_is_best_effort():
    async def prep(ctx, acc): return {}
    async def commit(ctx, acc): return {"ok": True}
    async def supp(ctx, acc): raise RuntimeError("supp fail")

    results = await three_phase_write(prep, commit, supp, context={})
    assert results[1].success is True  # commit still ok
    assert results[2].success is False
    assert "supp fail" in (results[2].error or "")
```

→ verify: `git status tests/governance/test_three_phase.py` 显示 `??`

- [ ] **Step 22: 跑测试确认 FAIL (ImportError)**

Run: `pytest tests/governance/test_three_phase.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'src.governance.transaction'`

- [ ] **Step 23: 创建 transaction 包 + `mv` 源文件 + 跑测试确认 PASS**

```bash
mkdir -p src/governance/transaction
touch src/governance/transaction/__init__.py
mv .trash/steal-digestion/governance/transaction/three_phase.py src/governance/transaction/three_phase.py
pytest tests/governance/test_three_phase.py -v
```

→ verify: pytest 输出 `3 passed` 且 `ls src/governance/transaction/` 列出 `__init__.py` + `three_phase.py`
- depends on: step 22

- [ ] **Step 24: 重构 `src/mcp/memory_server.py:251-402`（`memory_save`）为 async + 三阶段**

在文件顶部 import 区（查找 `import asyncio`，若无则在现有 import 末尾追加）：

```python
import asyncio
from src.governance.transaction.three_phase import three_phase_write
```

把当前 `def memory_save(facts, source="mcp-client", importance=0.5) -> str:` 函数签名改为 `async def memory_save(...)`。

将函数体（当前 270-402 行的 `_ensure_shared_dir()` → `return ...`）重构为三个内部 async 闭包（保持逻辑等价，只把原函数体按"读→写→审计"拆成三段）：

```python
async def memory_save(
    facts: list[str],
    source: str = "mcp-client",
    importance: float = 0.5,
) -> str:
    """Save atomic facts via three-phase transaction (R64 Hindsight)."""
    _ensure_shared_dir()
    if not facts:
        return "Error: facts list must not be empty"
    valid_facts = [f.strip() for f in facts if f and f.strip()]
    if not valid_facts:
        return "Error: all facts were empty strings"

    # 原第 279-298 行的 atomic_fact_splitter + validate_fact 逻辑照搬
    if split_into_atomic_facts:
        atomized: list[str] = []
        for fact in valid_facts:
            atoms = split_into_atomic_facts(fact)
            atomized.extend(atoms if atoms else [fact])
        valid_facts = atomized
    if validate_fact:
        validated: list[str] = []
        for fact in valid_facts:
            ok, _reason = validate_fact(fact)
            if ok:
                validated.append(fact)
            else:
                log.debug("memory_save: rejected fact (%s): %s", _reason, fact[:80])
        if validated:
            valid_facts = validated

    async def _prepare(ctx, acc):
        # Phase 1: lock-free read — 扫描现有 shared/*.md，计算 supersede 候选
        existing_files = sorted(_SHARED_DIR.glob("*.md"))
        existing_data: list[tuple[Path, str, dict]] = []
        for ef in existing_files:
            try:
                raw = ef.read_text(encoding="utf-8")
            except OSError:
                continue
            fm = _parse_shared_fm(raw)
            if fm.get("superseded_by"):
                continue
            body = raw
            if raw.startswith("---"):
                end = raw.find("\n---", 3)
                if end != -1:
                    body = raw[end + 4:].strip()
            existing_data.append((ef, body, fm))
        return {"existing_data": existing_data}

    async def _commit(ctx, acc):
        # Phase 2: atomic writes — 标记 superseded + 写新 fact
        existing_data = list(acc["existing_data"])
        now_ts = time.time()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        saved = 0
        superseded_total = 0
        for fact_text in valid_facts:
            superseded_paths: list[str] = []
            for ef_path, ef_body, ef_fm in existing_data:
                sim = _jaccard_similarity(fact_text, ef_body)
                if sim >= _SUPERSEDE_SIMILARITY:
                    superseded_paths.append(ef_path.name)
                    try:
                        updated = ef_path.read_text(encoding="utf-8")
                        new_fm_line = f"superseded_by: {now_iso}\n"
                        if "superseded_by:" in updated:
                            updated = re.sub(r'superseded_by:.*\n', new_fm_line, updated)
                        else:
                            close = updated.find("\n---", 3)
                            if close != -1:
                                updated = updated[:close] + f"\n{new_fm_line.rstrip()}" + updated[close:]
                        atomic_write(ef_path, updated)
                        superseded_total += 1
                    except OSError as exc:
                        log.warning("memory_save: could not update superseded entry %s: %s", ef_path, exc)
            fact_hash = hashlib.sha1(fact_text.encode()).hexdigest()[:8]
            headroom_id = f"shm-{int(now_ts)}-{fact_hash}"
            filename = f"{int(now_ts)}-{fact_hash}.md"
            target = _SHARED_DIR / filename
            frontmatter_lines = [
                "---",
                f"headroom_id: {headroom_id}",
                f"source: {source}",
                f"importance: {importance}",
                f"created_at: {now_iso}",
                f"access_count: 0",
            ]
            if superseded_paths:
                frontmatter_lines.append(f"supersedes: {', '.join(superseded_paths)}")
            frontmatter_lines.append("---")
            frontmatter_lines.append("")
            frontmatter_lines.append(fact_text)
            entry_text = "\n".join(frontmatter_lines)
            try:
                atomic_write(target, entry_text)
                saved += 1
                existing_data.append((target, fact_text, {
                    "headroom_id": headroom_id, "source": source,
                    "importance": str(importance), "created_at": now_iso,
                }))
            except OSError as exc:
                log.error("memory_save: failed to write %s: %s", target, exc)
        return {"saved": saved, "superseded_total": superseded_total}

    async def _supplement(ctx, acc):
        # Phase 3: best-effort audit
        _audit("SAVE", f"shared facts={acc.get('saved', 0)} superseded={acc.get('superseded_total', 0)} source={source}")
        return {}

    results = await three_phase_write(_prepare, _commit, _supplement, context={})
    commit_data = next((r.data for r in results if r.phase.value == "commit"), {})
    saved = commit_data.get("saved", 0)
    superseded_total = commit_data.get("superseded_total", 0)
    return f"Saved {saved} fact(s), superseded {superseded_total} existing entries."
```

备注：`_parse_shared_fm` 原为 `memory_save` 内部闭包（304-316 行），重构时把它提到模块级（和 `_jaccard_similarity` 同一层级）。

→ verify: `python -c "import asyncio; from src.mcp.memory_server import memory_save; assert asyncio.iscoroutinefunction(memory_save); print('async ok')"` 输出 `async ok`
- depends on: step 23

- [ ] **Step 25: 冒烟 memory_save end-to-end（使用 tmp shared dir）**

```bash
python -c "
import asyncio, tempfile, pathlib
from src.mcp import memory_server as ms

with tempfile.TemporaryDirectory() as td:
    ms._SHARED_DIR = pathlib.Path(td)
    out = asyncio.run(ms.memory_save(['test fact for wave2 three-phase'], source='plan-verify', importance=0.5))
    assert 'Saved 1 fact' in out, out
    files = list(pathlib.Path(td).glob('*.md'))
    assert len(files) == 1, files
    print('smoke ok:', out)
"
```

→ verify: 输出 `smoke ok: Saved 1 fact(s), superseded 0 existing entries.`
- depends on: step 24

- [ ] **Step 26: 跑完整 4-module 测试集，确认无回归**

```bash
pytest tests/governance/test_idle_timeout.py tests/governance/test_query_writeback.py tests/governance/test_blackboard.py tests/governance/test_three_phase.py -v
```

→ verify: 全部 PASS（13 个测试用例 = 3 + 3 + 4 + 3）
- depends on: step 25

- [ ] **Step 27: 提交 Task 4**

```bash
git add src/governance/transaction/__init__.py src/governance/transaction/three_phase.py tests/governance/test_three_phase.py src/mcp/memory_server.py
git commit -m "$(cat <<'EOF'
feat(transaction): reinstate three-phase executor for memory_save (Wave 2)

Restore R64 Hindsight's three-phase pattern (prepare/commit/supplement)
from .trash/ and refactor memory_server.memory_save to run its read,
write, and audit legs through three_phase_write. Reduces atomic-write
contention under concurrent MCP clients.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

→ verify: `git log --oneline main..HEAD` 显示 4 个本 Wave 的 commit
- depends on: step 26

---

--- PHASE GATE: Implement → Done ---
- [ ] 每个 Task 的 verify 命令全部通过
- [ ] `git diff main..HEAD --stat` 仅涉及本 File Map 列出的 13 个文件（9 Create + 4 Modify）
- [ ] `pytest tests/governance/test_idle_timeout.py tests/governance/test_query_writeback.py tests/governance/test_blackboard.py tests/governance/test_three_phase.py` 全绿
- [ ] `.trash/steal-digestion/governance/{safety,learning,context,transaction}/` 下被 mv 的 4 个文件已不存在（`find .trash/steal-digestion -name idle_timeout.py -o -name query_writeback.py -o -name blackboard.py -o -name three_phase.py` 无输出）
- [ ] 4 次 commit（每 Task 一次），分支为 `feat/digest-wave2`
- [ ] 未修改本 File Map 外的任何文件（特别是 Wave 3 可能触及的其他部分）
- [ ] 未改动 `.trash/` 下其余被判定废弃的模块

## Notes

- **如执行中发现 `memory_server.py:304-316` 的 `_parse_shared_fm` 被其他函数引用**，Step 24 提升到模块级是安全的；若仅在 `memory_save` 内部使用，直接提升不会有副作用。执行前先 `grep -n "_parse_shared_fm" src/mcp/memory_server.py` 确认。
- **若 MCP FastMCP 装饰器不支持 async tool**（可能性极低，FastMCP 从 0.x 起即支持），在 Step 24 fallback 为 `asyncio.run(three_phase_write(...))` 包在同步函数内。
- **`.trash/steal-digestion/governance/transaction/__init__.py`** 是空文件（0 字节），Step 23 通过 `touch` 新建等价文件，不用 mv（源文件无内容价值）。
