# Capability-Agent Refactor 设计对抗性深审报告

## 执行摘要

- `CRITICAL` 迁移步骤仍自相矛盾：文档一边要求 v1/v2 共存期保留 `departments/` 作为回滚路径，另一边又在迁移步骤第 6 步提前把 `departments/` 移到 `.trash`，会直接破坏回滚与大量根目录探测代码。
- `HIGH` Override Stack 仍未闭环：正文保留 L2 Blueprint 参与每个维度决策，但文末又声明 L2 在 v1 中是 `RESERVED`。这会让实现者无法判断 `blueprint` 到底是不是可执行层。
- `HIGH` `active_capabilities`、`model_floor`、`intent.model` 三组规则互相打架：文中同时宣称 `intent.model` 是“hard override”、`profile` 是 ceiling、`floor` 总能胜出，导致 LOW_LATENCY + `opus-floor` 等流转没有唯一决议。
- `HIGH` 当前系统以 `department` 为真实主键贯穿 `gateway`、`dispatcher`、`governor`、`FSM`、`review_dispatch`、`semaphore`、`budget`、`eval`、`channels`；设计没有给出一个真正可增量落地的兼容层，多个关键路径只能 big-bang 切换。
- `HIGH` ad-hoc capability 模式引入新的权限旁路：`authority_cap` 只定义在 intent 上，但 `resolve_adhoc(capabilities=[...])` 并不经过 intent 约束，等于给了“绕开角色 intent 限权，直接按能力求最强 agent”的入口。

## 1. 逻辑一致性与自相矛盾

### 1. [CRITICAL] 回滚路径与迁移步骤互相冲突，文档内部仍未自洽
- 严重级别：`CRITICAL`
- 位置：设计文档 `## Migration` L898-L909，`### Migration Steps` L950-L956，`### Post-Validation Cutover` L967-L974
- 描述：确认问题。L909 明确写了“`departments/` is NOT deleted until v2 is confirmed stable. Rollback = set `ORCHESTRATOR_ARCH=v1`”，L969-L974 又把删除旧路径放到“48h 验证后”的 cutover 阶段；但 L955 仍把 `departments/` 移到 `.trash` 作为正式迁移步骤第 6 步。三处规则不能同时成立。
- 触发场景：团队按“Migration Steps”执行到第 6 步后，`ORCHESTRATOR_ARCH=v1` 仍然可设置，但 `src/governance/registry.py`、`src/governance/eval/prompt_eval.py`、`src/governance/audit/run_logger.py`、多处 root detection 仍依赖 `departments/`，回滚立即失效。
- 修复建议：删除或改写 L955，把“移动 `departments/`”只保留在 cutover 阶段；同时把“回滚前置条件”写成显式 checklist，而不是口头说明。

### 2. [HIGH] Override Stack 的 L2 到底存在还是保留位，正文与结论冲突
- 严重级别：`HIGH`
- 位置：设计文档 `### Override Stack` L358-L379；文末 `### Adversarial Review` L1208
- 描述：确认问题。L358-L379 把 L2 Blueprint 当成正式参与者，并在 dimension table 中给了 `model/max_turns/timeout/authority/tools/paths/blast_radius` 的具体规则；但 L1208 又说“L2 marked RESERVED in v1; Dimension Resolution Table simplified to L0/L1/L3”。正文没有反映这个结论，导致实现范围不确定。
- 触发场景：实现者按表格去落地 `blueprint` 对 `authority/tools/paths` 的真实收敛逻辑，同时另一个实现者按 L1208 把 L2 当占位层，最终会在 `src/governance/policy/blueprint.py`、`executor_prompt.py`、`dispatcher.py` 产生不兼容实现。
- 修复建议：二选一。要么从正文删掉 L2，并把所有 L2 列改成 `N/A`；要么补充明确的 v1 consumer 列表，说明哪些代码真正消费了 L2。

