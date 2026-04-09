# Capability + Agent Refactor — Deep Analysis

**Date**: 2026-04-08
**Analyst**: Orchestrator (deep review, post-P0/P1 resolution)
**Target**: `2026-04-08-capability-agent-refactor-design.md`
**Verdict**: Design 声称已修复 review 的 P0/P1，但仍有 1 个 P0 + 4 个 P1 未覆盖

---

## 一、设计层面的结构性问题

### 1. Divisions（二十四司）整体蒸发 — P0，Review 未提及

当前系统每个 department 有 2-4 个 divisions，总共约 20 个子专业化单元：

```
engineering/divisions/: implement, scaffold, integrate, orchestrate
quality/divisions/: review, detect, compare, gate
operations/divisions/: operate, budget, collect, store
protocol/divisions/: interpret, calibrate, communicate, polish
personnel/divisions/: analyze, recall, evaluate, chronicle
```

每个 division 有独立的 `prompt.md`、`exam.md`、`exam_cases.jsonl`。这是**精调过的子专业指令和考核题库**。

新设计里 capability 只有一层 `prompt.md`，没有 division 概念。这意味着：
- `engineering/divisions/implement/prompt.md` vs `engineering/divisions/scaffold/prompt.md` 的差异化指令全部丢失
- Division 级别的 exam 考核体系没有去处
- 当前系统的任务可以路由到 division 级别，新系统只能到 capability 级别——粒度反而变粗了

**这不是 "历史包袱"，这是 45 轮偷师沉淀的知识资产。**

### 2. Manifest 字段大面积丢失 — P1，Review 未提及

对比当前 manifest.yaml 和新 capability manifest.yaml + agent.yaml：

| 当前 manifest 字段 | 新架构去处 | 状态 |
|---|---|---|
| `dimensions` (primary/secondary/boost) | 无 | **丢失** |
| `policy.allowed_tools` / `denied_tools` | manifest.yaml `tools` | 部分保留 |
| `policy.writable_paths` / `denied_paths` | manifest.yaml `paths` | 保留 |
| `policy.can_commit` / `can_network` | ComposedSpec | 保留 |
| `policy.read_only` / `max_file_changes` | 无 | **丢失** |
| `preflight` checks | 无 | **丢失** |
| `blast_radius.forbidden_paths` | manifest.yaml `forbidden_paths` | 保留 |
| `divisions/` | 无 | **丢失** |
| `policy-denials.jsonl` (per-dept) | 无 | **丢失** |
| `run-log.jsonl` (per-dept) | 无 | **丢失** |
| `guidelines/` (safe harbor) | 无 | **丢失** |

丢失了 6+ 个功能维度。特别是 `preflight` checks（磁盘空间、文件存在性）和 `dimensions`（routing 的多维语义匹配），这些不是装饰。

### 3. `test` READ 权限矛盾 — P1，Review 提了但设计没修

Review 明确指出：`test` 标记为 READ，但 "Run tests, verify coverage" 需要 shell 执行（pytest 产生临时文件、coverage 报告）。

设计文档的回应：**没有**。`test` 仍然是 READ。

这导致 `verifier` = verify(READ) + test(READ) = **READ**。一个 READ agent 怎么跑 `pytest`？

两种可能：
- verifier 实际上跑不了测试 → `test` capability 在它身上是摆设
- 运行时绕过权限检查 → authority 系统就是纸老虎

`test` 应该是 `EXECUTE`（如果引入新级别）或直接标 MUTATE。

### 4. Intent Profile 系统消融 — P1，Review 未提及

当前系统有三档执行策略：

```python
class PolicyProfile(Enum):
    LOW_LATENCY = "low_latency"   # haiku, 10 turns, 120s
    BALANCED = "balanced"          # sonnet, 25 turns, 300s
    HIGH_QUALITY = "high_quality"  # sonnet, 40 turns, 600s
```

每个 intent 绑定一个 profile。同一个 department 的不同 intent 可以用不同的模型和资源。

新设计里 agent.yaml 的 intents 有 `profile` 字段，但 `CapabilityComposer.compose()` 输出的 `ComposedSpec` 里没有 profile 概念——只有 model、max_turns、timeout_s。这些值从哪来？

- 如果从 capability merge 来 → model=max 策略已经定了，profile 的 LOW_LATENCY 选项永远不会生效
- 如果从 intent profile 来 → 会覆盖 capability merge 的结果吗？Override Stack 没提 profile

当前系统的 LOW_LATENCY path（haiku + 10 turns）是性能关键路径，新设计看不到保留它的机制。

### 5. 15 个 Capability 但只有 3 种 Authority — 粒度不匹配

