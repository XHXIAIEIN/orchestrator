# Runtime Supervisor — OpenAkita P0 偷师实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 OpenAkita 偷师 4 个 P0 模式，为 Agent 运行时增加签名重复检测、进度感知超时、编辑抖动检测和空转检测，将二元审批升级为多级干预。

**Architecture:** 新建 `src/governance/supervisor.py` 作为运行时监督器（观察者模式），嵌入 `executor_session.py` 的 ReAct 循环。不修改 Agent SDK 内部，在外层包装检测逻辑。升级 `StuckDetector` 增加签名重复检测。在 `executor.py` 增加进度感知超时。

**Tech Stack:** Python 3.11+, dataclass, hashlib (md5 签名), threading (线程安全)

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/governance/supervisor.py` | 运行时监督器：5 级干预 + 4 种检测模式 |
| Modify | `src/governance/executor_session.py` | 集成 Supervisor，每轮调用 evaluate() |
| Modify | `src/governance/stuck_detector.py` | 增加签名重复检测 (Pattern 6) |
| Create | `tests/governance/test_supervisor.py` | Supervisor 单元测试 |
| Modify | `tests/governance/test_doom_loop.py` | 补签名重复检测测试 |

---

### Task 1: RuntimeSupervisor 核心 — 干预分级 + 签名重复检测

**Files:**
- Create: `src/governance/supervisor.py`
- Test: `tests/governance/test_supervisor.py`

- [ ] **Step 1: 写失败测试 — 签名重复检测**

```python
# tests/governance/test_supervisor.py
"""RuntimeSupervisor — 运行时监督器测试。"""
import pytest
from src.governance.supervisor import RuntimeSupervisor, InterventionLevel


class TestSignatureRepeat:
    """签名重复检测：相同 tool+params 调用多次 → 升级干预。"""

    def test_no_repeat_no_intervention(self):
        sv = RuntimeSupervisor()
        sv.record_tool_call("Read", {"file_path": "/a.py"})
        sv.record_tool_call("Edit", {"file_path": "/b.py"})
        sv.record_tool_call("Bash", {"command": "ls"})
        result = sv.evaluate(iteration=3)
        assert result is None

    def test_3_repeats_nudge(self):
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.record_tool_call("Read", {"file_path": "/a.py"})
        result = sv.evaluate(iteration=3)
        assert result is not None
        assert result.level == InterventionLevel.NUDGE
        assert "signature_repeat" in result.pattern

    def test_5_repeats_terminate(self):
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_tool_call("Read", {"file_path": "/a.py"})
        result = sv.evaluate(iteration=5)
        assert result is not None
        assert result.level == InterventionLevel.TERMINATE

    def test_different_params_no_repeat(self):
        sv = RuntimeSupervisor()
        for i in range(5):
            sv.record_tool_call("Read", {"file_path": f"/file_{i}.py"})
        result = sv.evaluate(iteration=5)
        assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/test_supervisor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.governance.supervisor'`

- [ ] **Step 3: 实现 RuntimeSupervisor**

