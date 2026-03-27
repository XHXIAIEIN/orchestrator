# 偷师总纲 — Orchestrator 升级清单

> 来源：32 个开源项目深度分析（2026-03-22）
> 目标：提炼可直接落地到三省六部架构的模式，按优先级排序

---

## 一、总览：32 个项目的核心发现

### 行业共识（几乎所有项目都在做的）
- **Git Worktree 隔离** — 多 agent 并行的事实标准
- **文件系统即状态** — 轻量项目用 JSON/JSONL，重量级用 SQLite
- **Hub-and-Spoke 通信** — 没有一个项目实现了真正的 P2P agent 协调
- **Prompt-as-Code** — 越来越多项目用 Markdown 定义 agent 行为而非硬编码

### 行业分歧（不同项目走了不同路线）
- **编排层**: 代码编排（Ferment/Lucentia）vs Prompt 编排（Artemis/codingbuddy）vs Hook 编排（workflow-orchestration/template）
- **状态管理**: Event Sourcing（swarm-tools/organvm）vs Snapshot（Orchestra）vs 文件信号（orc-spencer）
- **质量保证**: LLM-as-judge（template/claude-prove）vs 确定性检查（Lumina OS）vs 混合（SoulFlow）

### 你的 Orchestrator 在哪里
你已经有：Docker 运行层、Agent SDK 执行、YAML 声明式采集器、DB-first logging、三省六部治理框架、SOUL 身份系统。
你还缺：事件驱动反应层、质量门控闭环、token 预算管理、跨部门协调协议、agent 间上下文传递机制。

---

## 二、按架构维度的偷师清单

### 🏛️ A. 治理层升级（三省 → 宪法级治理）

**现状**: 三省六部有层级但缺硬约束，权限边界靠 prompt 而非机制。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P0 | **Authority Ceiling** | organvm | 定义四级权限 READ/PROPOSE/MUTATE/APPROVE，AI agent 天花板 MUTATE，APPROVE 留给朕 |
| P0 | **哈希链审计日志** | Lumina OS + organvm | run-log.jsonl 每条加 `prev_hash` (SHA-256)，从日志升级为不可篡改账本 |
| P1 | **Verify Gate 硬约束** | Conitens | 定义 non-negotiable gates（如：代码变更必须过测试才能关闭任务），任何路径都不能跳过 |
| P1 | **Typed Handoff 状态机** | Conitens | 部门间任务移交有完整生命周期 requested→started→blocked→completed→rejected |
| P1 | **工具权限剥夺做约束** | Multi-Agent Research | 编排 agent 不给 Write 权限，物理上无法越权干活，被迫委派 |
| P2 | **Gate Record 持久化** | Conitens | 每个审批决策留 JSON 记录（gate_id, decision, evidence_refs），可回溯 |
| P2 | **Immutable Base Constraints** | claude-swarm | Object.freeze 冻结安全底线，动态策略只能更严格不能更宽松 |

### 🔀 B. 调度层升级（中书省 → 意图路由引擎）

**现状**: 派单靠规则/prompt，缺乏意图识别和降级策略。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P0 | **Gateway 三路分流** | SoulFlow | 请求先分类：no-token（状态查询）/ model-direct（单轮）/ agent（多步），简单请求不走 agent loop |
| P0 | **Intent-based Routing** | Ferment | 派单抽象为 intent → department 映射，每个 intent 绑定 policy profile（low-latency/balanced/high-quality） |
| P1 | **TokenAccountant 预算降级链** | Lucentia | 每个部门日预算 + 单任务上限，超预算自动降级模型而非拒绝 |
| P1 | **Provider Cascade** | Orchestra | 一个 agent 失败 3 次自动换 provider，不是重试同一个 |
| P1 | **Seed Contract 依赖图** | organvm | 每个部门 YAML 声明 produces/consumes/subscriptions，事件路由从声明生成 |
| P2 | **Complexity Classifier** | codingbuddy | 加权关键词判断任务复杂度，简单任务跳过完整编排流程 |
| P1 | **Budget Hard Stop** | Paperclip | 月度预算 company→project→agent，超预算自动 pause + 取消 run |
| P2 | **AgentSemaphore 分级并发** | Lucentia | 按部门类型不同并发上限，全局上限兜底 |

### 🔄 C. 执行层升级（六部 → 并行隔离执行引擎）

**现状**: Agent SDK 单线程执行，缺乏并行和上下文隔离。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P0 | **Scratchpad 文件传递** | workflow-orchestration | agent 间不传文本传文件路径，`DONE\|{path}` 协议，彻底杜绝 context 膨胀 |
| P0 | **Scout-Synthesize** | orc-spencer | 编排 agent 不读源码/数据，派 scout sub-agent 侦察，自己只做综合。保护 context window |
| P1 | **Stage Pipeline + Command Catalog** | bored | workflow 拆成可配置 stage 序列，每 stage 是一个 .md prompt，扩展=加文件 |
| P1 | **Doom Loop Detection** | orc-safe | 相同 tool+input 滑动窗口重复 5 次 / 同一文件编辑 4 次 → 触发熔断 |
| P1 | **WorkerHandoff 契约** | swarm-tools | 派单三段式：contract（files_owned/success_criteria）+ context（WHY）+ escalation（卡住找谁） |
| P1 | **Atomic Task Checkout** | Paperclip | `POST /checkout` + 409 冲突放弃，防双重工作。单一分配人模型 |
| P1 | **Heartbeat Protocol** | Paperclip | 标准化 9 步心跳规范，靠 prompt 注入不硬编码 |
| P2 | **Punch-in/Punch-out** | organvm | 多 agent 并行时"打卡"声明操作区域，TTL 自动过期，资源权重限流 |
| P2 | **Wakeup Coalescing** | Paperclip | 合并重复唤醒，DB-backed 队列，防事件风暴 |
| P2 | **反应式 YAML 配置** | ComposioHQ | 事件→动作声明式配置：ci-failed → auto-retry(2) → escalateAfter(30m) |