```
READ < MUTATE < APPROVE
```

但实际需求至少有 5 种权限级别：
- **READ**：只读代码和数据
- **EXECUTE**：运行测试/命令但不改文件（test、monitor）
- **MUTATE**：修改文件
- **NETWORK**：外部网络访问（collect、operate）
- **APPROVE**：审批权

把 `test`（需要 EXECUTE）和 `review`（只需要 READ）都标成 READ，是因为缺少 EXECUTE 级别。这是类型系统的表达力不足。

### 6. authority_cap 只限权限不限 prompt — 冲突指令仍注入

architect = plan + refactor。`design_plan` intent 的 authority_cap = READ。

权限被限制了，但 `refactor.prompt` 里的指令（"执行结构性重构"、"删除死代码"）仍然被注入到 LLM context。LLM 看到 "执行结构性重构" + READ 权限 → 两种结果：
1. 工具调用被拦截 → LLM 反复重试 → 浪费 token + turns
2. LLM 改为用文字描述重构步骤 → 混入执行性语言（"我已经修改了..."），用户以为做了实际改动

**修复建议**：compose 时，如果 intent 的 authority_cap < capability 的 authority，应该**排除**那个 capability 的 prompt，而不是注入后靠权限拦截。

### 7. Fact layer rubric 权重固定，场景不匹配

reviewer = review(0.7) + discipline(0.3)。

在 fact layer 场景下，anti-sycophancy 应该是**主要职责**（需要 50%+），但 rubric 写死了 discipline 30%。而且 `review` prompt 的权重（0.7）更高，"审查代码质量" 的指令会盖过 "保持事实中立" 的指令。

**体验感知**：fact layer 的输出开始夹带代码审查意见（"这段代码可以优化"），而不是纯粹的事实陈述。

**修复建议**：rubric 权重应该随 intent/transition 上下文动态调整，而不是写死在 agent.yaml。

---

## 二、回归风险与潜在 Bug

### Bug A：DB 迁移 CASE 语句缺少 NULL/ELSE 处理

```sql
UPDATE tasks SET agent = CASE department
    WHEN 'engineering' THEN 'engineer'
    ...
END;
```

如果有 `department IS NULL` 的记录（系统异常时可能产生），CASE 没有 `ELSE` 子句 → `agent` 被设为 NULL → 后续查询 `WHERE agent = 'engineer'` 丢数据。

应该加 `ELSE department`（保留原值便于排查）。

### Bug B：Qdrant 迁移无幂等性保证

设计说 "Batch update all vectors' department metadata field"。但 Qdrant 不支持事务。如果更新到一半崩了：
- 部分向量有 `agent` 字段，部分只有 `department`
- dual-query 可以兜底，但 `department_legacy` 字段只存在于更新完的记录上
- 搜索会出现不一致结果

应该用幂等写法（检查是否已更新再写）或分批 + checkpoint。

### Bug C：`cancel_all_if_failed` callback 竞态条件

```python
for gate in ['clarify', 'synthesis']:
    workers[gate].add_done_callback(
        lambda t, all_tasks=workers: cancel_all_if_failed(t, all_tasks)
    )
```

时序问题：

```
workers['clarify'] = create_task(...)
workers['synthesis'] = create_task(...)
# callback 注册完毕
# 如果 clarify 在这里就完成并失败 → callback 触发
# 此时 workers 还没有 'scout' key
workers['scout'] = create_task(conditional_scout())
# scout 已经创建但没被 cancel → 资源浪费
```

`done_callback` 在 task 完成时**同步**触发。如果 gate 在 scout task 创建之前就失败，callback 遍历 `workers` dict 时 `'scout'` key 还不存在 → scout task 逃逸 cancel → 白白跑完。

### Bug D：`conditional_scout` 的 CancelledError 传播

```python
async def conditional_scout():
    mode = await workers['cog_mode']
    if mode.value == "designer":
        return await run_scout(spec)
    return None
```

如果 `workers['cog_mode']` 被 cancel（因为 gate 失败），`await workers['cog_mode']` 抛 `CancelledError`。这个异常在 `conditional_scout` 里冒泡——但 `conditional_scout` **本身**的 task 可能没有被 cancel（因为 Bug C 的竞态）。

`asyncio.gather(return_exceptions=True)` 会捕获它，但 results dict 里这个 key 的值是 `CancelledError` 实例。后续代码用 `isinstance(v, (asyncio.CancelledError, Exception))` 检查——但在 Python 3.9+ 中，`CancelledError` 不再继承 `Exception`，继承 `BaseException`。`isinstance(v, Exception)` 匹配不到 `CancelledError`。