```python
# src/governance/supervisor.py
"""
RuntimeSupervisor — 运行时监督器。

偷自 OpenAkita 的 supervisor.py，观察者模式：
  - 不直接修改 Agent 状态
  - 只返回 Intervention 指令让调用方执行
  - 职责分离，测试友好

检测模式:
  1. SIGNATURE_REPEAT — 完全相同的 tool+params 重复调用
  2. EDIT_THRASHING  — 同一文件反复读写交替
  3. UNPRODUCTIVE    — 连续 N 轮只调用管理类工具，无实际产出
  4. TOKEN_ANOMALY   — 单轮 token 消耗异常（预留）

干预等级:
  NONE → NUDGE → STRATEGY_SWITCH → ESCALATE → TERMINATE
"""
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import IntEnum

log = logging.getLogger(__name__)


class InterventionLevel(IntEnum):
    NONE = 0
    NUDGE = 1            # 注入提示消息
    STRATEGY_SWITCH = 2  # 回滚 + 换策略
    ESCALATE = 3         # 请求人工介入
    TERMINATE = 4        # 安全终止


@dataclass
class Intervention:
    """Supervisor 返回的干预指令。"""
    level: InterventionLevel
    pattern: str          # 检测模式名称
    message: str          # 注入给 agent 的提示（NUDGE 时使用）
    details: dict = field(default_factory=dict)


# ── 检测阈值 ──
SIG_REPEAT_NUDGE = 3       # 签名重复 3 次 → NUDGE
SIG_REPEAT_TERMINATE = 5   # 签名重复 5 次 → TERMINATE
EDIT_THRASH_THRESHOLD = 3  # 读写交替 3 次 → NUDGE
UNPRODUCTIVE_THRESHOLD = 5 # 连续 5 轮空转 → NUDGE
SIG_WINDOW = 20            # 签名检测滑动窗口

# 管理类工具：调用这些不算"有产出"
MANAGEMENT_TOOLS = frozenset({
    "TodoRead", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
})


def _tool_signature(tool_name: str, params: dict) -> str:
    """生成工具调用签名：tool_name(md5(params)[:8])"""
    params_str = str(sorted(params.items())) if params else ""
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    return f"{tool_name}({params_hash})"


class RuntimeSupervisor:
    """观察者模式运行时监督器。记录每轮数据，evaluate() 返回最严重的干预。"""

    def __init__(self):
        self._signatures: list[str] = []
        self._file_ops: list[dict] = []       # {"path": str, "op": "read"|"write"}
        self._productive_streak: int = 0      # 连续无产出轮数
        self._tool_calls_this_turn: list[str] = []

    def record_tool_call(self, tool_name: str, params: dict) -> None:
        """记录一次工具调用。每轮可能调用多个工具。"""
        sig = _tool_signature(tool_name, params)
        self._signatures.append(sig)
        # 只保留窗口内的签名
        if len(self._signatures) > SIG_WINDOW * 2:
            self._signatures = self._signatures[-SIG_WINDOW:]

        self._tool_calls_this_turn.append(tool_name)

        # 记录文件操作
        path = params.get("file_path", "") or params.get("path", "")
        if path:
            if tool_name in ("Edit", "Write", "NotebookEdit"):
                self._file_ops.append({"path": path, "op": "write"})
            elif tool_name in ("Read", "Glob"):
                self._file_ops.append({"path": path, "op": "read"})
        if len(self._file_ops) > SIG_WINDOW * 2:
            self._file_ops = self._file_ops[-SIG_WINDOW:]

    def end_turn(self) -> None:
        """标记一轮结束。更新空转计数。"""
        tools = self._tool_calls_this_turn
        if not tools or all(t in MANAGEMENT_TOOLS for t in tools):
            self._productive_streak += 1
        else:
            self._productive_streak = 0
        self._tool_calls_this_turn = []

    def evaluate(self, iteration: int) -> Intervention | None:
        """评估当前状态，返回最严重的干预（如有）。"""
        interventions = []

        # ── Check 1: 签名重复 ──
        sig_result = self._check_signature_repeat()
        if sig_result:
            interventions.append(sig_result)

        # ── Check 2: 编辑抖动 ──
        edit_result = self._check_edit_thrashing()
        if edit_result:
            interventions.append(edit_result)

        # ── Check 3: 空转检测 ──
        idle_result = self._check_unproductive()
        if idle_result:
            interventions.append(idle_result)

        if not interventions:
            return None

        # 返回最严重的干预
        return max(interventions, key=lambda i: i.level)

    def _check_signature_repeat(self) -> Intervention | None:
        """签名重复检测。"""
        if len(self._signatures) < SIG_REPEAT_NUDGE:
            return None

        window = self._signatures[-SIG_WINDOW:]
        counts = Counter(window)
        if not counts:
            return None

        most_common_sig, count = counts.most_common(1)[0]

        if count >= SIG_REPEAT_TERMINATE:
            return Intervention(
                level=InterventionLevel.TERMINATE,
                pattern="signature_repeat",
                message=f"相同操作 {most_common_sig} 已重复 {count} 次，强制终止",
                details={"signature": most_common_sig, "count": count},
            )
        elif count >= SIG_REPEAT_NUDGE:
            return Intervention(
                level=InterventionLevel.NUDGE,
                pattern="signature_repeat",
                message=f"[Supervisor] 检测到相同操作重复 {count} 次（{most_common_sig}）。请换一种方法。",
                details={"signature": most_common_sig, "count": count},
            )
        return None

    def _check_edit_thrashing(self) -> Intervention | None:
        """编辑抖动检测：同一文件反复读写交替。"""
        if len(self._file_ops) < 4:
            return None

        recent = self._file_ops[-SIG_WINDOW:]
        file_cycles: Counter = Counter()

        for i in range(1, len(recent)):
            prev, curr = recent[i - 1], recent[i]
            if prev["path"] == curr["path"] and prev["op"] != curr["op"]:
                file_cycles[prev["path"]] += 1

        if not file_cycles:
            return None

        worst_file, cycles = file_cycles.most_common(1)[0]
        if cycles >= EDIT_THRASH_THRESHOLD:
            return Intervention(
                level=InterventionLevel.NUDGE,
                pattern="edit_thrashing",
                message=f"[Supervisor] 文件 {worst_file} 被反复读写 {cycles} 次。先想清楚再改。",
                details={"file": worst_file, "cycles": cycles},
            )
        return None

    def _check_unproductive(self) -> Intervention | None:
        """空转检测：连续 N 轮只调管理类工具。"""
        if self._productive_streak >= UNPRODUCTIVE_THRESHOLD:
            return Intervention(
                level=InterventionLevel.NUDGE,
                pattern="unproductive_loop",
                message=f"[Supervisor] 连续 {self._productive_streak} 轮没有实际操作（只有管理类工具调用）。开始干活。",
                details={"idle_turns": self._productive_streak},
            )
        return None

    def reset(self) -> None:
        """重置所有状态。"""
        self._signatures.clear()
        self._file_ops.clear()
        self._productive_streak = 0
        self._tool_calls_this_turn.clear()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/test_supervisor.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/supervisor.py tests/governance/test_supervisor.py
git commit -m "feat(governance): RuntimeSupervisor — 签名重复/编辑抖动/空转检测 + 5级干预"
```