### 3. [HIGH] `architect/design_plan` 的“已修复问题”又被后文重新引入
- 严重级别：`HIGH`
- 位置：设计文档 `### Intent-Level Capability Filtering` L315-L318；`### Round 5` 结论 L1140
- 描述：确认问题。L1140 声称 round 5 已修复“`architect/design_plan` filters out refactor knowledge”，修复方案是 `active_capabilities: [plan, refactor] with authority_cap=READ`；但正文示例 L317 又回到 `active_capabilities: [plan]`，并明确说“no refactor instructions”。这不是措辞差异，而是两种完全不同的 prompt 语义。
- 触发场景：如果实现者遵从正文，`architect/design_plan` 将不再看到 `refactor` prompt；如果遵从 round 5 结论，则 `refactor` prompt 仍会注入但权限收窄到 READ。两者会直接影响 Flow B 的拆解质量。
- 修复建议：在 agent YAML 示例中给出唯一版本，并在“Issue Resolution”里注明 round 5 方案是否已被 round 7 明确回滚；不能同时保留两种说法。

### 4. [HIGH] `intent.model`、`profile ceiling`、`model_floor` 的优先级定义前后不一致
- 严重级别：`HIGH`
- 位置：设计文档 L290-L295，L337-L343，L371，L1216
- 描述：确认问题。L290-L292 把 `intent.model` 写成“explicit hard override”；L371 也写成“explicit=hard override; profile=ceiling with floor”；但 L1216 又给出最终规则 `final = max(floor, intent.model if explicit else min(compose, ceiling))`，这意味着当 `intent.model < floor` 时，`intent.model` 并不是 hard override，而是会被 floor 覆盖。
- 触发场景：Flow E 中 `LOW_LATENCY` intent 如果显式写 `model: haiku`，但 capability 上存在 `model_floor: opus`，最终到底是 `haiku` 还是 `opus`，目前正文存在两个答案。
- 修复建议：把“hard override”改成“显式请求，但仍受 floor 约束”，并在 Resolution Table 中用同一句规范表达，避免实现者各自猜测。

## 2. 回归风险分析

### 1. [HIGH] intent routing 无法静默迁移，当前前门到 Governor 的合同仍是 `department`
- 严重级别：`HIGH`
- 位置：设计文档 `## Task Execution Flow / Single Task` L848-L857，`### File Changes` L1012-L1018；代码路径 `src/gateway/intent.py::TaskIntent.to_governor_spec`，`src/gateway/routing.py::resolve_route`，`src/gateway/dispatcher.py::dispatch_user_intent`
- 描述：确认问题。设计把入口改成“route to agent + intent”，但当前 `TaskIntent`、`resolve_route()`、`dispatch_user_intent()`、webhook 订阅都把 `department` 作为下游 spec 主字段。只改 registry 不能让前门自动切到 agent。
- 触发场景：如果先打开 `ORCHESTRATOR_ARCH=v2`，但 `IntentGateway` 仍输出 `department`，Governor 下游可能拿到一个没有 `department` fallback 的 agent-only spec，或者 agent 值被当成 department 值写进 DB，造成任务路由错乱但不一定立刻报错。
- 修复建议：把 `gateway/intent.py`、`routing.py`、`dispatcher.py`、`webhook.py` 视为同一批原子切换；迁移期间要么双写 `department+agent`，要么保留严格的 adapter。

### 2. [HIGH] semaphore 行为会在迁移期静默退化，当前实现仍是硬编码部门集
- 严重级别：`HIGH`
- 位置：设计文档 `## Semaphore Adjustment` L823-L831，`### Multiple Concurrent Tasks` L877-L893；代码路径 `src/governance/safety/agent_semaphore.py::MUTATE_DEPARTMENTS/READ_DEPARTMENTS/try_acquire`
- 描述：确认问题。设计要求按 agent default authority 构建 tier，并在运行时用 `effective authority` 选槽；当前实现只看 `department in {"engineering","operations"}` 或 `department in {"protocol","security","quality","personnel"}`，完全不理解 `architect/design_plan → READ slot` 这类动态降级。
- 触发场景：迁移后 `architect` 即使 `authority_cap=READ`，只要兼容层仍把它映射成类 engineering 的 MUTATE 角色，队列会被错误压到 mutate 池；反过来，如果直接传 agent key 给当前 semaphore，会因不在任何集合里而绕过部门级限制。
- 修复建议：先实现“按 authority 取槽”的新 semaphore，再改 dispatch 合同；不要指望 agent/department 字段替换后老 semaphore 还能正确工作。

