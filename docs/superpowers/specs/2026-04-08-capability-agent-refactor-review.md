# Capability + Agent Refactor — Design Review

**Date**: 2026-04-08
**Reviewer**: Orchestrator (self-review)
**Target**: `2026-04-08-capability-agent-refactor-design.md`
**Verdict**: P0/P1 issues must be resolved before implementation plan

---

## 一、设计层面的不合理之处

### 1. `compress` 是幽灵能力原子 — 14 个 capability 中有 1 个无人认领

14 个 capability 中，`compress` 没有出现在任何一个 agent 的 `capabilities` 列表里：

| Agent | Capabilities |
|-------|-------------|
| engineer | develop, test |
| architect | plan, refactor |
| reviewer | review |
| sentinel | audit, guard |
| operator | operate, collect |
| analyst | monitor, verify |
| inspector | inspect, express |
| verifier | verify, test |

`compress` 是个孤儿。如果没人用，它就不该出现在设计里。如果它是为 ad-hoc 模式预留的，文档应该说明。

---

### 2. `test` 能力标记为 READ，但 "运行测试" 需要执行副作用

`test` capability: `authority: READ, model: sonnet`。但它的定义是 "Run tests, verify coverage" — 运行 pytest/npm test 是实打实的 shell 执行，会产生临时文件、coverage 报告等。

- `verifier` = verify(READ) + test(READ) = READ
- `engineer` = develop(MUTATE) + test(READ) = MUTATE

当 verifier 执行端到端验证，需要 `pytest` 运行测试时，READ 权限能让它跑吗？当前系统里 quality 部门是 READ 的，它确实只做代码审查不跑测试。测试执行在 engineering（MUTATE）。

**问题**：如果 verifier 只能 READ，它的 `test` capability 就是摆设 — 它能看测试文件，但不能运行。这等于把 "验证者" 阉割成了 "观察者"。

---

### 3. Authority merge = max 会产生非预期的权限膨胀

Compose 策略：`authority = max(all capabilities)`。

**场景**：architect = plan(READ) + refactor(MUTATE) → **MUTATE**

用户说 "帮我规划 auth 重构方案"。IntentGateway 路由到 architect。Composer 组合后给了 MUTATE 权限。一个纯规划任务拿到了文件写权限。

**更危险的 ad-hoc 场景**：`compose(capabilities=["review", "develop"])` → READ merge MUTATE = **MUTATE**。用户可能只想 "边看边写"，但 develop 的 MUTATE 悄悄升级了整个组合的权限。

**修复建议**：Authority 应该由 agent 显式声明（override），不是从 capability 盲目 max。或者引入 intent-level authority cap。

---

### 4. Rubric 加权合并 1/N 太粗暴

engineer 组合 develop + test，rubric 各占 50%。但 develop 是主任务，test 是辅助验证。一个 bug fix 任务，50% 的评分权重给了测试覆盖率？这会导致：
- 一个完美修复 + 没跑测试 = 50 分
- 一个敷衍修复 + 完美测试 = 50 分

应该允许 agent 声明 capability 权重：
```yaml
capabilities:
  - key: develop
    weight: 0.7
  - key: test
    weight: 0.3
```

---

### 5. FSM 表达力严重退化

当前 `department_fsm.py` 有 10+ 转移规则，包括：
- 通配符：`("*", "fact_layer") → quality`
- 多触发器：`quality_review`, `rework`, `fact_layer`, `expression_layer`, `escalation`, `retry`
- 自重试：`("*", "retry") → __self__`

新 FSM 每个 agent 只有 3 个字段：`on_done`, `on_fail`, `on_rework`。

**丢失的语义**：

| 当前 FSM | 新 FSM 能表达？ |
|----------|---------------|
| `("*", "fact_layer") → quality` | 不能 — 无通配符 |
| `("quality", "expression_layer") → protocol` | 不能 — 没有 `on_expression` 字段 |
| `("*", "retry") → __self__` | 不能 — 自重试无处声明 |
| `("*", "escalation") → ""` | 不能 — 没有 escalation 触发 |

三个字段不够。要么扩展为 `transitions` map：
```yaml
transitions:
  done: quality_review
  fail: log_only
  rework: engineer
  fact_layer: reviewer
  expression_layer: inspector
  retry: __self__
```
要么保留一个全局 transition override 文件。

