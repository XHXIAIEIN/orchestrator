# Governance 全局重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 governance/ 从 37 个平铺文件 + 1187 行 God Object 重组为 6 个子包 + 4 个专职类，同时拆分 scheduler.py

**Architecture:** Governor.py 拆为 Scrutinizer/Dispatcher/Executor/ReviewManager 四个类，Governor 保留为瘦协调器。37 个叶子文件按领域分进 budget/safety/audit/context/policy/pipeline/learning 7 个子包。Scheduler 提取 jobs/ 包 + 通用 wrapper。

**Tech Stack:** Python 3.11+, pytest, claude_agent_sdk, apscheduler

**Spec:** `docs/superpowers/specs/2026-03-23-governance-refactor-design.md`

---

## File Structure

### governance/ 子包结构（新建）

```
src/governance/
├── governor.py              # 瘦协调器 ~80行 (重写)
├── scrutiny.py              # 新建：从 governor.py 提取
├── dispatcher.py            # 新建：从 governor.py 提取
├── executor.py              # 新建：从 governor.py 提取
├── review.py                # 新建：从 governor.py 提取
├── governor_cli.py          # 保留，更新 import
├── budget/
│   ├── __init__.py
│   └── token_budget.py      # 移动自 governance/token_budget.py
├── safety/
│   ├── __init__.py
│   ├── doom_loop.py
│   ├── immutable_constraints.py
│   ├── verify_gate.py
│   └── agent_semaphore.py
├── audit/
│   ├── __init__.py
│   ├── run_logger.py
│   ├── outcome_tracker.py
│   ├── punch_clock.py
│   └── heartbeat.py
├── context/
│   ├── __init__.py
│   ├── context_assembler.py
│   ├── domain_pack.py
│   ├── prompts.py
│   ├── memory_tier.py
│   ├── memory_supersede.py
│   └── intent_manifest.py
├── policy/
│   ├── __init__.py
│   ├── blueprint.py
│   ├── policy_advisor.py
│   ├── prompt_canary.py
│   ├── seed_contract.py
│   ├── novelty_policy.py
│   ├── tiered_review.py
│   └── deterministic_resolver.py
├── pipeline/
│   ├── __init__.py
│   ├── stage_pipeline.py
│   ├── scratchpad.py
│   ├── fan_out.py
│   ├── eval_loop.py
│   └── scout.py
└── learning/
    ├── __init__.py
    ├── learn_from_edit.py
    ├── skill_evolver.py
    ├── debt_scanner.py
    ├── debt_resolver.py
    ├── deslop.py
    └── cafi_index.py
```

### jobs/ 包（新建）

```
src/jobs/
├── __init__.py              # run_job wrapper
├── collectors.py            # run_collectors()
├── analysis.py              # run_analysis()
├── maintenance.py           # debt_scan, debt_resolve, health, voice_refresh
└── periodic.py              # profile, performance, skill_evolution, policy, weekly_audit
```

---

## Task 1: 创建子包目录 + 移动叶子文件

**Files:**
- Create: `src/governance/budget/__init__.py`, `src/governance/safety/__init__.py`, `src/governance/audit/__init__.py`, `src/governance/context/__init__.py`, `src/governance/policy/__init__.py`, `src/governance/pipeline/__init__.py`, `src/governance/learning/__init__.py`
- Move: 30 个叶子文件到对应子包

- [ ] **Step 1: 创建 7 个子包目录 + `__init__.py`**

```bash
cd /d/Users/Administrator/Documents/GitHub/orchestrator
for pkg in budget safety audit context policy pipeline learning; do
  mkdir -p src/governance/$pkg
  touch src/governance/$pkg/__init__.py
done
```

- [ ] **Step 2: 移动 budget/ 文件**

```bash
mv src/governance/token_budget.py src/governance/budget/
```

- [ ] **Step 3: 移动 safety/ 文件**

```bash
mv src/governance/doom_loop.py src/governance/safety/
mv src/governance/immutable_constraints.py src/governance/safety/
mv src/governance/verify_gate.py src/governance/safety/
mv src/governance/agent_semaphore.py src/governance/safety/
```

- [ ] **Step 4: 移动 audit/ 文件**

