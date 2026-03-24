# Governance 全局重构设计

**Date**: 2026-03-23
**Scope**: C 路线 — 拆 governor.py + governance 子包重组 + 拆 scheduler.py + import 路径一步到位
**Breaking**: 所有旧 import 路径直接废弃，不保留兼容层

---

## 1. 问题

### governor.py — God Object
- 1187 行，16 个类方法 + 6 个模块级函数，34 个内部 import
- 11 个方法/函数超过 40 行（最大 136 行）
- 混合了 5 种职责：审查、调度、执行、评审、返工

### governance/ — 平铺 37 文件
- 偷师模式全部堆在一个目录，无逻辑分组
- 新加模块不知道该放哪里
- 相关文件靠命名猜关系（`debt_scanner.py` 和 `debt_resolver.py` 是一对，但只能靠人脑对应）

### scheduler.py — 胖调度器
- 342 行，10+ 个 job 函数全部硬编码
- 每个 job 函数都重复 `db = EventsDB(DB_PATH)` + try/except/log 模式
- 添加新 job 需要改 scheduler.py 本体

---

## 2. 设计

### 2.1 Governor 拆分

把 God Object 拆成 4 个专职类 + 1 个瘦协调器：

| 新文件 | 类 | 原方法 | 行数估算 |
|--------|-----|--------|----------|
| `governance/scrutiny.py` | `Scrutinizer` | `scrutinize()` + 模块级 `_parse_scrutiny_verdict()`, `classify_cognitive_mode()`, `estimate_blast_radius()` | ~120 |
| `governance/dispatcher.py` | `TaskDispatcher` | `_dispatch_task()`, `run_batch()`, `run_parallel_scenario()`, `_get_available_slots()`, `_reap_zombie_tasks()` | ~200 |
| `governance/executor.py` | `TaskExecutor` | `execute_task()`, `execute_task_async()`, `_prepare_prompt()`, `_run_agent_session()`, `_log_agent_event()`, `_visual_verify()`, `_extract_artifact()` + 模块级 `_in_async_context()`, `_resolve_project_cwd()`, `_extract_target_files()` | ~350 |
| `governance/review.py` | `ReviewManager` | `_dispatch_quality_review()`, `_dispatch_rework()`, `_finalize_task()` | ~250 |
| `governance/governor.py` | `Governor` | 瘦协调器，组合上述 4 个类 | ~80 |

**Governor 瘦身后的样子：**

```python
class Governor:
    def __init__(self, db=None, db_path="events.db"):
        self.db = db or EventsDB(db_path)
        self.scrutinizer = Scrutinizer(self.db)
        self.dispatcher = TaskDispatcher(self.db, self.scrutinizer)
        self.executor = TaskExecutor(self.db)
        self.reviewer = ReviewManager(self.db)

    def run_batch(self, max_dispatch=3):
        """Dispatcher 返回待执行 task_id 列表，Governor 负责驱动执行。"""
        task_ids = self.dispatcher.run_batch(max_dispatch)
        for tid in task_ids:
            self.executor.execute_task_async(tid)
        return task_ids

    def execute_task(self, task_id):
        return self.executor.execute_task(task_id)
```

**依赖方向**（严格单向，无循环）：

```
Governor ──→ Dispatcher ──→ Scrutinizer
    │
    └──→ Executor ──→ ReviewManager
```

- Dispatcher 和 Executor 互不知道对方存在
- Governor 是唯一的粘合点：Dispatcher 返回 task_id，Governor 交给 Executor
- ReviewManager 需要触发返工执行时，通过回调函数注入（`on_execute: Callable[[int], None]`），不直接依赖 Executor

**关键接口约定**：
- 所有类都接收 `db: EventsDB` 作为构造参数（依赖注入，方便测试）
- Dispatcher 只负责"能不能执行"的决策（preflight + scrutiny + semaphore），返回 approved task_id
- Executor 只负责"怎么执行"（prompt 组装 + Agent SDK 调用 + finalize）
- ReviewManager 只负责"执行完怎么办"（质量评审 + 返工派发）
- 跨模块调用全部通过 Governor facade 路由，子类之间不直接 import

### 2.2 Governance 子包重组