### Bug E：FSM `_defaults.yaml` 继承的合并策略未定义

```yaml
# _defaults.yaml
transitions:
  retry: __self__
  escalation: ""
  fact_layer: reviewer
  expression_layer: inspector
```

```yaml
# engineer.yaml
transitions:
  done: quality_review
  fail: log_only
```

"Inherited from _defaults" — 合并策略是什么？
- Shallow merge（engineer 的 transitions 覆盖整个 defaults）？→ 丢失 retry、escalation
- Deep merge（per-key override）？→ engineer 保留 retry + escalation + 新增 done/fail

文档用 "inherited" 一词但没有明确 merge 策略。实现者的第一个疑问。

### Bug F：`resolve_trigger` 命名空间冲突

设计说 `on_done: quality_review` 的解析规则：

1. Exact agent key match → 如果 value 是合法 agent key → 直接用
2. Trigger name lookup → 搜索匹配的 transition trigger name

问题：如果未来有个 agent 叫 `quality_review`，规则 1 会直接匹配到这个 agent，而不是走规则 2 的 trigger 语义。当前设计里没有这个冲突，但命名空间没有隔离 = 定时炸弹。

应该用前缀区分（`@engineer` 表示 agent，`quality_review` 表示 trigger），或者用 `Literal` 枚举约束合法值。

---

## 三、消费端体验走查

### 场景 A："修一下 auth.py 的登录 bug" — 标准修复流程

```
用户输入 → IntentGateway.parse() → engineer, code_fix
  → Dispatcher Pipeline (async ~7s)
  → CapabilityComposer.compose("engineer")
  → develop.prompt + test.prompt 拼接
  → Executor 执行
  → on_done → quality_review → reviewer
```

| 步骤 | 当前系统 | 新系统 | 差异 |
|------|---------|--------|------|
| 1. 意图解析 | → engineering, code_fix | → engineer, code_fix | OK |
| 2. Pipeline | 10 步串行, ~22s | 3 phase async, ~7s | 体验提升 |
| 3. Prompt 组合 | engineering SKILL.md（完整、调教过的） | develop.prompt + test.prompt 拼接 | **降级风险** |
| 4. Division 路由 | → implement division（针对性 prompt） | 无 division 概念 | **粒度退化** |
| 5. 执行 | sonnet, MUTATE, 25 turns | sonnet, MUTATE, 25 turns | 相同 |
| 6. 质量审查 | FSM → quality dept（含 anti-sycophancy） | on_done → reviewer（discipline 30%） | **权重不匹配** |
| 7. 结果 | 两轮完成 | 两轮完成 | 流程等价 |

**体验痛点**：
- Step 3：prompt 从精心编写的 SKILL.md 变成两段 prompt.md 拼接。当前 SKILL.md 是经过多轮调教的完整指令，拼接版质量很可能下降。
- Step 4：当前系统可以区分 "修 bug" → implement vs "搭脚手架" → scaffold，新系统所有开发任务共享同一段 develop.prompt。
- 用户感知：不会直接感知 prompt 变化，但会发现 "以前能一次修好的 bug 现在要两轮"。这种隐性回归最难排查。

### 场景 B："帮我做个重构计划" — 权限溢出（已修复）+ prompt 冲突（未修复）

```
用户输入 → architect, design_plan
  → compose(plan, refactor) → MUTATE
  → authority_cap: READ → 最终权限: READ ✓
  → 但 refactor.prompt 仍然被注入
```

| 步骤 | 问题 |
|------|------|
| 权限 | authority_cap=READ 有效拦截了写操作 ✓ |
| Prompt | refactor.prompt 包含执行性指令，注入到 READ 场景 ✗ |
| 模型 | opus（从 sonnet 升级），成本 ↑ |
| 行为 | LLM 可能在输出中混入 "我已经重构了..." 的误导性表述 |

### 场景 C："全量安全审计" — 模型已修复

```
用户输入 → sentinel, full_audit
  → audit(sonnet) + secure(haiku) → model: max = sonnet ✓
```

Review 指出的 haiku 问题已修复。audit capability 的 model 改为 sonnet，sentinel 解析后 model=sonnet。

但 `secure` capability 仍然是 haiku。如果 sentinel 在审计过程中需要 secure 的注入检测能力，那部分推理仍然受限于 haiku 水平的 prompt。虽然模型层面用了 sonnet，但 secure.prompt 可能是为 haiku 的能力边界编写的（更简单的指令），在 sonnet 上可能 underutilize。

### 场景 D：ad-hoc "审查代码并修掉问题" — 多 agent 路径