```bash
mv src/governance/run_logger.py src/governance/audit/
mv src/governance/outcome_tracker.py src/governance/audit/
mv src/governance/punch_clock.py src/governance/audit/
mv src/governance/heartbeat.py src/governance/audit/
```

- [ ] **Step 5: 移动 context/ 文件**

```bash
mv src/governance/context_assembler.py src/governance/context/
mv src/governance/domain_pack.py src/governance/context/
mv src/governance/prompts.py src/governance/context/
mv src/governance/memory_tier.py src/governance/context/
mv src/governance/memory_supersede.py src/governance/context/
mv src/governance/intent_manifest.py src/governance/context/
```

- [ ] **Step 6: 移动 policy/ 文件**

```bash
mv src/governance/blueprint.py src/governance/policy/
mv src/governance/policy_advisor.py src/governance/policy/
mv src/governance/prompt_canary.py src/governance/policy/
mv src/governance/seed_contract.py src/governance/policy/
mv src/governance/novelty_policy.py src/governance/policy/
mv src/governance/tiered_review.py src/governance/policy/
mv src/governance/deterministic_resolver.py src/governance/policy/
```

- [ ] **Step 7: 移动 pipeline/ 文件**

```bash
mv src/governance/stage_pipeline.py src/governance/pipeline/
mv src/governance/scratchpad.py src/governance/pipeline/
mv src/governance/fan_out.py src/governance/pipeline/
mv src/governance/eval_loop.py src/governance/pipeline/
mv src/governance/scout.py src/governance/pipeline/
```

- [ ] **Step 8: 移动 learning/ 文件**

```bash
mv src/governance/learn_from_edit.py src/governance/learning/
mv src/governance/skill_evolver.py src/governance/learning/
mv src/governance/debt_scanner.py src/governance/learning/
mv src/governance/debt_resolver.py src/governance/learning/
mv src/governance/deslop.py src/governance/learning/
mv src/governance/cafi_index.py src/governance/learning/
```

- [ ] **Step 9: 备份 governor.py + 移除废弃文件**

```bash
mkdir -p .trash/2026-03-23-governance-refactor
cp src/governance/governor.py .trash/2026-03-23-governance-refactor/governor.py.bak
# task_lifecycle.py 无外部引用（仅 cafi_index.py 有字符串常量引用），直接归档
mv src/governance/task_lifecycle.py .trash/2026-03-23-governance-refactor/
```

- [ ] **Step 10: 清理 `__pycache__`**

```bash
find src/governance -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
```

---

## Task 2: 更新叶子文件的内部 import

移动后，叶子文件内部的 `from src.governance.xxx` 需要改成新路径。

**Files:** 修改所有移动后的叶子文件中的 cross-reference import

- [ ] **Step 1: 更新 `context/context_assembler.py` 内部 import**

文件 `src/governance/context/context_assembler.py:125` 有:
```python
from src.governance.memory_tier import (
```
改为:
```python
from src.governance.context.memory_tier import (
```

- [ ] **Step 2: 更新 `policy/policy_advisor.py` 内部 import**

文件 `src/governance/policy/policy_advisor.py:272` 有:
```python
from src.governance.blueprint import load_blueprint
```
改为:
```python
from src.governance.policy.blueprint import load_blueprint
```

- [ ] **Step 3: 全量搜索确认无遗漏**

```bash
grep -rn "from src\.governance\.\(token_budget\|doom_loop\|immutable_constraints\|verify_gate\|agent_semaphore\|run_logger\|outcome_tracker\|punch_clock\|heartbeat\|context_assembler\|domain_pack\|prompts\|memory_tier\|memory_supersede\|intent_manifest\|blueprint\|policy_advisor\|prompt_canary\|seed_contract\|novelty_policy\|tiered_review\|deterministic_resolver\|stage_pipeline\|scratchpad\|fan_out\|eval_loop\|scout\|learn_from_edit\|skill_evolver\|debt_scanner\|debt_resolver\|deslop\|cafi_index\)" src/ --include="*.py" | grep -v governor.py | grep -v __pycache__
```

对每个匹配项更新 import 路径。

- [ ] **Step 4: 更新外部消费方 import**