### 3. [HIGH] eval、run log、learnings、budget 仍以部门为索引，迁移后会出现静默错账
- 严重级别：`HIGH`
- 位置：设计文档 `### Database` L728-L755，`### Impact Radius` L981-L988，L1206-L1209；代码路径 `src/governance/eval/prompt_eval.py`，`src/governance/eval/department_rubric.py`，`src/governance/audit/run_logger.py`，`src/storage/_learnings_mixin.py::get_learnings_for_dispatch`，`src/governance/budget/token_budget.py::_load_history`
- 描述：确认问题。当前 eval 从 `departments/<dept>/...` 读 prompt 与 exam case；run logger fallback 写 `departments/<dept>/run-log.jsonl`；learnings dispatch 用 `department = ? OR department IS NULL`；budget 用 `json_extract(t.spec, '$.department')` 聚合。设计虽提到 DB dual-query，但这些消费者并没有统一兼容层。
- 触发场景：新流量只写 agent，不再写 department 时，预算会把支出记到 `unknown`，learnings 命中率骤降，eval baseline 无法与 v1 横向可比，run-log JSONL 也不再被健康分析读取。
- 修复建议：迁移前先做双写而不是“只写 agent”；同时给 eval/run-log/budget/learnings 各自加显式 adapter，不要只在 SQL UPDATE 上下注。

### 4. [MEDIUM] dual-query 只覆盖 DB 文本查询，Qdrant/语义检索侧仍存在一致性空洞
- 严重级别：`MEDIUM`
- 位置：设计文档 `### Qdrant Metadata` L757-L774，`### Query Compatibility` L776-L778；代码路径 `src/governance/dispatcher.py::_get_semantic_context`，`src/storage/qdrant_store.py::search/search_scoped`
- 描述：风险。文档说“所有 DB queries dual-query”，但没有给出 Qdrant filter 的双字段策略。当前 `_get_semantic_context()` 从 `orch_runs` 取回结果后仍展示 `metadata.department`；一旦后续任何 capability/agent 检索开始依赖 payload filter，就会遭遇“部分点有 `agent`、部分点只有 `department`”的问题。
- 触发场景：Qdrant 迁移进行到一半，新的 search filter 只查 `agent=engineer`，老点全被漏掉；或者 UI 中相似历史 run 只显示空白 area/department，导致检索结果看似存在但不可解释。
- 修复建议：补一个与 SQL dual-query 对应的 Qdrant filter adapter，明确“迁移期所有检索条件必须对 `agent/department` 双字段求并集”。

## 3. 消费者视角的 5 条关键流转

### 1. [HIGH] Flow A: 用户消息 → intent gateway → agent 选择 → compose → execute → FSM → next agent
- 严重级别：`HIGH`
- 位置：设计文档 `## Task Execution Flow / Single Task` L848-L857；代码路径 `src/gateway/intent.py::TaskIntent.to_governor_spec`，`src/gateway/dispatcher.py::dispatch_user_intent`，`src/governance/governor.py::_dispatch_task`，`src/governance/review_dispatch.py::dispatch_quality_review`，`src/governance/department_fsm.py`
- 描述：确认问题。当前整条链路从前门到 review/rework FSM 都是 department-first：`TaskIntent` 输出 `department`，Governor 也把 task spec 当 department spec，review handoff 和 `DepartmentFSM` 的 transition 目标都是 department。设计版 Flow A 想把 agent 变成一级路由键，但没有定义一层“department-compatible governor spec”如何在过渡期持续工作。
- 触发场景：用户消息被解析为 `agent=engineer, intent=code_fix` 后，如果中途任何一段仍调用 `fsm.get_next_department(parent_dept, "quality_review")`，就会把 agent 流重新折回旧部门状态机，导致 reviewer 链接丢失或落入错误分支。
- 修复建议：先引入 `AgentFSM` 与 `spec["agent"]` 的新合同，再替换 `review_dispatch`/`department_fsm`；不要让 agent 流直接穿过旧 FSM。

