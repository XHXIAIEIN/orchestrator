# Round 8 Deep Audit: 设计不合理 × 回归风险 × 消费端体验

**Date**: 2026-04-09
**Reviewer**: Orchestrator (Opus 4.6, full codebase cross-reference)
**Method**: 设计文档全文 + 7 轮 review + `grep -rn department src/` 138 处引用逐条比对
**Scope**: 找出 Round 1-7 遗漏的设计缺陷、回归 bug、消费端盲区

---

## Executive Summary

| 类别 | 数量 | 严重度分布 |
|------|------|-----------|
| 设计不合理 | 5 | 2 P0 / 2 P1 / 1 P2 |
| 回归 Bug | 6 | 1 P0 / 3 P1 / 2 P2 |
| 消费端体验 | 4 | 1 P1 / 2 P2 / 1 P3 |

**核心发现**: 设计文档的 "File Changes" 清单严重不完整——只列了 13 个文件的 rewrite，但实际受影响文件至少 **40+**。遗漏的文件集中在三个完全未提及的子系统：**Channel 层**（通知/格式化）、**Storage 层**（run_logs/learnings 表）、**Jobs 层**（向量同步/共享知识）。

---

## I. 设计不合理

### D1. `_REPO_ROOT` 探测逻辑依赖 `departments/` 目录存在 [P0]

**现状**: 代码库中有 **25+ 个文件**用以下模式探测项目根目录：

```python
while _REPO_ROOT != _REPO_ROOT.parent and not (
    (_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()
):
    _REPO_ROOT = _REPO_ROOT.parent
```

**受影响文件**（不完全列表）:
- `src/channels/wake.py`, `src/channels/chat/engine.py`, `src/channels/chat/tools.py`
- `src/jobs/shared_knowledge.py`
- `src/exam/runner.py`, `src/exam/prompt_assembler.py`, `src/exam/dimension_map.py`
- `src/governance/audit/outcome_tracker.py`, `src/governance/context/domain_pack.py`
- `src/governance/context/prompts.py`, `src/governance/context/structured_memory.py`
- `src/governance/context/memory_tier.py`, `src/governance/context/citation.py`
- `src/governance/learning/` 下 5 个文件
- `src/governance/policy/` 下 4 个文件
- `src/governance/pipeline/` 下 3 个文件
- `src/governance/safety/` 下 3 个文件
- `src/governance/signals/cross_dept.py`
- `src/governance/ontology.py`
- `src/governance/registry.py`
- `src/core/event_bus.py`

**设计遗漏**: 迁移计划说 `departments/ → .trash/departments-legacy-20260408/`，但 `.trash/` 不是 `departments/`，`is_dir()` 检查会**全部失败**。所有这些文件在迁移后都找不到项目根目录。

**影响**: **整个系统启动崩溃**。不是某个功能降级，是 import 阶段就 crash。

**修复方案**:
1. 迁移前全局替换 `departments` → `capabilities`（或 `agents`）作为根目录探测标志
2. 或者保留空的 `departments/` 目录（仅含 `.gitkeep`）直到 v2 稳定
3. 或者改用更健壮的探测方式：`pyproject.toml` / `.git` / `CLAUDE.md` 存在性

---

### D2. `run_logs` 和 `learnings` 表的 `department` 字段迁移完全缺失 [P0]

**现状**: 设计文档只提了 `tasks` 表的 SQL 迁移：

```sql
ALTER TABLE tasks ADD COLUMN agent TEXT;
UPDATE tasks SET agent = CASE department ... END;
```

但数据库实际有 **三张表**包含 `department` 字段：

| 表 | department 用途 | 设计文档提及 |
|---|---|---|
| `tasks` | 主路由键 | ✅ 有迁移 SQL |
| `run_logs` | 执行日志按部门分类，有 `idx_run_logs_dept` 索引 | ❌ **完全未提** |
| `learnings` | 经验教训按部门过滤，有 `idx_learnings_dept` 索引 | ❌ **完全未提** |