以下文件引用了被移动的模块：

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| `src/analysis/analyst.py:6` | `from src.governance.prompts import load_prompt` | `from src.governance.context.prompts import load_prompt` |
| `src/analysis/insights.py:14` | `from src.governance.prompts import load_prompt` | `from src.governance.context.prompts import load_prompt` |
| `src/analysis/profile_analyst.py:12` | `from src.governance.prompts import load_prompt` | `from src.governance.context.prompts import load_prompt` |
| `src/gateway/handlers.py:12` | `from src.governance.run_logger import ...` | `from src.governance.audit.run_logger import ...` |
| `src/scheduler.py:15` | `from src.governance.debt_scanner import DebtScanner` | `from src.governance.learning.debt_scanner import DebtScanner` |
| `src/scheduler.py:16` | `from src.governance.debt_resolver import ...` | `from src.governance.learning.debt_resolver import ...` |
| `src/scheduler.py:19` | `from src.governance.skill_evolver import run_evolution` | `from src.governance.learning.skill_evolver import run_evolution` |
| `src/scheduler.py:20` | `from src.governance.policy_advisor import ...` | `from src.governance.policy.policy_advisor import ...` |

- [ ] **Step 5: 更新测试文件 import**

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| `tests/test_debt_scanner_router.py:3` | `from src.governance.debt_scanner import DebtScanner` | `from src.governance.learning.debt_scanner import DebtScanner` |
| `tests/test_governor_async.py:102` | `from src.governance.verify_gate import ...` | `from src.governance.safety.verify_gate import ...` |

- [ ] **Step 6: 跑测试验证**

```bash
python -m pytest --tb=short -q 2>&1 | tail -20
```
Expected: 185 tests collected, all pass (或已知的预期 failure 保持不变)

- [ ] **Step 7: Commit**

```bash
git add -A src/governance/ src/analysis/ src/gateway/ src/scheduler.py tests/
git commit -m "refactor(governance): move 30 leaf files into 7 domain sub-packages"
```

---

## Task 3: 拆 governor.py → 4 个专职类

这是最核心的一步。从 1187 行的 God Object 中提取 4 个类。

**Files:**
- Create: `src/governance/scrutiny.py`, `src/governance/dispatcher.py`, `src/governance/executor.py`, `src/governance/review.py`
- Rewrite: `src/governance/governor.py`

### 依赖方向（不可违反）
```
Governor ──→ Dispatcher ──→ Scrutinizer
    │
    └──→ Executor ──→ ReviewManager
```
Dispatcher ✕ Executor: 互不知道对方存在

- [ ] **Step 1: 创建 `src/governance/scrutiny.py`**

从 governor.py 提取：
- `classify_cognitive_mode()` (L66-101)
- `estimate_blast_radius()` (L104-119)
- `_parse_scrutiny_verdict()` (L155-160)
- `Governor.scrutinize()` (L172-235) → `Scrutinizer.scrutinize()`

```python
"""门下省审查 — 任务进入执行前的质量关卡。"""
import logging
from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.governance.context.prompts import SCRUTINY_PROMPT, SECOND_OPINION_MODEL
from src.governance.policy.blueprint import load_blueprint
from src.governance.context.context_assembler import assemble_context

log = logging.getLogger(__name__)


def classify_cognitive_mode(task: dict) -> str:
    # ... 从 governor.py L66-101 原样搬过来 ...

def estimate_blast_radius(spec: dict) -> str:
    # ... 从 governor.py L104-119 原样搬过来 ...

def _parse_scrutiny_verdict(text: str) -> tuple[bool, str]:
    # ... 从 governor.py L155-160 原样搬过来 ...


class Scrutinizer:
    def __init__(self, db: EventsDB):
        self.db = db

    def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
        # ... 从 Governor.scrutinize() L172-235 原样搬过来 ...
        # 内部调用 classify_cognitive_mode, estimate_blast_radius, _parse_scrutiny_verdict
```

- [ ] **Step 2: 创建 `src/governance/dispatcher.py`**