### 2. [HIGH] Flow B: Architect subtasks → Governor capability matching → Superstep dispatch → reducer merge
- 严重级别：`HIGH`
- 位置：设计文档 `### Subtask Allocation` L860-L873，`## Parallel Scenarios` L632-L649；代码路径 `src/governance/group_orchestration.py::run/_dispatch_to_department/aggregate`，`src/governance/channel_reducer.py`
- 描述：确认问题。设计要求 subtasks 声明 `capabilities`，Governor 负责 capability→agent 匹配并按依赖进入 Superstep；但现有 `GroupOrchestrationSupervisor` 只接受 `department/departments`，完全没有 capability matching 层。此外 `_dispatch_to_department()` 会把“任务刚创建、还在 running”的状态也当成成功结果返回，`aggregate()` 随后直接并入 reducer。
- 触发场景：architect 产出两个 subtasks：一个给 engineer，一个给 reviewer 且 `depends_on` 前者。当前 supervisor 无法理解 capability 依赖，只能把它们当普通部门任务；更糟的是 reviewer 任务即使尚未真正完成，也会被 reducer 当成功结果合并。
- 修复建议：把 capability matching 与 dependency scheduler 作为独立实现，不要复用现有 group orchestration 的 department dispatcher；同时把 reducer 的输入条件收紧为“真正 completed 的 task output”。

### 3. [HIGH] Flow C: Fact-expression split Phase 0.5 → reviewer → inspector → merge back
- 严重级别：`HIGH`
- 位置：设计文档 `### Fact-Expression Split — Dispatcher Phase 0.5` L554-L606，L610-L629，L1214；代码路径 `src/governance/dispatcher.py::dispatch_with_fact_expression_split`，`src/governance/department_fsm.py`
- 描述：确认问题。正文 Phase 0.5 代码没有定义异常释放、失败分支和 `merge(fact_output, expr_output)` 的结构；文末 L1214 虽补充“Fact layer failure → REJECTED”，但正文未同步。现有实现则更弱：`dispatch_with_fact_expression_split()` 立即创建 expression task，只靠 `fact_layer_task_id` 作为上下文，没有真正依赖链或合并协议。
- 触发场景：reviewer 子任务失败、超时、被 scrutiny 拒绝，设计正文没有统一说明 expression 子任务是否还应继续；当前代码甚至可能已经把 expression task 发出去了，形成“表达层重写不存在的事实层结果”。
- 修复建议：把 `Phase 0.5` 写成有明确状态机的子流程：`fact_failed -> reject`，`fact_ok + expr_failed -> fallback to fact output?`，并要求 expression task 使用真实 `depends_on`。

### 4. [HIGH] Flow D: ad-hoc capability request（无特定 agent）→ `resolve_adhoc` → identity resolution
- 严重级别：`HIGH`
- 位置：设计文档 `### Two Invocation Modes` L404-L421
- 描述：风险。文档只定义了“两种情况”：单个 agent 覆盖、多个 agent 需要协作；没有定义“多个 agent 都能覆盖同一 capability 集”的 tie-break，也没定义 ad-hoc 请求如何套用 `authority_cap`、`profile`、`active_capabilities`、审计日志和 deny-list。
- 触发场景：请求 `capabilities=["review"]` 时，如果后续能力图演进出多个 reviewer-like agent，`resolve_adhoc()` 没有确定性选主规则；请求 `capabilities=["plan","refactor"]` 时，可能直接拿到 architect 的 MUTATE spec，而不是 `design_plan` 的 READ 约束。
- 修复建议：为 ad-hoc 模式补三个显式规则：覆盖冲突的 tie-break、最小权限策略、审计可见性；没有这些规则前，不应把 ad-hoc 当生产入口。