**受影响的消费端**:
- `_runs_mixin.py`: `append_run_log(department=...)`, `get_recent_run_logs(department=...)`, `get_department_run_stats()` — 全部按 department 查询
- `_learnings_mixin.py`: `add_learning(department=...)`, `get_learnings(department=...)`, `get_learnings_for_dispatch(department=...)` — 全部按 department 过滤
- `token_budget.py`: `TokenUsageRecord.department`, `daily_spent(department)`, `daily_remaining(department)`, `recommend_model(department)` — 预算按 department 计算
- `sync_vectors.py`: 向量同步时 metadata 包含 `department` 字段

**影响**: 迁移后新任务写 `agent` 字段，但 run_logs/learnings 仍写 `department`。查询时 `get_learnings_for_dispatch(department="engineer")` 找不到任何历史数据（因为历史都是 `department="engineering"`）。**经验教训系统静默失效**。

**修复方案**:
```sql
-- run_logs
ALTER TABLE run_logs ADD COLUMN agent TEXT;
UPDATE run_logs SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    WHEN 'quality' THEN 'reviewer'
    WHEN 'security' THEN 'sentinel'
    WHEN 'operations' THEN 'operator'
    WHEN 'personnel' THEN 'analyst'
    WHEN 'protocol' THEN 'inspector'
    ELSE department
END;

-- learnings
ALTER TABLE learnings ADD COLUMN agent TEXT;
UPDATE learnings SET agent = CASE department ... END;  -- 同上
```

加上所有 mixin 方法的参数名/查询字段迁移。

---

### D3. Channel 层完全未出现在迁移计划中 [P1]

**现状**: Channel 子系统有以下 department 依赖：

| 文件 | 依赖点 |
|------|--------|
| `channels/formatter.py` | `DEPT_NAMES = {"engineering": "工部", ...}` — 硬编码中文名映射 |
| `channels/base.py` | `ChannelMessage.department: str` — 数据类字段 |
| `channels/registry.py` | `broadcast_event(department=...)` — 广播接口参数 |
| `channels/chat/tools.py` | `"department": {"type": "string"}` — Telegram bot 工具定义 |
| `channels/chat/commands.py` | `SELECT task_id, department, status` — 查询模板 |

**设计文档 File Changes 清单**: Channel 层的文件**一个都没列**。

**影响**: 迁移后 Telegram bot 显示的部门名全部变成原始英文 key（`engineer` 而非 `工程师`），`/status` 命令查询结果缺少 agent 字段。

**修复**: 在 File Changes 的 Rewrite 列表中添加：
- `src/channels/formatter.py` — `DEPT_NAMES` → `AGENT_NAMES`
- `src/channels/base.py` — `department` → `agent`
- `src/channels/registry.py` — 参数名
- `src/channels/chat/tools.py` — 工具 schema
- `src/channels/chat/commands.py` — SQL 查询

---

### D4. Token Budget 系统的 per-department 计费逻辑未迁移 [P1]

**现状**: `token_budget.py` 实现了按部门的每日预算控制：

```python
BUDGET_DAILY_PER_DEPT_USD = 20  # per-department daily limit

def daily_spent(self, department: str) -> float:
    return sum(r.cost_usd for r in self.state.records
               if r.department == department and r.timestamp[:10] == today)

def recommend_model(self, department: str, preferred_model: str) -> str:
    daily_remaining = self.state.daily_remaining(department)
    if daily_remaining <= 0:
        log.info(f"token_budget: {department} daily budget exhausted, downgrading model")
```

**设计文档**: 完全没提 token budget。

**影响**:
- 新 agent 有 8 个（vs 旧 6 个部门），但预算仍按旧 department 名计算 → 新 agent 名没有预算记录 → `daily_remaining("engineer")` 永远返回满额 → **预算控制失效**
- `architect` 是新角色，没有对应的旧 department → 无法从历史数据推算预算

**修复**: 在设计文档中增加 Token Budget 迁移段落，包括：
1. `TokenUsageRecord.department` → `.agent`
2. 历史记录的 department→agent 映射
3. 8 agent vs 6 department 的预算重新分配策略