从 governor.py 提取：
- `Governor._reap_zombie_tasks()` (L237-265)
- `Governor._get_available_slots()` (L266-281)
- `Governor._dispatch_task()` (L283-385) — **注意**：删除末尾的 `self.execute_task_async(task_id)` 调用，改为返回 task_id
- `Governor.run_batch()` (L389-449) — 改为返回 task_id 列表
- `Governor.run_parallel_scenario()` (L451-494) — 改为返回 task_id 列表

```python
"""任务调度 — 从 insight 队列选任务、预检、审查、分配执行槽位。"""
import json
import logging
from datetime import datetime, timezone

from src.storage.events_db import EventsDB
from src.governance.scrutiny import Scrutinizer, classify_cognitive_mode
from src.governance.safety.agent_semaphore import AgentSemaphore
from src.governance.policy.blueprint import load_blueprint, run_preflight, preflight_passed
from src.governance.context.prompts import PARALLEL_SCENARIOS
from src.gateway.complexity import classify_complexity, should_skip_scrutiny

# 可选依赖
try:
    from src.governance.policy.novelty_policy import check_novelty, get_recent_failures
except ImportError:
    check_novelty = None

try:
    from src.governance.policy.deterministic_resolver import get_deterministic_fallback
except ImportError:
    get_deterministic_fallback = None

log = logging.getLogger(__name__)

STALE_THRESHOLD = 420  # seconds
MAX_CONCURRENT = 3


class TaskDispatcher:
    def __init__(self, db: EventsDB, scrutinizer: Scrutinizer):
        self.db = db
        self.scrutinizer = scrutinizer
        self.semaphore = AgentSemaphore()

    def dispatch_task(self, spec, action, reason, priority="high", source="auto") -> int | None:
        """返回 approved task_id，不负责执行。"""
        # ... 从 _dispatch_task L283-383 搬过来 ...
        # 最后 return task_id (不调用 execute_task_async)

    def run_batch(self, max_dispatch=MAX_CONCURRENT) -> list[int]:
        """返回待执行的 task_id 列表。"""
        # ... 从 run_batch L389-449 搬过来 ...
        # 收集 dispatch_task 返回的 task_id

    def run_parallel_scenario(self, scenario_name, project="orchestrator", **kw) -> list[int]:
        # ... 从 run_parallel_scenario L451-494 搬过来 ...
```

- [ ] **Step 3: 创建 `src/governance/executor.py`**

从 governor.py 提取：
- `_in_async_context()` (L122-129)
- `_resolve_project_cwd()` (L132-140)
- `_extract_target_files()` (L143-152)
- `Governor._prepare_prompt()` (L510-578)
- `Governor._log_agent_event()` (L580-585)
- `Governor._run_agent_session()` (L587-686)
- `Governor.execute_task()` (L814-949)
- `Governor.execute_task_async()` (L498-508)
- `Governor._visual_verify()` (L1159-1187)
- `Governor._extract_artifact()` (L954-995)

```python
"""任务执行 — Agent SDK 调用 + prompt 组装 + 运行时监控。"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anyio
from claude_agent_sdk import (
    query, ClaudeAgentOptions, ResultMessage,
    AssistantMessage, TaskStartedMessage, TaskProgressMessage,
)

from src.storage.events_db import EventsDB
from src.core.llm_router import get_router
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS, DEPARTMENTS,
    load_department, find_git_bash,
)
from src.governance.policy.blueprint import load_blueprint, get_allowed_tools, AuthorityCeiling
from src.governance.safety.immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint
from src.gateway.routing import resolve_route, get_policy_config
from src.gateway.complexity import classify_complexity, should_skip_scrutiny, get_recommended_turns
from src.governance.scrutiny import classify_cognitive_mode

# 可选依赖
try:
    from src.governance.budget.token_budget import TokenAccountant
except ImportError:
    TokenAccountant = None

try:
    from src.governance.safety.doom_loop import check_doom_loop
except ImportError:
    check_doom_loop = None

try:
    from src.governance.safety.verify_gate import run_gates, save_gate_record
except ImportError:
    run_gates = None

try:
    from src.governance.audit.heartbeat import parse_progress, HEARTBEAT_PROMPT
except ImportError:
    parse_progress = None
    HEARTBEAT_PROMPT = ""

try:
    from src.governance.audit.punch_clock import get_punch_clock
except ImportError:
    get_punch_clock = None

try:
    from src.governance.audit.run_logger import format_runs_for_context
except ImportError:
    format_runs_for_context = None

try:
    from src.governance.policy.prompt_canary import should_use_canary, get_canary_prompt
except ImportError:
    should_use_canary = None

log = logging.getLogger(__name__)

MAX_AGENT_TURNS = 25
CLAUDE_TIMEOUT = 300


class TaskExecutor:
    def __init__(self, db: EventsDB, on_finalize: Callable | None = None):
        self.db = db
        self.accountant = TokenAccountant(db=db) if TokenAccountant else None
        self.punch_clock = get_punch_clock() if get_punch_clock else None
        self.on_finalize = on_finalize  # ReviewManager.finalize_task 回调

    def execute_task(self, task_id: int) -> dict:
        # ... 从 Governor.execute_task L814-949 搬过来 ...
        # finally 块中调用 self.on_finalize(...) 替代 self._finalize_task(...)

    def execute_task_async(self, task_id: int):
        # ... 从 Governor.execute_task_async L498-508 搬过来 ...
```