```
src/governance/
├── __init__.py              # 空，或只导出 Governor
├── governor.py              # 瘦协调器 (~80 行)
├── scrutiny.py              # 门下省审查 (~120 行)
├── dispatcher.py            # 任务调度 (~200 行)
├── executor.py              # Agent 执行 (~350 行)
├── review.py                # 评审 + 返工 (~250 行)
│
├── budget/
│   ├── __init__.py
│   └── token_budget.py      # TokenAccountant + 降级链
│
├── safety/
│   ├── __init__.py
│   ├── doom_loop.py         # 熔断器
│   ├── immutable_constraints.py  # 宪法级约束
│   ├── verify_gate.py       # 质量门控
│   └── agent_semaphore.py   # 并发信号量
│
├── audit/
│   ├── __init__.py
│   ├── run_logger.py        # 哈希链日志
│   ├── outcome_tracker.py   # 结果追踪
│   ├── punch_clock.py       # 文件锁
│   └── heartbeat.py         # 心跳
│
├── context/
│   ├── __init__.py
│   ├── context_assembler.py # 上下文组装
│   ├── domain_pack.py       # 领域包
│   ├── prompts.py           # prompt 模板
│   ├── memory_tier.py       # 两级记忆
│   └── memory_supersede.py  # 记忆取代
│
├── policy/
│   ├── __init__.py
│   ├── blueprint.py         # 蓝图 + 权限
│   ├── policy_advisor.py    # 策略顾问
│   ├── prompt_canary.py     # 金丝雀部署
│   ├── seed_contract.py     # 种子契约
│   ├── novelty_policy.py    # 新颖性策略
│   └── tiered_review.py     # 分级审查配置
│
├── pipeline/
│   ├── __init__.py
│   ├── stage_pipeline.py    # 阶段流水线
│   ├── scratchpad.py        # 文件传递
│   ├── fan_out.py           # 多路输出
│   └── eval_loop.py         # PLAN→ACT→EVAL
│
└── learning/
    ├── __init__.py
    ├── learn_from_edit.py   # 从编辑学习
    ├── skill_evolver.py     # 技能演化
    ├── debt_scanner.py      # 债务扫描
    ├── debt_resolver.py     # 债务解决
    ├── deslop.py            # 去废话
    └── cafi_index.py        # CAFI 指数
```

**分包原则**：
- 每个子包 3-6 个文件，内聚度高
- 子包之间可以互相 import，但不形成循环
- Governor 顶层文件不归入任何子包

**文件去向映射**（旧路径 → 新路径）：

| 旧 | 新 | 备注 |
|----|-----|------|
| `governance/token_budget.py` | `governance/budget/token_budget.py` | |
| `governance/doom_loop.py` | `governance/safety/doom_loop.py` | |
| `governance/immutable_constraints.py` | `governance/safety/immutable_constraints.py` | |
| `governance/verify_gate.py` | `governance/safety/verify_gate.py` | |
| `governance/agent_semaphore.py` | `governance/safety/agent_semaphore.py` | |
| `governance/run_logger.py` | `governance/audit/run_logger.py` | |
| `governance/outcome_tracker.py` | `governance/audit/outcome_tracker.py` | |
| `governance/punch_clock.py` | `governance/audit/punch_clock.py` | |
| `governance/heartbeat.py` | `governance/audit/heartbeat.py` | |
| `governance/context_assembler.py` | `governance/context/context_assembler.py` | |
| `governance/domain_pack.py` | `governance/context/domain_pack.py` | |
| `governance/prompts.py` | `governance/context/prompts.py` | |
| `governance/memory_tier.py` | `governance/context/memory_tier.py` | |
| `governance/memory_supersede.py` | `governance/context/memory_supersede.py` | |
| `governance/blueprint.py` | `governance/policy/blueprint.py` | |
| `governance/policy_advisor.py` | `governance/policy/policy_advisor.py` | |
| `governance/prompt_canary.py` | `governance/policy/prompt_canary.py` | |
| `governance/seed_contract.py` | `governance/policy/seed_contract.py` | |
| `governance/novelty_policy.py` | `governance/policy/novelty_policy.py` | |
| `governance/tiered_review.py` | `governance/policy/tiered_review.py` | |
| `governance/stage_pipeline.py` | `governance/pipeline/stage_pipeline.py` | |
| `governance/scratchpad.py` | `governance/pipeline/scratchpad.py` | |
| `governance/fan_out.py` | `governance/pipeline/fan_out.py` | |
| `governance/eval_loop.py` | `governance/pipeline/eval_loop.py` | |
| `governance/learn_from_edit.py` | `governance/learning/learn_from_edit.py` | |
| `governance/skill_evolver.py` | `governance/learning/skill_evolver.py` | |
| `governance/debt_scanner.py` | `governance/learning/debt_scanner.py` | |
| `governance/debt_resolver.py` | `governance/learning/debt_resolver.py` | |
| `governance/deslop.py` | `governance/learning/deslop.py` | |
| `governance/cafi_index.py` | `governance/learning/cafi_index.py` | |
| `governance/scout.py` | `governance/pipeline/scout.py` | 侦察模式 |
| `governance/deterministic_resolver.py` | `governance/policy/deterministic_resolver.py` | 策略类 |
| `governance/intent_manifest.py` | `governance/context/intent_manifest.py` | 上下文类 |
| `governance/governor_cli.py` | `governance/governor_cli.py` | 保持顶层 |
| `governance/task_lifecycle.py` | `governance/dispatcher.py` 内 | 合并到调度 |

