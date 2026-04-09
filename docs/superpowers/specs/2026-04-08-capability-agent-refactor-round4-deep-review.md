# Round 4: Deep Review — Capability + Agent Refactor

**Date**: 2026-04-08
**Reviewer**: Orchestrator (self-review, consumer-perspective walkthrough)
**Input**: design.md + 3 prior review rounds + full codebase read
**Verdict**: **Not ready for implementation** — 3 P0, 4 P1, 3 P2 remaining

---

## 一、设计层面的不合理

### 1. `express` 能力的 authority=READ 限制未来扩展

`express`（表达层重写、语气调整）标记为 READ。当前 protocol 部门也在 `READ_DEPARTMENTS`，所以这是延续。但 inspector 在 `inspect` + `express` 两个能力下，如果将来有"修复文档错误"的 intent，会被 READ 卡死。

**建议**：至少留个 intent-level override 的示例，让 inspector 的某些 intent 可以拿到 MUTATE。

### 2. `collect` 放在 operator 上，model 从 haiku 升到 sonnet

`collect` capability 推荐 model 是 haiku（合理，数据采集不需要高智能），但 operator agent 的 model 是 sonnet。compose 的 model merge 策略是 max(haiku, sonnet) = sonnet。

**结果**：每一次简单的数据采集任务，即使只激活 collect 能力，也会用 sonnet 跑。设计里 operator 的 intent 示例只有 `docker_fix`，没有 `data_collect` 这种纯采集 intent。

**成本影响**：如果采集频率高（每小时、每天多次），sonnet vs haiku 的成本差异是 10-20 倍。

**建议**：operator 需要一个 `collect_data` intent，`active_capabilities: [collect]`，profile 设为 LOW_LATENCY（降 model 到 haiku）。

### 3. Override Stack L3 的 profile "lower" 语义不清晰

设计说 "Profile can **lower** the model/turns/timeout from compose defaults"。但没有说清楚这个"lower"是单向的（只能降不能升）还是双向覆盖。

如果是双向覆盖：某个 intent 设了 HIGH_QUALITY 但 compose 结果已经是 opus，HIGH_QUALITY 的 sonnet 反而会降级 opus → sonnet。

**建议**：明确语义——profile 是 **ceiling**（天花板，只能降不能升）。

### 4. `discipline` 没有独立的反谄媚检查路径

`discipline` 变成 reviewer 的一个能力——只有 reviewer 执行时才启用反谄媚。如果某个任务的 FSM transition 是 `done: log_only`（terminal），或者任务太简单跳过了 review，discipline 不会触发。

当前系统也不是对所有输出都跑 guard，所以不完全算回归。但值得标注为已知风险。

### 5. Ad-hoc 模式的依赖检测逻辑过于简化

设计说 "if capability set includes both READ and MUTATE capabilities targeting the same files, assume sequential"。

**问题**：
- "targeting the same files" 怎么判断？capability manifest 里的 `writable_paths` 只定义可写范围，不是实际目标文件。
- develop (MUTATE) 和 audit (READ) 同时请求，可能操作完全不同的文件，但因为 authority 级别不同被错误序列化。

**建议**：要么全部序列化（简单安全），要么需要任务级别的文件范围声明。当前的 "same files" 启发式不可靠。

---

## 二、回归风险和潜在 Bug

### Bug 1: `CEILING_TOOL_CAPS` 缺少 Agent/Task/Web 工具 — P1

```python
CEILING_TOOL_CAPS = {
    "READ":    {"Read", "Glob", "Grep"},
    "EXECUTE": {"Read", "Glob", "Grep", "Bash"},
    "MUTATE":  {"Read", "Glob", "Grep", "Bash", "Write", "Edit"},
    "APPROVE": {"Read", "Glob", "Grep", "Bash", "Write", "Edit"},
}
```

**遗漏**：当前 executor 还用 `Agent`（子代理调用）、`WebSearch`/`WebFetch`（需要 `can_network`）、`TaskCreate`/`TaskUpdate` 等工具。这些在 ceiling 映射里完全没出现。

**后果**：如果工具过滤基于 CEILING_TOOL_CAPS 做白名单，子代理调用和网络访问全部失效。

**修复**：需要 `ALWAYS_AVAILABLE` 集合（TaskCreate, TaskUpdate, TaskGet 等）+ `NETWORK_TOOLS`（WebSearch, WebFetch）由 `can_network` 控制。

### Bug 2: `return_to: __caller__` 依赖不存在的 `executor.resume()` — P0