- [ ] **Step 4: 创建 `src/governance/review.py`**

从 governor.py 提取：
- `Governor._finalize_task()` (L688-812)
- `Governor._dispatch_quality_review()` (L997-1071)
- `Governor._dispatch_rework()` (L1073-1157)

```python
"""评审与返工 — 执行后质量检查 + 工部→刑部协作链。"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable

from src.storage.events_db import EventsDB
from src.governance.pipeline.eval_loop import parse_eval_output, format_eval_for_rework, MAX_EVAL_ITERATIONS
from src.governance.scrutiny import classify_cognitive_mode

# 必须依赖
from src.governance.policy.blueprint import load_blueprint

# 可选依赖
try:
    from src.governance.pipeline.scratchpad import write_scratchpad, build_handoff_prompt
except ImportError:
    write_scratchpad = None
    build_handoff_prompt = None

try:
    from src.governance.audit.run_logger import append_run_log
except ImportError:
    append_run_log = None

try:
    from src.governance.audit.outcome_tracker import record_outcome
except ImportError:
    record_outcome = None

try:
    from src.governance.pipeline.fan_out import get_fan_out
except ImportError:
    get_fan_out = None

try:
    from src.governance.policy.tiered_review import determine_review_tier, get_review_config
except ImportError:
    determine_review_tier = None

try:
    from src.governance.policy.policy_advisor import observe_task_execution
except ImportError:
    observe_task_execution = None

try:
    from src.governance.context.intent_manifest import build_manifest
except ImportError:
    build_manifest = None

log = logging.getLogger(__name__)


class ReviewManager:
    MAX_REWORK = MAX_EVAL_ITERATIONS - 1

    def __init__(self, db: EventsDB, on_execute: Callable[[int], None] | None = None):
        self.db = db
        self.on_execute = on_execute  # Governor 注入的执行回调

    def finalize_task(self, task_id, task, dept_key, status, output, task_cwd, project_name, now):
        # ... 从 _finalize_task L688-812 搬过来 ...

    def _dispatch_quality_review(self, parent_id, parent_task, task_cwd, project_name):
        # ... 从 _dispatch_quality_review L997-1071 搬过来 ...
        # 末尾 self.on_execute(review_id) 替代 self.execute_task_async(review_id)

    def _dispatch_rework(self, review_task_id, review_task, task_cwd, project_name, review_output, eval_result=None):
        # ... 从 _dispatch_rework L1073-1157 搬过来 ...
        # self.on_execute(rework_id) 替代 self.execute_task_async(rework_id)
```

- [ ] **Step 5: 重写 `src/governance/governor.py` 为瘦协调器**