---

### 6. Fact-Expression Split 在新架构中断裂

当前实现：
1. `_needs_fact_expression_split()` → 触发
2. Fact phase: route to `quality` department（中立事实）
3. Expression phase: route to `protocol` department（语气改写）
4. FSM: `("*", "fact_layer") → quality`, `("quality", "expression_layer") → protocol`

新架构映射：
- quality → reviewer（但 reviewer 只有 `review`，没有 `guard`/anti-sycophancy）
- protocol → inspector（inspect + express）

**问题**：anti-sycophancy 逻辑是 `guard` capability 的职责，而 `guard` 被分给了 `sentinel`。Reviewer 没有 guard。所以：
- Fact layer 需要 anti-sycophancy → sentinel 有，reviewer 没有
- 设计说 "Anti-sycophancy → guard capability"，但 guard 跟着 sentinel 走了
- reviewer 执行 fact layer 时缺少 anti-sycophancy 保护

这是功能丢失。

---

### 7. sentinel 用 haiku 做安全审计是降级

当前 security 部门在 routing.py 的 BALANCED profile 下用 **sonnet**。

新设计：sentinel = audit(haiku) + guard(haiku) → model: max(haiku, haiku) = **haiku**。

拿 haiku 做全仓库安全审计？CVE 扫描、权限检查、注入检测 — 这些任务需要深度推理。Haiku 的推理能力不足以发现复杂的安全漏洞。

Override Stack 可以在 L1 层覆盖 model，但文档里 sentinel 的 agent YAML 没有展示 model override。如果依赖 intent profile 来救场（BALANCED → sonnet），那 capability 里标的 haiku 就是误导。

---

### 8. Ad-hoc 模式 "无身份" 是危险的

> Ad-hoc mode has no identity prompt.

当前系统每个任务都有 department identity（来自 manifest.yaml 的 identity 字段 + SKILL.md）。身份不是装饰 — 它约束了 LLM 的行为边界：
- "你是安全审计员，只报告漏洞，不修改代码"
- "你是运维工程师，先诊断再修复"

没有身份的 ad-hoc 组合就是一袋散装指令。`compose(capabilities=["develop", "audit"])` 会产出什么？一个既想写代码又想扫漏洞的精分 agent。LLM 没有角色锚定，行为不可预测。

**修复建议**：ad-hoc 模式应该生成一个合成身份（基于 capability 组合），或者强制要求选择一个 agent。

---

### 9. `verify` 重复分配导致路由歧义

- verifier: verify, test
- analyst: monitor, **verify**

两个 agent 都有 verify。当 IntentGateway 解析出 "verify the deployment" 时，AGENT_TAGS 里两个 agent 都会匹配 verify 标签。

Tag-based routing 没有消歧规则。当前系统每个 intent 唯一映射到一个 department，不存在这个问题。

---

## 二、回归风险与潜在 Bug

### Bug 1：数据库 schema 断裂 — 沉默的数据丢失

EventsDB 存储的每条 task 记录都有 `department` 字段（值：engineering, quality 等）。重构后字段名变 `agent`，值变 engineer, reviewer 等。

- 历史数据查询：`SELECT * FROM tasks WHERE department = 'engineering'` → 0 条结果
- Qdrant 向量也带 department metadata → 语义搜索的 filter 失效
- Novelty policy 用历史失败记录判断是否重试 → 找不到旧记录，误判为 "新任务"
- Learnings injection 按 department 过滤经验 → 旧经验全部丢失

**文档完全没提数据迁移**。这不是 "clean cut" 能解决的。

---

### Bug 2：`_COLLABORATION_PATTERNS` 硬编码中文部门名

```python
_COLLABORATION_PATTERNS = {
    r"需要工程部|需要engineering|工程部配合": "engineering",
    r"需要运维|需要operations|运维配合": "operations",
    ...
}
```

重构后 agent key 变成 engineer, operator 等。LLM 输出里如果仍然说 "需要工程部"，regex 匹配到的 value "engineering" 不再是有效的 agent key → 协作检测全部静默失败。

---

### Bug 3：`_DEPT_SPECIFIC_FIELDS` in task_handoff.py

```python
_DEPT_SPECIFIC_FIELDS = {
    "engineering": {"code_diff", "file_list", ...},
    "operations": {"docker_logs", ...},
    ...
}
```