### ✅ D. 质量层升级（质量部/吏部 → 闭环质量引擎）

**现状**: 吏部有绩效概念但缺闭环执行。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P0 | **PLAN→ACT→EVAL 循环** | codingbuddy | 循环直到 criticalCount===0 && highCount===0，达上限 fallback 回 PLAN 让人类介入 |
| P0 | **Anti-Sycophancy** | codingbuddy | 评审 prompt 禁止恭维词，必须先说问题再说优点，必须至少 3 个改进点 |
| P1 | **两层 Review** | orc-spencer | 小任务快审（bead 级）+ 大功能深审（goal 级独立 sub-agent） |
| P1 | **ACB Intent Manifest** | claude-prove | agent commit 时声明意图，按意图分组审查。Classification: explicit/inferred/speculative |
| P1 | **Negative Space** | claude-prove | 显式记录"没做但你可能关心的事"及原因，加到报告格式 |
| P2 | **并行调和确定性优先** | SoulFlow | 确定性可解的冲突不发给 LLM，只有真正的分歧才升级 |
| P2 | **Deslop 去 AI 臭味** | bored | 专门的质量工位：去过度注释、不必要防御代码、机器感命名 |
| P2 | **Novelty Policy** | SoulFlow | 阻止 agent 重试已失败路径（除非有新信息） |

### 🧠 E. 上下文与记忆层升级（SOUL → 分层记忆系统）

**现状**: SOUL 系统有 boot.md 编译产物，但缺 token 预算管理和记忆衰减。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P0 | **两级记忆 hot/extended** | Artemis | hot memory（~70 行，每次加载）+ extended memory（按需加载），精细控制 token 预算 |
| P0 | **条件式 prompt 注入** | workflow-orchestration | 不一股脑加载所有 system prompt，按需注入。boot.md 可以更细粒度 |
| P1 | **Notebook Pattern 状态外置** | claude-swarm | agent context 不是 truth，文件系统才是。context compaction 后从文件恢复 |
| P1 | **Task-Scoped Session** | Paperclip | 按 (agent_id, task_key) 存 session，跨心跳恢复上下文 |
| P1 | **Memory Supersede** | Lucentia | 新记忆与旧记忆相似度>0.90 → 旧的标记 superseded。半衰期 90 天 |
| P2 | **Learn-from-edit 反馈闭环** | Artemis | 人工修正 agent 产出 → diff 分析 → 提取通用教训 → 追加到 lessons |
| P2 | **CAFI 文件索引** | claude-prove | 为每个文件生成 routing hint，agent 查索引后再 Glob/Grep |
| P2 | **事件即学习信号** | swarm-tools | SubtaskOutcome 记录 planned vs actual，反馈给策略选择 |

### 🏗️ F. 平台层升级（Docker 底座 → 可观测编排平台）

**现状**: Docker Compose + Dashboard，缺事件总线和实时推送。

| 优先级 | 模式 | 来源 | 落地方案 |
|--------|------|------|---------|
| P1 | **四级优先级 Dispatcher** | voice-ai | critical/input/output/low 独立处理，紧急任务（告警）不被低优任务阻塞 |
| P1 | **Fan-out Collector** | voice-ai | run-log 同时写文件+DB+外部 APM，无 exporter 时 no-op |
| P1 | **Domain Pack 模式** | Lumina OS | 核心引擎零领域代码，部门行为通过配置+动态加载注入 |
| P2 | **确定性模板 fallback** | Lumina OS | LLM 不可用时系统仍能运转（预定义 action→response 映射） |
| P2 | **Canary/Shadow Prompt 部署** | Ferment | prompt 迭代时 canary 分流，shadow 模式对比新旧效果 |
| P2 | **Sub-run 追踪** | bored | 每个 stage 独立记录状态/耗时/成本，精确定位问题阶段 |

---

## 三、推荐实施路径

### Phase 1: 地基（治理 + 日志）
1. run-log.jsonl 加 prev_hash 哈希链
2. Authority Ceiling 四级权限
3. Gateway 三路分流（简单请求不走 agent loop）

### Phase 2: 骨架（调度 + 执行）
4. Intent-based routing + policy profiles
5. Scratchpad 文件传递 + DONE|{path} 协议
6. PLAN→ACT→EVAL 质量闭环

### Phase 3: 肌肉（并行 + 预算）
7. TokenAccountant 预算降级链
8. Scout-Synthesize 模式
9. Doom Loop Detection

### Phase 4: 神经（记忆 + 反馈）
10. 两级记忆 hot/extended
11. Learn-from-edit 反馈闭环
12. Canary/Shadow prompt 部署

---

## 四、一句话总结每个维度

| 维度 | 核心升级 | 一句话 |
|------|---------|--------|
| 治理 | 从"请遵守规则"到"物理上不能违规" | hooks are enforcement, not instructions |
| 调度 | 从"规则派单"到"意图路由+自动降级" | intent → capability → policy profile |
| 执行 | 从"串行独占"到"并行隔离+上下文保护" | scratchpad over stdout, scout before act |
| 质量 | 从"事后评估"到"实时循环+量化退出" | loop until critical=0, anti-sycophancy |
| 记忆 | 从"全量加载"到"分层按需+自动淘汰" | hot/extended, supersede stale memories |
| 平台 | 从"Docker+日志"到"优先级事件+可观测" | priority dispatch, fan-out collect |