### 5. [HIGH] Flow E: `LOW_LATENCY` profile + `opus-floor` capability 的模型决议冲突
- 严重级别：`HIGH`
- 位置：设计文档 `### Intent Profile Preservation` L326-L344，`### Dimension Resolution Table` L371，L1216；代码路径 `src/gateway/routing.py::PolicyProfile`
- 描述：确认问题。设计想保留现有 profile 语义，但又给 capability 引入 `model_floor`。结果是 Flow E 中至少有三种候选答案：按 profile 用 haiku，按 explicit intent.model 用指定模型，按 floor 用 opus。正文没有唯一规则，且与当前 `PolicyProfile` 的“单一模型配置”思路不兼容。
- 触发场景：某 intent 标记 `LOW_LATENCY` 以压成本，但所选 capability 带 `opus-floor`；预算系统按 profile 预估低成本，最终 compose 却落到 opus，造成延迟和成本同时偏离预期。
- 修复建议：把“model resolution”做成独立、可记录 trace 的纯函数，并在设计里给出 4-5 个规范例子；没有 trace 之前，Flow E 很难验证。

## 4. 缺失的边界情况

### 1. [HIGH] intent 可以声明 0 个 active capability，但设计没有禁止
- 严重级别：`HIGH`
- 位置：设计文档 `### Intent-Level Capability Filtering` L282-L288，`### Migration Steps` L958-L963
- 描述：风险。正文 compose 伪代码允许 `active = []`，随后 prompt/rubric 都会基于空集合计算；而 `verify-intents.py` 只被要求检查“`active_capabilities ⊆ agent.capabilities`”，没有要求“非空”。
- 触发场景：某 agent intent 配错成 `active_capabilities: []`，最终会得到“只有 identity、没有 capability prompt/rubric”的 spec，执行时既不明显报错，也很难从日志中识别根因。
- 修复建议：在 schema 和 `verify-intents.py` 中增加 `active_capabilities` 非空校验；若为空，应显式回退到“all capabilities”或 hard fail。

### 2. [MEDIUM] `authority_cap` 低于所有 active capability 所需权限时，行为只靠提示词补救
- 严重级别：`MEDIUM`
- 位置：设计文档 `### Intent-Level Authority Cap` L258-L266，`### Intent-Level Capability Filtering` L270-L295，L141-L145
- 描述：风险。文档允许 `authority = min(authority, intent.authority_cap)`，但没有定义“当 active capability 本身语义依赖更高权限工具时怎么办”。目前唯一补救是插入一行 authority context 提示词，这不能保证行为稳定。
- 触发场景：如果某 intent 激活 `refactor` 或 `test` prompt，但 `authority_cap=READ`，模型会拿到高权限任务语义、低权限工具包和一行“只读观察”说明，容易产生无效建议、重复尝试或错误自我描述。
- 修复建议：为 capability 增加 `minimum_runtime_authority` 校验；当 intent cap 低于能力最低运行权限时，要求显式改用别的 capability 组合，而不是只靠 prompt 提示。

### 3. [HIGH] hot reload 会影响 in-flight task，但设计没有版本钉住机制
- 严重级别：`HIGH`
- 位置：设计文档 `### Hot Reload` L445-L447；代码路径 `src/governance/registry.py::reload`
- 描述：风险。文档沿用当前“单例原地 mutate”方案，但 ComposedSpec、FSM transition、subtask capability matching、intent prompt cache 都会受到 registry 热更新影响。设计没有说明任务创建时是否保存 registry version。
- 触发场景：任务 A 用旧 registry 已进入队列；中途 `reload()` 修改了 agent capability、model floor 或 transition；任务 A 的重试、子任务或 FSM 下一跳可能突然按新定义执行，复现困难。
- 修复建议：给 `ComposedSpec` 和 task row 增加 `registry_version`/`compose_trace`，in-flight task 固定解析结果；热更新只影响后续新任务。