```python
"""Governor — 瘦协调器，组合 Scrutinizer/Dispatcher/Executor/ReviewManager。"""
from src.storage.events_db import EventsDB
from src.governance.scrutiny import Scrutinizer
from src.governance.dispatcher import TaskDispatcher
from src.governance.executor import TaskExecutor
from src.governance.review import ReviewManager


class Governor:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.db = db or EventsDB(db_path)
        self.scrutinizer = Scrutinizer(self.db)
        self.dispatcher = TaskDispatcher(self.db, self.scrutinizer)
        self.reviewer = ReviewManager(self.db, on_execute=self._execute_async)
        self.executor = TaskExecutor(self.db, on_finalize=self.reviewer.finalize_task)

    def _execute_async(self, task_id: int):
        self.executor.execute_task_async(task_id)

    def run_batch(self, max_dispatch: int = 3) -> list[dict]:
        task_ids = self.dispatcher.run_batch(max_dispatch)
        for tid in task_ids:
            self.executor.execute_task_async(tid)
        return [self.db.get_task(tid) for tid in task_ids]

    def run_parallel_scenario(self, scenario_name: str, **kw) -> list[dict]:
        task_ids = self.dispatcher.run_parallel_scenario(scenario_name, **kw)
        for tid in task_ids:
            self.executor.execute_task_async(tid)
        return [self.db.get_task(tid) for tid in task_ids]

    def execute_task(self, task_id: int) -> dict:
        return self.executor.execute_task(task_id)

    def execute_task_async(self, task_id: int):
        return self.executor.execute_task_async(task_id)
```

- [ ] **Step 6: 更新 governor_cli.py import**

`src/governance/governor_cli.py:10`: import 路径不变（governor.py 还在原位），但确认 Governor 的公开接口没变。

- [ ] **Step 7: 更新外部消费方 import（如果有变化）**

检查 `src/channels/chat.py`、`src/channels/inbound.py`、`src/scheduler.py` 中的 `from src.governance.governor import Governor` — 路径不变，但确认 `Governor.run_batch()` 的返回值类型是否兼容。

原 `run_batch()` 返回 `list[dict]`，新版保持一致。

- [ ] **Step 8: 跑测试验证**

```bash
python -m pytest --tb=short -q 2>&1 | tail -20
```
Expected: 185 tests, all pass

- [ ] **Step 9: Commit**

```bash
git add src/governance/scrutiny.py src/governance/dispatcher.py src/governance/executor.py src/governance/review.py src/governance/governor.py
git commit -m "refactor(governance): split Governor God Object into Scrutinizer/Dispatcher/Executor/ReviewManager"
```

---

## Task 4: 拆 scheduler.py → jobs/ + 瘦 scheduler

**Files:**
- Create: `src/jobs/__init__.py`, `src/jobs/collectors.py`, `src/jobs/analysis.py`, `src/jobs/maintenance.py`, `src/jobs/periodic.py`
- Rewrite: `src/scheduler.py`

- [ ] **Step 1: 创建 `src/jobs/__init__.py`**

```python
"""Job 执行基础设施 — 统一 wrapper。"""
import logging
import time
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


def run_job(name: str, fn, db: EventsDB):
    """统一 job wrapper：日志 + 异常捕获 + 耗时。"""
    db.write_log(f"开始 {name}", "INFO", name)
    t0 = time.time()
    try:
        result = fn(db)
        elapsed = time.time() - t0
        db.write_log(f"{name} 完成 ({elapsed:.1f}s)", "INFO", name)
        return result
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"{name} failed after {elapsed:.1f}s: {e}")
        db.write_log(f"{name} 失败: {e}", "ERROR", name)
```

- [ ] **Step 2: 创建 `src/jobs/collectors.py`**

从 scheduler.py 提取 `run_collectors()` (L44-106) + `_is_collector_enabled()` (保留但标记 DEPRECATED)

```python
"""采集 job — 并行跑 collectors + burst 检测 + 健康自检。"""
# ... 从 scheduler.py L44-106 搬过来 ...
# 函数签名改为 def run_collectors(db: EventsDB): 接收 db 参数
```

- [ ] **Step 3: 创建 `src/jobs/analysis.py`**

从 scheduler.py 提取 `run_analysis()` (L109-163)

```python
"""分析 job — 日报 + 洞察 + Governor 批处理 + 健康自检→自修复。"""
# ... 从 scheduler.py L109-163 搬过来 ...
# 函数签名改为 def run_analysis(db: EventsDB):
```

- [ ] **Step 4: 创建 `src/jobs/maintenance.py`**

从 scheduler.py 提取：`_debt_scan()`, `_debt_resolve()`, `_voice_refresh()`