### 2.3 Scheduler 拆分

**问题**：342 行，10+ 个 job 函数都是重复的 try/except/log 模板。

**方案**：提取 job registry 模式 + 通用 wrapper。

```
src/
├── scheduler.py             # 瘦启动器：注册 jobs + start (~80 行)
├── jobs/
│   ├── __init__.py          # job_registry + run_job wrapper
│   ├── collectors.py        # run_collectors()
│   ├── analysis.py          # run_analysis() + insights + governor batch
│   ├── maintenance.py       # debt_scan, debt_resolve, health, voice_refresh
│   └── periodic.py          # profile, performance, skill_evolution, policy, weekly_audit
```

**通用 wrapper**：
```python
# jobs/__init__.py
def run_job(name: str, fn: Callable, db_path: str = DB_PATH):
    """统一的 job 执行 wrapper：日志 + 异常捕获 + 耗时统计。"""
    db = EventsDB(db_path)
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

**scheduler.py 瘦身后**：
```python
def start():
    db = EventsDB(DB_PATH)
    scheduler = BlockingScheduler()

    scheduler.add_job(lambda: run_job("collectors", run_collectors), "interval", hours=1)
    scheduler.add_job(lambda: run_job("analysis", run_analysis), "interval", hours=6)
    # ... 声明式注册，每行一个 job

    # Channel 层启动
    start_channels(db)

    scheduler.start()
```

### 2.4 Import 路径更新

一步到位更新所有消费方。受影响的文件清单：

**核心消费方**（必须更新）：
- `src/scheduler.py` — import governor, debt_scanner, debt_resolver, etc.
- `src/gateway/handlers.py` — import governor
- `src/channels/chat.py` — import governor
- `src/channels/inbound.py` — import governor
- `src/governance/governor_cli.py` — import governor

**分析层**（import prompts）：
- `src/analysis/analyst.py` — `from src.governance.prompts import load_prompt`
- `src/analysis/insights.py` — `from src.governance.prompts import load_prompt`
- `src/analysis/profile_analyst.py` — `from src.governance.prompts import load_prompt`

**测试文件**（必须更新）：
- `tests/test_agent.py`
- `tests/test_analyst.py`
- `tests/test_governor_async.py`
- `tests/test_governor_router.py`
- `tests/test_debt_scanner_router.py`
- `tests/gateway/test_dispatcher.py`
- `tests/gateway/test_intent.py`

**governance 内部互相引用**（最多）：
- 所有 37 个 governance 文件的 `from src.governance.xxx` 需要改成 `from src.governance.subpkg.xxx`

---

## 3. 可拆卸原则（Pluggable Modules）

每个子包都必须是**可拆卸的**——删掉一个子包，系统应该降级运行而不是崩溃。

### 3.1 接口约定

每个子包在 `__init__.py` 中导出一个统一入口函数或类，不需要调用方知道子包内部结构：

```python
# governance/budget/__init__.py
from .token_budget import TokenAccountant, get_accountant

# governance/safety/__init__.py
from .doom_loop import check_doom_loop
from .immutable_constraints import enforce_tool_constraint, enforce_timeout_constraint
from .verify_gate import run_gates, save_gate_record
from .agent_semaphore import AgentSemaphore
```

### 3.2 优雅降级模式

所有子包引用都通过 try/import 做 graceful fallback：

```python
# executor.py 中引用 safety 子包
try:
    from src.governance.safety.doom_loop import check_doom_loop
except ImportError:
    def check_doom_loop(*a, **kw):
        return type('R', (), {'triggered': False, 'reason': ''})()