---

### Task 2: 编辑抖动 + 空转检测测试

**Files:**
- Modify: `tests/governance/test_supervisor.py`

- [ ] **Step 1: 写编辑抖动测试**

```python
# 追加到 tests/governance/test_supervisor.py

class TestEditThrashing:
    """编辑抖动检测：同一文件反复读写交替 → NUDGE。"""

    def test_no_thrash_different_files(self):
        sv = RuntimeSupervisor()
        sv.record_tool_call("Read", {"file_path": "/a.py"})
        sv.record_tool_call("Edit", {"file_path": "/b.py"})
        sv.record_tool_call("Read", {"file_path": "/c.py"})
        result = sv.evaluate(iteration=3)
        assert result is None

    def test_thrash_same_file(self):
        sv = RuntimeSupervisor()
        for _ in range(3):
            sv.record_tool_call("Read", {"file_path": "/a.py"})
            sv.record_tool_call("Edit", {"file_path": "/a.py"})
        result = sv.evaluate(iteration=6)
        assert result is not None
        assert result.level == InterventionLevel.NUDGE
        assert result.pattern == "edit_thrashing"


class TestUnproductive:
    """空转检测：连续 N 轮只有管理工具 → NUDGE。"""

    def test_productive_no_alert(self):
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_tool_call("Edit", {"file_path": "/a.py"})
            sv.end_turn()
        result = sv.evaluate(iteration=5)
        # Edit 是生产性工具，不应触发
        assert result is None

    def test_idle_triggers_nudge(self):
        sv = RuntimeSupervisor()
        for _ in range(5):
            sv.record_tool_call("TodoWrite", {})
            sv.end_turn()
        result = sv.evaluate(iteration=5)
        assert result is not None
        assert result.pattern == "unproductive_loop"

    def test_productive_resets_counter(self):
        sv = RuntimeSupervisor()
        for _ in range(4):
            sv.record_tool_call("TodoWrite", {})
            sv.end_turn()
        # 第 5 轮做了正事
        sv.record_tool_call("Edit", {"file_path": "/a.py"})
        sv.end_turn()
        result = sv.evaluate(iteration=5)
        assert result is None
```