Handoff context filtering 依赖 department name → field set 映射。Key 变了，`filter_context()` 找不到匹配项，所有 context 字段都会被当作 "不属于任何部门" 而被过滤掉。结果：handoff 时下游 agent 收到空的 context。

---

### Bug 4：Semaphore 硬编码部门分类

```python
MUTATE_DEPARTMENTS = {"engineering", "operations"}
READ_DEPARTMENTS = {"protocol", "security", "quality", "personnel"}
```

新系统如果改为按 authority 动态分类（`if agent.authority == "MUTATE"`），那 architect（plan=READ + refactor=MUTATE → MUTATE）会被归入 MUTATE 组，和 engineer/operator 争抢 2 个槽位。

当前系统只有 engineering + operations 是 MUTATE（2 个部门）。新系统有 engineer + architect + operator = **3 个 MUTATE agent**，但 mutate_max 仍然是 2。这意味着 3 个中只能同时跑 2 个，第三个永远排队。

---

### Bug 5：CapabilityRegistry 命名冲突

已有 `src/governance/capability_registry.py`，定义的 `CapabilityRegistry` 类映射 abstract capabilities（如 `file_read`, `code_edit`）到 tools。

新设计的 `capabilities/` 目录定义的 capability 是 functional atoms（如 `develop`, `review`）。

两个 "capability" 概念在同一个代码库里共存：
- 旧的 `CapabilityRegistry`：tool-level capability mapping（保留？替换？）
- 新的 `capabilities/`：agent-level functional atoms

文档没说旧 `CapabilityRegistry` 的去留。如果保留，代码里会有两种 capability 语义；如果替换，当前引用旧 registry 的所有代码都要改。

---

### Bug 6：`build_fsm_from_agents` 的 `resolve_trigger` 未定义

```python
target = resolve_trigger(agent.on_done, agents)
```

`on_done: quality_review` — 这是一个 trigger name，不是 agent key。`resolve_trigger` 需要把 trigger name 映射到 agent key。怎么映射？

文档说 "system finds agent with review capability"。所以是 capability-based reverse lookup。但：
- `quality_review` 这个 trigger 里包含 "review" → 找到 reviewer agent？
- 这是字符串匹配还是语义匹配？
- 如果有两个 agent 都有 review capability 怎么办？

这个函数的行为没有被定义，是设计文档里最大的悬念之一。

---

### Bug 7：Pipeline 异步化的错误处理缺陷

```python
results = await asyncio.gather(*workers.values())
if failed(results['clarify']) or failed(results['synthesis']):
    return REJECTED
```

`asyncio.gather(*workers.values())` 返回的是一个 list，不是 dict。`results['clarify']` 会 KeyError。需要改为 `asyncio.gather(**workers)` 或用 `TaskGroup` + 命名。

另外，`cancel_all_if_failed` callback 在 gate 失败时取消所有 worker，但 `asyncio.gather` 默认 `return_exceptions=False` — 如果被取消的 task 抛出 `CancelledError`，`gather` 自己也会异常，`failed()` 检查永远到不了。

---

## 三、消费端体验走查

### 场景 A："修一下 auth.py 的登录 bug"

| 步骤 | 当前系统 | 新系统 | 差异 |
|------|---------|--------|------|
| 1. 意图解析 | → engineering, code_fix | → engineer, code_fix | OK |
| 2. Pipeline | 10 步串行, ~22s | 3 phase async, ~7s | 体验提升 |
| 3. Prompt 组合 | engineering SKILL.md（完整、调教过的） | develop.prompt + test.prompt 拼接 | **降级风险** |
| 4. 执行 | sonnet, MUTATE, 25 turns | sonnet, MUTATE, 25 turns | 相同 |
| 5. 质量审查 | FSM → quality dept | on_done: quality_review → reviewer | **reviewer 缺 guard（anti-sycophancy）** |
| 6. 结果 | 两轮完成 | 两轮完成 | 流程等价 |

**体验痛点**：
- Step 3 的 prompt 从精心编写的 SKILL.md 变成两段 prompt.md 拼接。当前 SKILL.md 是经过多轮调教的完整指令，拼接版质量很可能下降。
- Step 5 reviewer 缺少 anti-sycophancy 保护，可能出现 "looks good to me" 的橡皮图章审查。