```python
"""维护 job — 债务扫描/解决、声音池刷新。"""
# 每个函数签名改为 def xxx(db: EventsDB):
```

- [ ] **Step 5: 创建 `src/jobs/periodic.py`**

从 scheduler.py 提取：`_profile_periodic()`, `_profile_daily()`, `_performance_report()`, `_skill_evolution()`, `_policy_suggestions()`, `_weekly_audit()`

```python
"""周期 job — 画像分析、绩效报告、技能演进、策略建议、每周审计。"""
# 每个函数签名改为 def xxx(db: EventsDB):
```

- [ ] **Step 6: 重写 `src/scheduler.py` 为瘦启动器**

```python
"""Scheduler — 声明式 job 注册 + 启动。"""
import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.storage.events_db import EventsDB
from src.jobs import run_job
from src.jobs.collectors import run_collectors
from src.jobs.analysis import run_analysis
from src.jobs.maintenance import debt_scan, debt_resolve, voice_refresh
from src.jobs.periodic import (
    profile_periodic, profile_daily, performance_report,
    skill_evolution, policy_suggestions, weekly_audit,
)

log = logging.getLogger(__name__)
DB_PATH = str(Path(__file__).parent.parent / "data" / "events.db")


def start():
    db = EventsDB(DB_PATH)
    s = BlockingScheduler()

    s.add_job(lambda: run_job("collectors", run_collectors, db), "interval", hours=1, id="collectors")
    s.add_job(lambda: run_job("analysis", run_analysis, db), "interval", hours=6, id="analysis")
    s.add_job(lambda: run_job("profile_periodic", profile_periodic, db), "interval", hours=6, id="profile_periodic")
    s.add_job(lambda: run_job("profile_daily", profile_daily, db), "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
    s.add_job(lambda: run_job("debt_scan", debt_scan, db), "interval", hours=12, id="debt_scan")
    s.add_job(lambda: run_job("debt_resolve", debt_resolve, db), "interval", hours=12, start_date="2026-01-01 01:00:00", timezone="Asia/Shanghai", id="debt_resolve")
    s.add_job(lambda: run_job("performance", performance_report, db), "cron", hour=8, timezone="Asia/Shanghai", id="performance_report")
    s.add_job(lambda: run_job("voice_refresh", voice_refresh, db), "interval", days=7, id="voice_refresh")
    s.add_job(lambda: run_job("skill_evolution", skill_evolution, db), "cron", day_of_week="mon", hour=9, timezone="Asia/Shanghai", id="skill_evolution")
    s.add_job(lambda: run_job("policy_suggestions", policy_suggestions, db), "cron", hour=7, timezone="Asia/Shanghai", id="policy_suggestions")
    s.add_job(lambda: run_job("weekly_audit", weekly_audit, db), "cron", day_of_week="wed", hour=10, timezone="Asia/Shanghai", id="weekly_audit")

    # Channel 层启动
    try:
        from src.channels.registry import get_channel_registry
        from src.channels.inbound import register_inbound_handlers
        reg = get_channel_registry()
        reg.start_all()
        register_inbound_handlers(db_path=DB_PATH)
        status = reg.get_status()
        if status:
            db.write_log(f"Channel 层已启动: {', '.join(status.keys())}", "INFO", "channels")
    except Exception as e:
        log.warning(f"Channel layer init failed (non-fatal): {e}")

    db.write_log("调度器已启动", "INFO", "scheduler")
    log.info("Scheduler started. Running initial collection + debt scan...")

    run_job("collectors", run_collectors, db)
    run_job("debt_scan", debt_scan, db)
    run_job("debt_resolve", debt_resolve, db)

    try:
        s.start()
    except (KeyboardInterrupt, SystemExit):
        try:
            from src.channels.registry import get_channel_registry
            get_channel_registry().stop_all()
        except Exception:
            pass
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
```

- [ ] **Step 7: 备份旧 scheduler.py**

```bash
cp .trash/2026-03-23-governance-refactor/  # 已在 Task 1 创建
cp src/scheduler.py .trash/2026-03-23-governance-refactor/scheduler.py.bak
```

- [ ] **Step 8: 跑测试验证**

```bash
python -m pytest --tb=short -q 2>&1 | tail -20
```