- [ ] **Step 2: 运行测试确认通过**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/test_supervisor.py -v`
Expected: 8 passed

- [ ] **Step 3: Commit**

```bash
git add tests/governance/test_supervisor.py
git commit -m "test(supervisor): 编辑抖动 + 空转检测覆盖"
```

---

### Task 3: 集成 Supervisor 到 AgentSessionRunner

**Files:**
- Modify: `src/governance/executor_session.py`

- [ ] **Step 1: 在 executor_session.py 顶部添加 import**

在现有的 optional imports 区域（line 22-35 附近）添加：

```python
try:
    from src.governance.supervisor import RuntimeSupervisor, InterventionLevel
except ImportError:
    RuntimeSupervisor = None
```

- [ ] **Step 2: 在 run() 方法中初始化 Supervisor**

在 `result_text = ""` 之后（line 74 附近）添加：

```python
supervisor = RuntimeSupervisor() if RuntimeSupervisor else None
```

- [ ] **Step 3: 在每轮 AssistantMessage 处理中，记录工具调用到 Supervisor**

在 tool_calls 解析完成后（line 101 之后），`if AgentTurnEvent:` 之前，添加：

```python
                # ── Supervisor: 记录工具调用 ──
                if supervisor and tool_calls:
                    for tc in tool_calls:
                        # 从 input_preview 还原简化 params（用于签名）
                        supervisor.record_tool_call(
                            tc.get("tool", ""),
                            {"_preview": tc.get("input_preview", "")},
                        )
```

- [ ] **Step 4: 在 Stuck Detection 之后添加 Supervisor 评估**

在 Doom Loop 检查之后（line 175 附近），添加 Supervisor 评估逻辑：

```python
                # ── Supervisor: 每轮评估 ──
                if supervisor:
                    supervisor.end_turn()
                    if turn > 0 and turn % 3 == 0:
                        intervention = supervisor.evaluate(iteration=turn)
                        if intervention:
                            self._log_event(task_id, "supervisor_intervention", {
                                "level": intervention.level.name,
                                "pattern": intervention.pattern,
                                "message": intervention.message,
                                "turn": turn,
                                **intervention.details,
                            })
                            if intervention.level >= InterventionLevel.TERMINATE:
                                log.warning(f"Supervisor TERMINATE: task #{task_id} — {intervention.message}")
                                result_text = f"[SUPERVISOR: {intervention.pattern}] {intervention.message}"
                                break
                            elif intervention.level >= InterventionLevel.NUDGE:
                                log.info(f"Supervisor NUDGE: task #{task_id} — {intervention.message}")
                                # NUDGE: 记录但不中断（后续可以注入提示到 agent 上下文）
```

- [ ] **Step 5: 运行现有测试确保不破坏**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/ -v --tb=short`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/governance/executor_session.py
git commit -m "feat(session): 集成 RuntimeSupervisor 到 Agent 运行循环"
```

---

### Task 4: StuckDetector 增加签名重复检测 (Pattern 6)

**Files:**
- Modify: `src/governance/stuck_detector.py`
- Modify: `tests/governance/test_doom_loop.py`

- [ ] **Step 1: 写失败测试**

在 `tests/governance/test_doom_loop.py` 末尾添加：

```python
from src.governance.stuck_detector import StuckDetector