---

### D5. `shared_knowledge.py` 直接操作 `departments/shared/` 目录 [P2]

**现状**:

```python
SHARED_DIR = _REPO_ROOT / "departments" / "shared"
# ...
key_dirs = ["src", "departments", "SOUL", "dashboard"]
# ...
"departments/": "六部配置 (SKILL.md, manifest.yaml, guidelines/)",
```

`shared_knowledge.py` 直接写入 `departments/shared/` 目录，并在目录描述中硬编码 "六部配置"。

**设计文档**: 未提及此文件。

**影响**: 迁移后共享知识写入一个不存在的目录。不会崩溃（`mkdir -p` 可能自动创建），但知识更新静默失败。

---

## II. 回归 Bug

### R1. `proactive_jobs.py` 使用 `department="proactive"` — 既不是旧名也不是新名 [P1]

**现状**:
```python
# src/jobs/proactive_jobs.py
department="proactive"
```

这不是任何已知的 department 或 agent 名。在旧系统中可能就是个 bug（或 special case），但新系统的 `KNOWN_TERMINALS` / `VALID_AGENTS` 验证会让它更显眼地失败。

**风险**: 如果新 registry 做 strict validation，`"proactive"` 会被拒绝。

**修复**: 决定 proactive jobs 归属哪个 agent（可能是 `operator` 或 `analyst`），或者在 agent 列表中添加 proactive 作为特殊值。

---

### R2. `periodic.py` 调用 `vet_all_departments()` — 函数名和导入路径都要变 [P1]

**现状**:
```python
from src.governance.audit.skill_vetter import vet_all_departments, risk_summary, RiskLevel
```

**设计文档**: `skill_vetter.py` 不在 File Changes 列表中。

**影响**: import 失败 → 定时任务全部中断。

---

### R3. Semaphore 从 threading.Lock 到 async — 线程安全性断裂 [P1]

**现状**: `agent_semaphore.py` 使用 `threading.Lock`：
```python
self._lock = threading.Lock()
```

**设计方案**: dispatcher pipeline 改为 async：
```python
await semaphore.acquire("reviewer", fact_spec.authority)
```

`threading.Lock` 不能在 async 上下文中安全使用。`await lock.acquire()` 需要 `asyncio.Lock`。但 `asyncio.Lock` 又不能跨线程使用。

**影响**: 如果 Governor 仍在同步线程中调用 semaphore，而 dispatcher 在 async 中调用同一个 semaphore 实例，会出现：
- `threading.Lock` 在 async 中阻塞事件循环
- 或者 `asyncio.Lock` 在同步线程中报错

**修复**: 设计文档需要明确 semaphore 的并发模型——是纯 async、纯 threading、还是混合？如果混合，需要 `asyncio.Lock` + `threading.Lock` 双层封装。

---

### R4. `dept_fsm` 导入在 dispatcher 中 — FSM 模块重命名后断裂 [P0]

**现状**: `dispatcher.py:15`:
```python
from src.governance.department_fsm import fsm as dept_fsm
```

`dispatcher.py:96`:
```python
if department and dept_fsm.is_terminal(department, "approved"):
```

**设计方案**: `department_fsm.py` → 删除（移到 `.trash/`），新建 `agent_fsm.py`。

**影响**: dispatcher 在 Phase 0 就 import crash，整个调度管线瘫痪。

**设计文档虽然列了这个文件改名**，但没有明确 dispatcher.py 中这个 import 需要更新。更关键的是：`dept_fsm.is_terminal()` 和 `dept_fsm.get_next_department()` 的 API 签名要同步改。

---

### R5. Qdrant 向量元数据中 `department` 字段的双写期一致性 [P2]

**现状**: `sync_vectors.py` 在向量同步时写入：
```python
"metadata": {"department": r["department"], "status": r.get("status", "done")}
```

**设计方案**: Qdrant 迁移是批量更新已有记录的 `department` → `agent`。但 `sync_vectors.py` 如果没同步改，新同步的向量仍然只写 `department` 不写 `agent`。