### 4. [HIGH] Qdrant 部分迁移完成时的行为没有定义完整
- 严重级别：`HIGH`
- 位置：设计文档 `### Qdrant Metadata` L759-L774，`### Query Compatibility` L776-L778；代码路径 `src/storage/qdrant_store.py::search/search_scoped`
- 描述：风险。文档只定义了“补 agent 字段”的批量更新，没有定义在部分点已经带 `agent`、部分点仍只有 `department` 时，搜索过滤、展示、去重和命中统计如何处理。
- 触发场景：某条 learning 在 SQLite 中已双写，但 Qdrant payload 仍只有 `department`；后续 capability-agent 检索如果先读向量库，再回查 DB，就会出现“DB 里能看见，向量召回不到”的半失联状态。
- 修复建议：在迁移文档中增加“partial Qdrant state contract”，定义过滤规则、回填进度指标和强制完成阈值。

## 5. 安全与权限分析

### 1. [CRITICAL] ad-hoc mode 可以绕过 intent 级 `authority_cap`
- 严重级别：`CRITICAL`
- 位置：设计文档 `### Intent-Level Authority Cap` L258-L266，`### Two Invocation Modes` L404-L421
- 描述：确认问题。`authority_cap` 只出现在 intent 层，而 `resolve_adhoc(capabilities=[...])` 没有经过 intent。文档还强调“single-agent coverage uses that agent's identity”，这意味着 ad-hoc 请求可能直接拿到 agent 的 compose-level authority。
- 触发场景：正常 `architect/design_plan` 本应 `authority_cap=READ`；但 ad-hoc 请求 `capabilities=["plan","refactor"]` 会直接匹配 architect 并继承 MUTATE 级 authority，从而绕过只读设计任务的约束。
- 修复建议：禁止 ad-hoc 直接产出比“最接近 intent”更高的权限；若缺少 intent，就默认最小权限而不是 compose-level authority。

### 2. [HIGH] `active_capabilities` 只过滤 prompt/rubric，仍可能暴露不应存在的工具
- 严重级别：`HIGH`
- 位置：设计文档 `### Intent-Level Capability Filtering` L270-L295
- 描述：确认问题。文档明确规定 model/tools/authority 始终来自“ALL capabilities”。这解决了 identity 稳定性问题，但也让“低风险 intent 只想用一部分能力”无法真正缩小工具面。
- 触发场景：某 agent 拥有 `develop + test`，某 intent 只激活 `develop` prompt；按照 L277-L280，最终工具仍包含 `test` 带来的 shell 能力。攻击者只要触发这个 intent，就能拿到比 prompt 表面看起来更大的工具集。
- 修复建议：把“identity 稳定”与“工具暴露最小化”拆开：至少允许 intent 对工具做显式 restrict，或在 manifest 中标记哪些 capability 的工具可被安全隐藏。

### 3. [HIGH] semaphore tier 在 authority 运行时变化时缺少一致性保证
- 严重级别：`HIGH`
- 位置：设计文档 `### Multiple Concurrent Tasks` L877-L893，`### Hot Reload` L445-L447；代码路径 `src/governance/safety/agent_semaphore.py`
- 描述：风险。设计要求 slot type 由 `effective authority` 动态决定，但没有定义当 `authority_cap`、blueprint、hot reload 改变 effective tier 时，已占用槽位是否需要迁移、释放或重算。
- 触发场景：任务以 READ tier 入队，执行前 intent/registry 热更新把它提升到 MUTATE；或者相反，任务先占了 MUTATE 槽，后续被降到 READ。没有一致性协议时，队列统计会失真，甚至出现超卖。
- 修复建议：把 semaphore 的 key 从“agent/department 名”改成“task_id + resolved effective authority”，并规定 task 创建后 tier 不再变化；任何变化都通过新 task 体现。

## 6. 实现可行性