```

**哪些子包是可选的（删掉不影响核心流程）：**
- `learning/` — 学习和债务扫描，纯增强
- `audit/` — 日志和追踪，删掉只是没记录
- `policy/prompt_canary.py` — 金丝雀部署，可选
- `pipeline/fan_out.py` — 多路输出，可选

**哪些子包是必须的（删掉会断流程）：**
- `budget/` — 预算控制，但可以 fallback 为"无限预算"
- `safety/immutable_constraints.py` — 宪法约束，不可降级
- `policy/blueprint.py` — 蓝图加载，核心路由依赖
- `context/prompts.py` — prompt 模板，执行必需

### 3.3 依赖方向图

```
Governor (协调器, 唯一粘合点)
  │
  ├─→ Dispatcher (调度, 返回 task_id 列表)
  │     ├── Scrutinizer (审查)
  │     │     ├── context/prompts        [必须, 直接 import]
  │     │     ├── policy/blueprint       [必须, 直接 import]
  │     │     └── policy/novelty_policy  [可选, try/import]
  │     ├── safety/agent_semaphore       [可选, try/import, fallback=无限制]
  │     └── policy/deterministic_resolver [可选, try/import, fallback=放行]
  │
  ├─→ Executor (执行, Governor 驱动调用)
  │     ├── context/prompts              [必须, 直接 import]
  │     ├── policy/blueprint             [必须, 直接 import]
  │     ├── safety/immutable_constraints [必须, 直接 import]
  │     ├── budget/token_budget          [可选, try/import, fallback=不降级]
  │     ├── safety/doom_loop             [可选, try/import, fallback=不检测]
  │     ├── audit/heartbeat              [可选, try/import]
  │     └── audit/punch_clock            [可选, try/import]
  │
  └─→ ReviewManager (评审, Executor.finalize 调用)
        ├── pipeline/eval_loop           [必须, 直接 import]
        ├── pipeline/scratchpad          [可选, try/import]
        ├── pipeline/fan_out             [可选, try/import]
        ├── audit/run_logger             [可选, try/import]
        ├── audit/outcome_tracker        [可选, try/import]
        └── policy/tiered_review         [可选, try/import, fallback=默认配置]

Dispatcher ✕ Executor: 互不知道对方存在
ReviewManager → Executor: 通过 on_execute 回调, 不直接 import
```

### 3.4 测试隔离

每个子包有独立的测试文件，mock 掉外部依赖即可单独测试：

```
tests/governance/
├── test_scrutiny.py
├── test_dispatcher.py
├── test_executor.py
├── test_review.py
├── budget/
│   └── test_token_budget.py
├── safety/
│   └── test_doom_loop.py
...
```

---

## 4. 代码质量红线

### 4.1 不写胶水代码
- 子包的 `__init__.py` 只做 re-export（`from .xxx import YYY`），不写逻辑
- Governor 的 facade 方法只是一行调用转发，不做参数转换、不加日志、不 catch 异常
- 如果发现需要"适配层"把 A 的输出转成 B 的输入，说明接口设计有问题——修接口，不写 adapter

### 4.2 不过度设计
- 不加 ABC 抽象基类——Scrutinizer、Dispatcher、Executor、ReviewManager 都是具体类，不需要 interface
- 不加 plugin registry / hook system——这是重构，不是框架化
- 不加 config 驱动的动态加载——import 就够了
- 子包的 `__init__.py` 不搞 `__all__` 或 lazy import 魔法

### 4.3 不做安全剧场
- try/import fallback 只用于真正可选的模块（learning/、audit/、fan_out）
- 必须模块（immutable_constraints、prompts、blueprint）直接 import，失败就 crash——比静默降级更安全
- 不给每个函数加 `try/except: pass`——错误要暴露，不要吞掉

---

## 5. 不做的事（Scope Fence）

- **不改 gateway/ 结构** — 6 个文件，结构已经合理
- **不改 collectors/ 结构** — 已有 base + registry 模式
- **不改 channels/ 结构** — 刚重构过，子包已清晰
- **不改 analysis/ 结构** — 5 个文件，不需要子包
- **不改 storage/ 和 core/** — 没有问题
- **不改任何业务逻辑** — 纯结构重组，行为不变
- **不加新功能** — 这是重构，不是 feature

---

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 循环 import | 依赖方向严格单向：Governor → Dispatcher/Executor → 子包。ReviewManager 通过注入获取 Executor 引用 |
| 遗漏消费方 | grep 全量搜索 `from src.governance` 确保无遗漏 |
| 测试回归 | 每拆一个子包跑一次 `pytest`，不攒到最后 |
| IDE 缓存 | `__pycache__` 清理 + 重启 LSP |

---

## 7. 实施顺序

**Phase 1**：创建子包目录 + 移动叶子文件（不含 governor.py）+ 更新叶子文件的 import 路径
**Phase 2**：拆 governor.py → scrutiny + dispatcher + executor + review + 瘦 governor，同步更新所有外部消费方 import
**Phase 3**：拆 scheduler.py → jobs/ + 瘦 scheduler
**Phase 4**：跑全量测试 + 清理旧文件 + 删 `__pycache__`

每个 Phase 完成后验证测试通过再进下一步。合并了原来的 Phase 2/3 避免 governor 相关 import 更新两遍。