**影响**: 迁移后的双查询期（同时查 `agent` 和 `department`）在新写入的向量上只有 `department`，而那个 `department` 值可能是新 agent 名（`"engineer"`），也可能是旧部门名（`"engineering"`）——取决于调用方传的是什么。数据混乱。

---

### R6. `evolution/actions.py` 有 9 处 department 引用 — 自进化系统断裂 [P2]

**现状**: `actions.py` 有 9 处 department 引用（grep 计数），这是 Orchestrator 的自进化循环。

**设计文档**: 未提及 `src/evolution/` 下任何文件。

**影响**: 进化循环中的 action 匹配和 risk 评估可能引用旧部门名。不会立即崩溃，但进化建议的质量会下降（引用不存在的部门）。

---

## III. 消费端体验走查

### E1. 场景："修 auth.py 的 bug" — 从用户输入到结果的完整链路 [P1]

**当前链路**:
```
用户: "修 auth.py 的 bug"
  → intent.py: parse → {intent: "code_fix", department: "engineering"}
  → routing.py: resolve → PolicyProfile.BALANCED (sonnet, 25 turns)
  → dispatcher: clarify → synthesis → qdrant → ... → scrutiny
  → executor: load engineering/SKILL.md → build prompt → run
  → review: quality dept review → done
```

**新链路**:
```
用户: "修 auth.py 的 bug"
  → intent.py: parse → {intent: "code_fix", agent: "engineer"}
  → routing.py: resolve → PolicyProfile.BALANCED
  → dispatcher: ... → composer.compose("engineer", intent="code_fix")
  → composed: develop.prompt + test.prompt (权重排序), model=sonnet, authority=MUTATE
  → executor: run with composed spec
  → FSM: done → @reviewer
  → reviewer runs: review.prompt + discipline.prompt
```

**回归风险点**:

| 步骤 | 风险 | 严重度 |
|------|------|--------|
| Prompt 组装 | 旧 SKILL.md 是单一连贯文档（~2000 tokens），新方案是 develop.prompt + develop/implement/prompt.md + test.prompt 拼接。**LLM 注意力分布改变**，可能丢失 SKILL.md 中精心调优的跨章节引用 | HIGH |
| 后续 Review | 旧：整个 quality 部门 SKILL.md（含完整 review 方法论）。新：review.prompt(70%) + discipline.prompt(30%) 拼接。权重配比是拍脑袋的，没有 A/B 数据 | MEDIUM |
| Token 消耗 | 多 prompt 片段 + section headers + authority context line → token 膨胀约 15-25%。对 LOW_LATENCY 任务尤其敏感 | MEDIUM |
| learnings 注入 | `get_learnings_for_dispatch(department="engineer")` — 历史全是 `department="engineering"` → **静默返回空列表** → agent 丧失所有历史经验 | CRITICAL |

**最后一点是最致命的**: 迁移后 agent 派出去干活，但完全没有历史经验加持。相当于一个有 45 轮偷师经验的老员工，一夜之间失忆了。用户感知："重构后系统变笨了。"

---

### E2. 场景："帮我做日报" — Fact-Expression Split 路径 [P2]

**当前链路**:
```
intent: "report" (in _SPLIT_INTENTS)
  → Phase 1: route to quality dept (fact layer)
  → Phase 2: route to protocol dept (expression layer)
```

**新链路**:
```
intent: "report" (in _SPLIT_INTENTS)
  → Phase 0.5a: compose("reviewer", intent_override="fact_layer")
  → Phase 0.5b: compose("inspector", intent_override="expression_layer")
```

**问题**: `intent_override="fact_layer"` 在 reviewer 的 intents 中**没有定义**。设计文档中 reviewer 的 intents 只有 `code_review` 类的。`fact_layer` 是 dispatcher 内部概念，不是 agent manifest 中的 intent。

**影响**: `compose("reviewer", intent="fact_layer")` 找不到 intent → fallback 到默认 intent → fact layer 用的是 code_review 的 active_capabilities 和 profile → **日报的 fact 层用代码审查的配置去跑**。