- [ ] **Step 9: Commit**

```bash
git add src/jobs/ src/scheduler.py
git commit -m "refactor(scheduler): extract jobs/ package with unified run_job wrapper"
```

---

## Task 5: 清理 + 全量验证

- [ ] **Step 1: 确认顶层 governance/ 只剩预期文件**

```bash
# 列出顶层 .py 文件，排除子包
ls src/governance/*.py
```
Expected 文件列表（正好 7 个）：
- `__init__.py`, `governor.py`, `scrutiny.py`, `dispatcher.py`, `executor.py`, `review.py`, `governor_cli.py`

如果有多余文件，移到 `.trash/2026-03-23-governance-refactor/`。

- [ ] **Step 2: 清理 `__pycache__`**

```bash
find src/ tests/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
```

- [ ] **Step 3: 全量测试**

```bash
python -m pytest --tb=short -v 2>&1 | tail -40
```
Expected: 185 tests, all pass

- [ ] **Step 4: Import 完整性检查**

```bash
python -c "
from src.governance.governor import Governor
from src.governance.scrutiny import Scrutinizer
from src.governance.dispatcher import TaskDispatcher
from src.governance.executor import TaskExecutor
from src.governance.review import ReviewManager
from src.governance.budget.token_budget import TokenAccountant
from src.governance.safety.doom_loop import check_doom_loop
from src.governance.audit.run_logger import append_run_log
from src.governance.context.prompts import TASK_PROMPT_TEMPLATE
from src.governance.policy.blueprint import load_blueprint
from src.governance.pipeline.eval_loop import parse_eval_output
from src.governance.learning.debt_scanner import DebtScanner
from src.jobs import run_job
print('All imports OK')
"
```

- [ ] **Step 5: 验证 Governor 公开接口完整**

```bash
python -c "
from src.governance.governor import Governor
g = Governor.__new__(Governor)
for method in ['run_batch', 'run_parallel_scenario', 'execute_task', 'execute_task_async']:
    assert hasattr(g, method), f'Missing: {method}'
print('Governor interface OK')
"
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "refactor(governance): cleanup old files, verify all imports"
```

---

## Task 6: 写子包 `__init__.py` re-export

> **注意**：Task 1 Step 1 创建的 `__init__.py` 是空文件。此 Task 填入 re-export。
> 放在最后是因为 Task 2-3 中所有 import 都用全路径（如 `from src.governance.budget.token_budget import TokenAccountant`），
> 不依赖 `__init__.py` re-export。这些 re-export 是给外部消费方和未来维护者的便利接口。

每个子包的 `__init__.py` 只做 re-export，不写逻辑。

- [ ] **Step 1: 写 7 个 `__init__.py`**

```python
# src/governance/budget/__init__.py
from .token_budget import TokenAccountant

# src/governance/safety/__init__.py
from .doom_loop import check_doom_loop
from .immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint
from .verify_gate import run_gates, save_gate_record
from .agent_semaphore import AgentSemaphore

# src/governance/audit/__init__.py
from .run_logger import append_run_log, load_recent_runs
from .outcome_tracker import record_outcome
from .punch_clock import get_punch_clock
from .heartbeat import parse_progress

# src/governance/context/__init__.py
from .context_assembler import assemble_context
from .prompts import load_prompt, TASK_PROMPT_TEMPLATE
from .memory_tier import load_hot_memory

# src/governance/policy/__init__.py
from .blueprint import load_blueprint, run_preflight
from .policy_advisor import observe_task_execution

# src/governance/pipeline/__init__.py
from .eval_loop import parse_eval_output
from .scratchpad import write_scratchpad
from .fan_out import get_fan_out

# src/governance/learning/__init__.py
from .debt_scanner import DebtScanner
from .debt_resolver import resolve_debts
```

- [ ] **Step 2: 写 `src/governance/__init__.py`**

```python
# src/governance/__init__.py
from .governor import Governor
```

- [ ] **Step 3: 跑测试确认 re-export 没引入循环 import**

```bash
python -m pytest --tb=short -q 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add src/governance/*/\\__init__.py src/governance/__init__.py
git commit -m "refactor(governance): add sub-package re-exports"
```