### 1. [CRITICAL] `gateway → dispatcher → governor → review/FSM → executor_prompt` 这一串不能增量改，只能原子切换
- 严重级别：`CRITICAL`
- 位置：设计文档 `### File Changes` L1003-L1019，`### Spec Schema Migration` L816-L818；代码路径 `src/gateway/intent.py`，`src/gateway/dispatcher.py`，`src/governance/governor.py`，`src/governance/review_dispatch.py`，`src/governance/executor_prompt.py`
- 描述：确认问题。文档把它们列为“需要改”，但仍把迁移描述成 feature-flagged coexistence。实际上这些模块共享同一个 `spec["department"]` 合同；任何一段先切 `agent`，都会与其他段立即不兼容。
- 触发场景：先改 gateway 产出 `agent`，review_dispatch 和 executor_prompt 仍按 department 读 prompt、跑 FSM、取 run logs；或者先改 Governor，前门仍传旧 spec。两边都不是可平滑过渡的状态。
- 修复建议：把这条链路定义为单独的 big-bang 里程碑，并在切换前引入过渡 adapter；不要把它误写成“逐文件渐进替换”。

### 2. [HIGH] eval/rubric/exam corpus 迁移同样不是渐进式，小改动无法保住可比性
- 严重级别：`HIGH`
- 位置：设计文档 L184，`### Manifest Field Migration` L804-L810，`### Migration Steps` L948-L965，L1209；代码路径 `src/governance/eval/prompt_eval.py`，`src/governance/eval/department_rubric.py`
- 描述：确认问题。设计把 eval 从“department rubric + division exam case”转到“agent capability 加权 rubric”，但文档只给了 baseline 步骤，没有给 exam corpus、dimension map、judge prompt 的完整新合同。L1209 还明确写着 `dimension_map.yaml migration missing`。
- 触发场景：v2 eval 即便跑通，也可能是在完全不同的题库与维度上比较，导致 Step 0b 基线和 Step 10 结果不可比，`P50 drop >10%` 失去意义。
- 修复建议：先冻结 v2 eval contract，再谈 prompt baseline；没有统一题库/维度映射前，不应把 10% 阈值作为 go/no-go 标准。

### 3. [HIGH] 迁移步骤顺序仍有循环依赖，至少 Step 3/4/9 不能按文案独立完成
- 严重级别：`HIGH`
- 位置：设计文档 `### Migration Steps` L950-L964
- 描述：确认问题。文档写成“3. 先跑 DB/Qdrant migration；4. Rewrite all consumers；9. verify-*”。但如果 consumer 还没双写新字段，Step 3 只会生成一次性快照；而 Step 9 的 `verify-migration.py` 又依赖 consumer 已经按新 contract 写数据，三者存在明显环依赖。
- 触发场景：先跑 Step 3 后继续上线旧 consumer，新产生的数据仍只写 department；Step 9 会发现 agent coverage 不完整，但那不是迁移脚本失败，而是合同尚未切换，验证结果没有可执行意义。
- 修复建议：把 Step 3 改成“schema migration + dual-write support”，把“data backfill”和“dual-write burn-in”单列成步骤，再在 cutover 前做 coverage 验证。

### 4. [HIGH] “最少 48h 生产验证”偏乐观，覆盖不到后台子系统与长尾路径
- 严重级别：`HIGH`
- 位置：设计文档 `### Post-Validation Cutover` L967-L974，`### Impact Radius` L976-L988；代码路径 `src/gateway/webhook.py`，`src/channels/formatter.py`，`src/governance/learning/*`，`src/governance/audit/run_logger.py`
- 描述：风险。当前系统不只有前门对话流，还包含 webhook、channels 展示、evolution/learning、JSONL fallback、周期任务、后台健康分析。48 小时生产流量很可能覆盖不到这些低频但关键路径。
- 触发场景：主聊天流两天内看起来正常，但周任务、webhook、run-log fallback 或健康分析要到下一次定时触发才暴露 `department` 残留，届时系统已经切走 rollback 资产。
- 修复建议：把“48h 生产验证”改成“48h + 完整场景回放 + 定时/后台任务至少一次全覆盖”；cutover 前必须跑低频路径 checklist。

## 严重级别汇总

| 严重级别 | 数量 |
|---|---:|
| CRITICAL | 4 |
| HIGH | 15 |
| MEDIUM | 3 |
| LOW | 0 |