class TestStuckDetectorSignatureRepeat:
    """StuckDetector Pattern 6: 完全相同参数的工具调用重复。"""

    def test_signature_repeat_detected(self):
        d = StuckDetector()
        for _ in range(6):
            d.record({"data": {
                "tools": ["Read"],
                "tools_detail": [{"tool": "Read", "input_preview": "file_path: /same.py"}],
                "text": [""],
                "error": "",
            }})
        stuck, pattern = d.is_stuck()
        assert stuck
        assert pattern == "SIGNATURE_REPEAT"

    def test_different_inputs_not_signature_repeat(self):
        d = StuckDetector()
        for i in range(6):
            d.record({"data": {
                "tools": ["Read"],
                "tools_detail": [{"tool": "Read", "input_preview": f"file_path: /file_{i}.py"}],
                "text": [""],
                "error": "",
            }})
        stuck, pattern = d.is_stuck()
        assert not stuck
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/test_doom_loop.py::TestStuckDetectorSignatureRepeat -v`
Expected: FAIL — `AssertionError`

- [ ] **Step 3: 实现 Pattern 6**

在 `stuck_detector.py` 的 `is_stuck()` 方法中，在 Pattern 5 之后添加：

```python
        # Pattern 6: Signature repeat (same tool + same input)
        if self._check_signature_repeat(recent):
            return True, "SIGNATURE_REPEAT"
```

添加检测方法：

```python
    def _check_signature_repeat(self, events: list[dict]) -> bool:
        """Same tool with same input parameters repeating 3+ times."""
        signatures = []
        for e in events:
            data = e.get("data", {})
            for tool_detail in (data.get("tools_detail") or []):
                sig = f"{tool_detail.get('tool', '')}:{tool_detail.get('input_preview', '')[:100]}"
                signatures.append(sig)
        if len(signatures) < 3:
            return False
        from collections import Counter
        counts = Counter(signatures)
        _, top_count = counts.most_common(1)[0]
        return top_count >= 3
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/test_doom_loop.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add src/governance/stuck_detector.py tests/governance/test_doom_loop.py
git commit -m "feat(stuck): Pattern 6 — 签名重复检测，相同 tool+input 3次触发"
```

---

### Task 5: 进度感知超时

**Files:**
- Modify: `src/governance/executor_session.py`

这个需要特殊处理：Agent SDK 的 `query()` 是一个 async generator，我们无法直接给它加 progress-aware timeout。但我们可以在外层用 `asyncio.wait_for` + 心跳重置机制实现。

- [ ] **Step 1: 在 AgentSessionRunner 中添加进度追踪**

在 `__init__` 中添加进度指纹追踪：

```python
    def __init__(self, db, log_event_fn=None):
        self.db = db
        self._log_event = log_event_fn or self._default_log_event
        self._last_progress_turn = 0
        self._last_tool_count = 0
```

- [ ] **Step 2: 在 run() 中跟踪进度指纹**

在每轮 AssistantMessage 处理结尾（Supervisor 评估之后），添加进度指纹更新：

```python
                # ── Progress fingerprint: 追踪实际进展 ──
                if tool_calls:
                    self._last_progress_turn = turn
                    self._last_tool_count += len(tool_calls)
```

- [ ] **Step 3: 添加 idle_turns 属性供 executor 查询**

```python
    @property
    def idle_turns(self) -> int:
        """自上次有工具调用以来过去了多少轮。"""
        return (self._last_progress_turn - self._last_progress_turn)
        # 注意：这个值在 run() 完成后才有意义
```

实际上，进度感知超时更适合在 executor.py 层面实现。AgentSessionRunner 已经有 stuck/doom loop 检测覆盖了"无进展"场景。现有的硬超时 + stuck detector 组合已经等效于 progress-aware timeout。

**决策：跳过独立的 progress-aware timeout 实现，因为 StuckDetector (Pattern 1-6) + DoomLoop + Supervisor 已经覆盖了所有"无进展"场景。硬超时作为最后兜底保留。**

- [ ] **Step 4: Commit (如果有改动)**

如果上述分析后决定不实现，跳过此步。

---

### Task 6: 端到端验证

**Files:**
- None (运行现有测试 + 新测试)

- [ ] **Step 1: 运行全部 governance 测试**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/governance/ -v --tb=short`
Expected: All passed

- [ ] **Step 2: 运行全部测试确保无回归**

Run: `cd /d/Users/Administrator/Documents/GitHub/orchestrator && python -m pytest tests/ -v --tb=short -x`
Expected: All passed (或只有预期的已知失败)

- [ ] **Step 3: 最终 Commit**

```bash
git add -A
git commit -m "feat(governance): OpenAkita P0 偷师 — RuntimeSupervisor + 签名重复 + 编辑抖动 + 空转检测"
```