```python
async def execute_with_fsm(task, agent, trigger):
    result = fsm.get_next(agent, trigger)
    if result.return_to == "__caller__":
        sub_output = await executor.execute(result.target, task)
        task.context[f"{trigger}_output"] = sub_output
        return await executor.resume(agent, task)  # ← 不存在
```

当前 executor 是 **stateless** 的——每次 execute 是一个完整 session 从头开始。resume 意味着需要保存和恢复 agent 执行状态（conversation history、plan progress），需要 **session state persistence**，当前架构完全没有。

**影响**：整个 fact-expression split 的新实现依赖这个机制。

**替代方案**：不做 resume，而是把 fact_layer/expression_layer 的输出作为 enrichment 注入到 **初始 dispatch** 阶段——在 agent 执行之前就跑完 fact+expression，而不是执行中间打断。这更符合当前 dispatcher pipeline 的 phase 0 并行设计。

### Bug 3: DB migration 的 department 列保留导致写入二义性 — P2

设计说 "new code writes to agent column only"，但 `department` 列仍然存在且没有约束。如果迁移过渡期有遗漏的 consumer 仍写 department 列，数据不一致。Qdrant 的 `department` 字段也没删除。

**建议**：迁移后把 department 列设为 `DEFAULT NULL`，新插入的行不填 department。通过 `WHERE department IS NOT NULL AND agent IS NULL` 快速发现遗漏的旧代码路径。

### Bug 4: FSM `_defaults.yaml` 的 `fact_layer: reviewer` 默认值有害 — P2

如果某天新增 agent 忘记覆盖 fact_layer，默认行为是跳到 reviewer。对低级任务（analyst 的 monitor）会导致不必要的 reviewer 调用和成本。

**建议**：默认值应该是 `""` (terminal/skip)。需要 fact_layer 的 agent 应该显式声明。安全的默认值是"不做"，而不是"总是做"。

### Bug 5: `active_capabilities` 的 Tier 2 fallback 产生反直觉结果 — P2

```python
elif intent and intent.authority_cap:
    return [c for c in agent.caps if c.authority <= intent.authority_cap]
```

operator 的 `collect(MUTATE)` + `compress(READ)` + `operate(MUTATE)`，在 `authority_cap=EXECUTE` 时，只剩下 `compress(READ)`——一个纯压缩能力，没有任何操作能力。

**建议**：去掉 Tier 2，只保留 Tier 1（显式声明）和 Tier 3（全部）。要么精确控制，要么不控制。

### Bug 6: Semaphore 的 "effective authority" 计算时机未定义 — P1

semaphore acquire 需要在 intent resolve 之后才能用 effective authority。设计的 dispatch pipeline 伪代码里没有标注这个时序依赖。

---

## 三、消费端体验走查

### 场景 1：用户说"修这个 bug" — FSM 链断裂 (P0)

```
1. IntentGateway.parse("修这个 bug")
   → agent: engineer, intent: code_fix

2. Dispatcher Pipeline → PASS

3. CapabilityComposer.compose("engineer", authority_cap=MUTATE)
   → develop.prompt + test.prompt
   → tools: {Read, Glob, Grep, Bash, Write, Edit}

4. Executor 执行 → Agent 修完 bug
   → 触发 FSM: done → quality_review

5. resolve_trigger("quality_review")
   → 没有 @ 前缀，不是 agent reference
   → 搜索 agents 的 transition triggers... quality_review 不是任何 agent 的 trigger key
   → ❌ No match → error
```

**Bug**：`quality_review` 在 engineer 的 `done` transition 里，但它既不是 `@reviewer`（agent reference）也不是任何 agent 声明的 trigger name。

**对比当前系统**：`("engineering", "quality_review"): "quality"` 是 hardcoded 映射。新系统的 resolve 逻辑要求目标要么是 `@agent`、要么是 terminal。

**修复**：engineer.yaml 应写 `done: @reviewer` 而不是 `done: quality_review`。

### 场景 2：Fact-Expression Split — 功能入口丢失 (P0)

当前系统中 fact-expression split 是 **dispatcher 层** 做的：
- dispatcher 里有 `_SPLIT_INTENTS = {"answer", "review", "analyze", "report", "explain", "advise", "assess"}`
- 检测到 split intent 后，先 dispatch quality（事实层），再 dispatch protocol（表达层）

新设计把它放到了 FSM transition 里（`fact_layer: reviewer`）。但：
- **谁触发 fact_layer？** agent 执行后 FSM 自动触发，但设计里没有机制让 dispatcher 或 agent 判断"需要 split"
- dispatch pipeline 伪代码里 **完全没有 fact-expression split 的逻辑**
- 如果 dispatcher 里的 `_SPLIT_INTENTS` 代码在重构中被删掉，功能彻底丢失