**修复**: 在 reviewer 和 inspector 的 agent.yaml 中显式定义 `fact_layer` / `expression_layer` 作为 intent。

---

### E3. 场景："查看系统状态" via Telegram bot [P2]

**当前链路**:
```
/status command
  → chat/commands.py: SELECT task_id, department, status, summary FROM tasks
  → 显示: [工部] 修复 auth.py — 完成
```

**新链路**:
```
/status command
  → chat/commands.py: SELECT task_id, department, status, summary FROM tasks
  → department 列仍有值（旧数据），但 agent 列可能为空（新数据写 agent 不写 department）
  → 显示: [] 修复 auth.py — 完成  （空白部门名）
```

`DEPT_NAMES` 映射不认识新 agent 名 → `DEPT_NAMES.get("engineer", "engineer")` → 显示原始英文 "engineer" 而非中文名。

**用户感知**: Telegram 通知从有中文名的专业感变成英文 raw key 的毛坯感。小事，但影响日常体验。

---

### E4. 场景："这个月花了多少钱？" — Token Budget 查询 [P3]

```python
def get_budget_status(self):
    depts = set(r.department for r in self.state.records)
    # 返回每个 dept 的花费统计
```

迁移后新记录的 `department` 字段可能是空的（如果代码改为写 `agent` 字段而不写 `department`）。预算统计会出现一个神秘的空字符串分类，旧部门的花费停止增长，新 agent 的花费无处归类。

---

## IV. 设计文档 File Changes 遗漏清单

设计文档 "File Changes" 节列了 13 个 Rewrite 文件。以下是**遗漏的需要修改的文件**（按子系统分组）：

### Storage 层 (6 files)
| 文件 | 修改点 |
|------|--------|
| `src/storage/_schema.py` | `run_logs.department`, `learnings.department` 列 + 索引 |
| `src/storage/_runs_mixin.py` | 所有方法参数名 + SQL 查询（20 处引用） |
| `src/storage/_learnings_mixin.py` | 所有方法参数名 + SQL 查询（15 处引用） |
| `src/governance/budget/token_budget.py` | `TokenUsageRecord.department`, 所有预算方法（15 处引用）|
| `src/jobs/sync_vectors.py` | 向量 metadata 字段（5 处引用）|
| `src/jobs/shared_knowledge.py` | `departments/shared/` 路径 + 目录描述（11 处引用）|

### Channel 层 (5 files)
| 文件 | 修改点 |
|------|--------|
| `src/channels/formatter.py` | `DEPT_NAMES` → `AGENT_NAMES`（3 处）|
| `src/channels/base.py` | `ChannelMessage.department` 字段 |
| `src/channels/registry.py` | `broadcast_event(department=...)` 参数 |
| `src/channels/chat/tools.py` | 工具 schema + SQL 查询（5 处）|
| `src/channels/chat/commands.py` | SQL 查询模板 |

### Jobs 层 (3 files)
| 文件 | 修改点 |
|------|--------|
| `src/jobs/proactive_jobs.py` | `department="proactive"` 特殊值 |
| `src/jobs/periodic.py` | `vet_all_departments` import + 函数调用 |
| `src/governance/audit/skill_vetter.py` | `vet_all_departments()` 函数签名 |

### Evolution 层 (3 files)
| 文件 | 修改点 |
|------|--------|
| `src/evolution/actions.py` | 9 处 department 引用 |
| `src/evolution/risk.py` | 1 处 department 引用 |
| `src/evolution/loop.py` | 2 处 department 引用 |

### Root Detection (25+ files)
| 模式 | 修改点 |
|------|--------|
| `(_REPO_ROOT / "departments").is_dir()` | 25+ 个文件的项目根目录探测 |