```
用户输入 → capabilities: [review, develop]
  → review → reviewer; develop → engineer
  → 两个 agent → SuperstepPlan（各自独立 session）
```

设计说 "Multi-agent coverage becomes a Superstep plan with independent agent sessions"。

**问题**：用户说的是一个连续动作（"看完就修"），但系统拆成了两个独立 session：
1. reviewer 审查 → 输出审查报告
2. engineer 修复 → 但它不知道 reviewer 看了什么

reviewer 的输出需要传递给 engineer，这就是 task_handoff 的职责。但 SuperstepPlan 的 "independent agent sessions" 意味着并行执行，不是串行。

如果并行：reviewer 和 engineer 同时开工，engineer 还没看到审查结果就开始修了。
如果串行：那就不是 "Superstep"，而是普通的 FSM 转移。

**设计模糊**：SuperstepPlan 在 ad-hoc 场景下的执行语义未定义。

### 场景 E：并发执行 — Semaphore 排队

用户同时触发：
1. "修 bug" → engineer (MUTATE, code_fix)
2. "重构模块" → architect (MUTATE, code_refactor)
3. "修 Docker" → operator (MUTATE)

三个 MUTATE agent，`mutate_max=2`。第三个排队。

设计建议 architect 的 `design_plan` intent 用 READ slot，但 `code_refactor` intent 用 MUTATE slot。

**消费端问题**：用户不知道 intent 会影响并发。当前系统只有 2 个 MUTATE department，排队概率低。新系统 3 个 MUTATE agent 但 slot 还是 2 → 排队概率 ↑ 50%。用户看到任务卡住，没有可见的原因。

---

## 四、严重度汇总

| # | 问题 | 严重度 | 发现源 |
|---|---|---|---|
| 1 | Divisions 系统整体丢失，20 个子专业 prompt + exam 无去处 | **P0** | 本次新发现 |
| 2 | Manifest 的 6+ 功能字段丢失（preflight, dimensions, policy 细项） | **P1** | 本次新发现 |
| 3 | `test` READ 权限矛盾 | **P1** | Review 提了，设计未修 |
| 4 | Intent Profile（LOW_LATENCY/BALANCED/HIGH_QUALITY）消融 | **P1** | 本次新发现 |
| 5 | Authority 类型只有 3 种，粒度不足 | **P1** | 本次新发现 |
| 6 | authority_cap 不限 prompt 注入 → 冲突指令 | **P2** | 本次新发现 |
| 7 | DB 迁移 CASE 缺 ELSE / Qdrant 无幂等 | **P2** | 本次新发现 |
| 8 | `cancel_all_if_failed` 竞态（scout 逃逸） | **P2** | 本次新发现 |
| 9 | `conditional_scout` CancelledError 在 Python 3.9+ 的 isinstance 不匹配 | **P2** | 本次新发现 |
| 10 | FSM defaults 合并策略未定义 | **P2** | 本次新发现 |
| 11 | Fact layer rubric 权重固定，场景不匹配 | **P2** | 本次新发现 |
| 12 | Ad-hoc SuperstepPlan 并行 vs 串行语义未定义 | **P2** | 本次新发现 |
| 13 | `resolve_trigger` 命名空间冲突 | **P3** | 本次新发现 |

---

## 五、建议

### 进入 Implementation Plan 前必须解决

1. **Divisions 迁移方案**：做一次知识审计——导出每个 department 的 SKILL.md、division prompts、exam cases，标记哪些映射到新 capability prompt，哪些需要新的承载机制（如 capability 支持 sub-specializations）
2. **`test` authority**：要么引入 EXECUTE 级别，要么把 test 标为 MUTATE 并在文档中解释
3. **Intent Profile 保留机制**：明确 compose() 如何处理 profile → 对应的 model/turns/timeout 值从哪一层注入
4. **Manifest 字段迁移表**：每个丢失的字段标注 "迁移到 X" 或 "设计决策：不再需要，原因是 Y"

### 实施中可迭代

5. FSM defaults merge 策略写明（推荐 deep merge with per-key override）
6. authority_cap 联动 prompt 过滤（cap < capability authority → 排除该 capability prompt）
7. DB 迁移加 ELSE 子句 + Qdrant 分批幂等更新
8. Pipeline 竞态修复（scout task 创建提前到 callback 注册之前，或用 TaskGroup）
9. Rubric 权重支持 intent/transition 上下文动态调整

### 收尾处理

10. `resolve_trigger` 加命名空间前缀或枚举约束
11. CancelledError isinstance 兼容 Python 3.9+（改用 `BaseException`）