**影响**：P0。核心功能在新设计里找不到明确的实现路径。

### 场景 3：并行审计 — 缺少 reducer 策略

```
dispatch(capabilities=["audit", "review", "inspect"])
→ sentinel ∥ reviewer ∥ inspector (Superstep)
→ 完成后... Channel-Reducer merges all results
```

当前 `group_orchestration.py` 有完整的 `SupervisorDecision` + `RoundResult` 实现。新设计的 scenarios.yaml 只定义 agent 列表，没有 reducer 策略。

**建议**：scenarios.yaml 需要 `reducer` 字段，声明合并策略。

### 场景 4：Clawvard 考试 — 考试层级错位

考试路径从 `departments/engineering/implement/exam_cases.jsonl` 变为 `capabilities/develop/specializations/implement/exam_cases.jsonl`。

**更深的问题**：考试应该考 **composed agent**（engineer 在 code_fix intent 下的表现），不是单独 capability。因为 compose 后 test.prompt 的干扰可能导致实际表现下降，但单独考 develop 能力分数可能很高。

**建议**：考试层级应该是 agent-level，capability-level 的 rubric.yaml 只做评分维度拆分。

### 场景 5：Intent LLM Prompt 路由 — 返回旧名称 (P1)

IntentGateway 的 LLM prompt 当前写的是"选择一个部门"。重构后输出 `agent` 而不是 `department`。如果 prompt 没同步更新，LLM 返回 "engineering" 而不是 "engineer"，路由全部失败。

File Changes 列了 `src/gateway/intent.py` 需要 rewrite，但没有明确标注 LLM routing prompt 需要同步更新。

### 补充：Prompt 拼接顺序

两个 prompt 拼接时（develop.prompt + test.prompt），由于 LLM 的 recency bias，后面的 test 指令会比 develop 更受重视。对于 code_fix intent，develop 才是主要任务。

**建议**：按 weight 降序排列 prompt（高权重在后利用 recency bias），或在设计里明确策略。

---

## 四、Critical Path 阻断项汇总

| # | 问题 | 级别 | 影响 |
|---|------|------|------|
| 1 | `executor.resume()` 不存在，return_to 机制无法实现 | **P0** | fact-expression split 整体失效 |
| 2 | `quality_review` trigger 无法 resolve | **P0** | engineer→reviewer FSM 链断裂 |
| 3 | fact-expression split 在新 dispatch pipeline 里没有入口 | **P0** | 核心功能丢失 |
| 4 | CEILING_TOOL_CAPS 缺少 Agent/Task/Web 工具 | **P1** | 子代理和网络功能全部失效 |
| 5 | Intent LLM prompt 仍在选"部门" | **P1** | 路由全部返回旧名称 |
| 6 | operator 的 collect intent 缺失，采集默认用 sonnet | **P1** | 成本膨胀 |
| 7 | Semaphore effective authority 计算时机未定义 | **P1** | 可能占错 slot 类型 |
| 8 | prompt 拼接顺序未定义策略 | **P2** | 静默质量回归 |
| 9 | Tier 2 fallback 产生反直觉过滤结果 | **P2** | operator 在 EXECUTE cap 下只剩 compress |
| 10 | scenarios.yaml 缺少 reducer 策略 | **P2** | 并行结果无合并规则 |

---

## 五、核心设计矛盾

这个设计试图用声明式 FSM（agent.yaml transitions）替代命令式流程（dispatcher 的 if/else 链），但很多当前行为 **不在 FSM 里**——fact-expression split 是 dispatcher 的逻辑，不是 FSM transition。把它塞进 FSM 导致 executor 需要 resume 能力，这是一个架构级新需求。

**更务实的路径**：保持 fact-expression split 在 dispatcher 层，FSM 只管 done/fail/retry/escalation 这类后处理 transition。不要让 FSM 承担运行时流程编排的职责——那是 dispatcher/governor 的活。

---

## 建议：实施前必须解决

1. **确定 fact-expression split 的归属**：是 dispatcher enrichment（推荐）还是 FSM transition（需要 resume 架构）
2. **修复 FSM transition 值**：所有 agent reference 统一用 `@agent` 格式，不要用 bare trigger name
3. **补全 CEILING_TOOL_CAPS**：加入 `ALWAYS_AVAILABLE` 和 `NETWORK_TOOLS` 集合
4. **补全 operator 的 collect intent**：LOW_LATENCY profile 降 model 到 haiku
5. **明确 Override Stack L3 profile 语义**：ceiling（只降不升）还是 override（双向覆盖）
6. **删除 Tier 2 fallback**：只保留显式声明和全部两档