### Other (5+ files)
| 文件 | 修改点 |
|------|--------|
| `src/core/health.py` | 3 处 department 引用 |
| `src/core/event_bus.py` | 2 处 + 根目录探测 |
| `src/core/multi_budget.py` | 2 处 department 引用 |
| `src/core/browser_runtime.py` | 8 处 department 引用 |
| `src/analysis/performance.py` | 3 处 department 引用 |
| `src/analysis/insights.py` | 1 处 department 引用 |

**总计**: 设计文档列了 ~13 文件，实际需要修改 **~40+ 文件**。遗漏率约 **67%**。

---

## V. 综合严重度排序

| # | Issue | 类型 | 严重度 | Round 1-7 覆盖 |
|---|-------|------|--------|---------------|
| D1 | `departments/` 目录删除导致 25+ 文件根目录探测失败 | 设计缺陷 | **P0** | ❌ 从未提及 |
| D2 | `run_logs` + `learnings` 表迁移缺失 | 设计缺陷 | **P0** | ❌ 从未提及 |
| R4 | `department_fsm` 重命名后 dispatcher import crash | 回归 Bug | **P0** | ⚠️ 间接提及但没列入迁移步骤 |
| D3 | Channel 层 5 个文件完全未列入迁移 | 设计缺陷 | **P1** | ❌ 从未提及 |
| D4 | Token Budget 按部门计费逻辑未迁移 | 设计缺陷 | **P1** | ❌ 从未提及 |
| E1 | learnings 注入静默失效（新名查旧数据=空） | 消费端 | **P1** | ❌ 从未提及 |
| R1 | `department="proactive"` 非法值 | 回归 Bug | **P1** | ❌ |
| R2 | `vet_all_departments` import 断裂 | 回归 Bug | **P1** | ❌ |
| R3 | Semaphore threading.Lock vs async 冲突 | 回归 Bug | **P1** | ❌ |
| E2 | Fact-Expression Split 的 intent_override 无定义 | 消费端 | **P2** | ❌ |
| E3 | Telegram bot 显示 raw agent key | 消费端 | **P2** | ❌ |
| D5 | `departments/shared/` 写入路径失效 | 设计缺陷 | **P2** | ❌ |
| R5 | Qdrant 双写期新旧字段名混乱 | 回归 Bug | **P2** | ⚠️ 部分覆盖 |
| R6 | evolution 子系统 department 引用未迁移 | 回归 Bug | **P2** | ❌ |
| E4 | Token Budget 统计出现空分类 | 消费端 | **P3** | ❌ |

---

## VI. 建议

### 实施前必须完成

1. **根目录探测模式全局替换** — 用 `pyproject.toml` 或 `.git` 存在性替代 `departments/` 探测，或在迁移期保留空 `departments/` 目录
2. **补全 SQL 迁移** — `run_logs` + `learnings` 表的 `agent` 字段 + 数据迁移 + 索引
3. **补全 File Changes 清单** — 把上面列出的 40+ 文件全部加入，按子系统分组
4. **learnings 双查询** — 迁移期 `get_learnings_for_dispatch` 同时查 `agent` 和 `department` 字段（同 tasks 表策略）
5. **定义 fact_layer / expression_layer intent** — 在 reviewer 和 inspector 的 agent.yaml 中显式声明

### 实施中关注

6. Channel 层 `AGENT_NAMES` 映射（中文名 + 表情符号）
7. Token Budget 的 agent 维度重新初始化
8. Semaphore 并发模型决定（sync / async / hybrid）
9. `shared_knowledge.py` 路径从 `departments/shared/` → `capabilities/shared/` 或 `data/shared/`
10. Evolution 子系统的 department 引用清理

### 设计文档修订建议

- 在 "File Changes" 之前增加 **"Impact Radius"** 节：`grep -rn department src/ | wc -l` = 138 处，涉及 30+ 文件
- 在 "Data Migration" 节增加 `run_logs` + `learnings` + `token_budget` 的迁移 SQL
- 在 "Migration Steps" 中增加 Step 0c：**根目录探测模式迁移**（在任何文件重命名之前）
- 在 "Hardcoded Reference Scan" 中把 scan 命令的输出实际跑一遍，把结果贴进去而不是只贴命令