---

### 场景 B："全量安全审计"

| 步骤 | 当前系统 | 新系统 | 差异 |
|------|---------|--------|------|
| 1. 意图解析 | → security | → sentinel | OK |
| 2. 模型选择 | BALANCED profile → sonnet | audit(haiku) + guard(haiku) → **haiku** | **严重降级** |
| 3. 执行 | sonnet 深度推理 | haiku 快速扫描 | 漏检风险 |
| 4. 审查 | FSM → quality | sentinel.on_done → ??? | 未定义 |

**体验痛点**：模型从 sonnet 降到 haiku，安全审计质量断崖式下降。用户不会知道底层模型变了，但会感知到 "以前能发现的问题现在找不到了"。

---

### 场景 C："帮我做个重构计划"

| 步骤 | 当前系统 | 新系统 | 差异 |
|------|---------|--------|------|
| 1. 路由 | → engineering | → architect | 更精准 |
| 2. 权限 | MUTATE（engineering 固有） | plan(READ) + refactor(MUTATE) → **MUTATE** | 不必要的升级 |
| 3. 模型 | sonnet | opus | **成本升级** |
| 4. 执行 | 做计划，不碰代码 | 有 MUTATE 权限 + refactor prompt，可能直接开始重构 | **行为漂移风险** |

**体验痛点**：用户想要一份计划，architect 拿到了 MUTATE 权限和 refactor.prompt。如果 refactor.prompt 里有 "执行结构性重构" 的指令，LLM 可能在 "做计划" 的过程中就开始动代码了。

---

### 场景 D：ad-hoc 组合 — "审查这段代码并修掉问题"

这个请求需要 review + develop。

| 步骤 | 问题 |
|------|------|
| 1. 解析 | `capabilities=["review", "develop"]` |
| 2. Set-cover | review → reviewer, develop → engineer → 两个 agent？还是找一个覆盖两者的？ |
| 3. 身份 | ad-hoc 模式无 identity prompt |
| 4. 权限 | READ(review) + MUTATE(develop) → MUTATE |

没有 agent 同时拥有 review + develop。Greedy set-cover 会选 engineer（develop, test）+ reviewer（review）= 两个 agent。但文档说 ad-hoc 模式产出的是**一个** ComposedSpec，不是多个 agent。

所以要么：
- 把两个 agent 的 capability 并入一个 spec（但没有 identity — 谁说了算？）
- 拒绝这个组合（用户体验差）
- 自动选最近的单 agent（但没有完全覆盖）

set-cover 解析到多 agent 时的行为是**未定义**的。

---

## 四、严重度汇总

| 级别 | 问题 | 影响 |
|------|------|------|
| **P0 - 功能断裂** | DB 无迁移方案，历史数据全部断链 | 旧任务/经验/学习全部丢失 |
| **P0 - 功能断裂** | FSM 表达力退化（3 字段 vs 10+ 转移） | Fact-Expression Split、自重试、通配符全部丢失 |
| **P0 - 功能断裂** | Fact-Expression Split 的 anti-sycophancy 脱落 | 审查质量下降，橡皮图章风险 |
| **P1 - 质量回归** | sentinel 用 haiku 做安全审计 | 安全检测能力断崖 |
| **P1 - 质量回归** | Authority max 导致权限膨胀（architect MUTATE） | 规划任务拿到写权限 |
| **P1 - 静默失败** | collaboration patterns / handoff fields / semaphore 硬编码 | 协作检测、context 过滤、并发控制静默失效 |
| **P2 - 设计缺陷** | `compress` 无人认领、`verify` 重复分配 | 能力图不干净 |
| **P2 - 设计缺陷** | ad-hoc 模式无 identity + set-cover 未定义 | 行为不可预测 |
| **P2 - 设计缺陷** | Rubric 1/N 加权太粗 | 评分不反映主次 |
| **P2 - 代码 Bug** | asyncio.gather 返回 list 不是 dict | Pipeline 运行时崩溃 |
| **P3 - 命名冲突** | 新旧 CapabilityRegistry 语义重叠 | 代码可读性混乱 |

---

## 五、建议

在进入实施计划前修复 P0 和 P1 级问题。P2 可以在实施中迭代，P3 在收尾时处理。
