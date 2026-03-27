# 偷师项目分类法

按**核心关注点**分 6 类。同一项目可能横跨多类，但只归入最核心的那个。

---

## 🏛️ A. 治理与信任层（"朕怎么管 AI"）

**关注点**: 权限边界、审计追溯、审批门控、安全约束

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **Lumina OS** | Domain Physics 不可变规则 / 哈希链审计 / 策略承诺门 / 检查中间件 | S |
| **organvm-engine** | Authority Ceiling / Seed Contract / Punch-in 协调 / Tool Checkout | S |
| **Conitens** | Verify Gate 硬约束 / Typed Handoff 状态机 / Gate Record / 三层审批 | A |
| **claude-swarm** | Protocol Governance / Immutable Base Constraints / Fail-Closed | A |

**对 Orchestrator 的意义**: 三省六部的"治理层"——谁能做什么、谁审批谁、怎么追溯。

---

## 🔀 B. 调度与路由层（"活儿给谁干"）

**关注点**: 意图识别、能力匹配、优先级调度、负载均衡、降级策略

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **Ferment** | Intent-based routing / Policy profiles / Quality-aware retry / Canary+Shadow | S |
| **SoulFlow** | Gateway 三路分流 / Role+Protocol 编译 / ToolIndex 词法检索 | S |
| **ComposioHQ** | 八槽插件系统 / LLM 递归分解 / 反应式 YAML | S |
| **Lucentia** | TokenAccountant 降级链 / AgentSemaphore / Trigger DSL | A |
| **Orchestra** | Claim-Execute-Release / Provider Cascade / Reconciliation Loop | B |

**对 Orchestrator 的意义**: 三省六部的"中书省"——怎么分析任务、派给哪个部、怎么降级重试。

---

## 🔄 C. 执行与编排层（"怎么并行干活"）

**关注点**: 多 agent 并行、worktree 隔离、DAG 依赖、状态机、通信

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **spencermarx/orc** | Scout-Synthesize / 两层 Review / 文件信号协议 / 四层层级 | A |
| **workflow-orchestration** | 约束即能力 / Scratchpad 传递 / Wave 并行 / Token 三层压缩 | A |
| **safethecode/orc** | Tournament Optimizer / Doom Loop Detection / WorkerBus / DAG+Phase | B |
| **Ludwig-AI** | Git Worktree 沙箱 / Model Fallback Chain / Semaphore 并发 | B |
| **Tmux-Orchestrator** | Self-scheduling / Hub-and-Spoke / tmux 作为 runtime | B |
| **cursor-cli-heavy** | Fan-out/Fan-in / AI 决定并行度 / Synthesis 显式阶段 | C |

**对 Orchestrator 的意义**: 六部的"执行层"——怎么隔离、怎么并行、怎么传递上下文、怎么防死循环。

---

## ✅ D. 质量与验证层（"怎么保证不出烂活"）

**关注点**: 质量门控、代码审查、anti-sycophancy、intent manifest、反馈闭环

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **claude-prove** | ACB Intent Manifest / Negative Space / Comprehend 苏格拉底 / 5 阶段验证 | A |
| **codingbuddy** | PLAN→ACT→EVAL 循环 / Anti-Sycophancy / Wave Splitter / Complexity Classifier | A |
| **SoulFlow** | Phase Loop + Critic Gate / Novelty Policy / 并行调和确定性优先 | (S, 已归 B 类) |

**对 Orchestrator 的意义**: 三省六部的"质量部/吏部"——怎么评审、怎么回炉、怎么防 AI 自作主张。

---

## 🧠 E. 上下文与记忆层（"怎么不让脑子爆"）

**关注点**: token 管理、状态持久化、记忆衰减、context 隔离

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **workflow-orchestration** | DONE\|{path} 协议 / Token 三层压缩 / 条件式注入 | (A, 已归 C 类) |
| **claude-swarm** | Notebook Pattern 状态外置 / Confidence Scoring | (A, 已归 A 类) |
| **project-artemis** | 两级记忆 hot/extended / Learn-from-edit 闭环 / Sync manifest | B |
| **Lucentia** | Memory Supersede / Importance decay 半衰期 | (A, 已归 B 类) |

**对 Orchestrator 的意义**: SOUL 系统的进化——怎么管记忆、怎么省 token、怎么跨 session 不丢状态。

---

## 🏗️ F. 平台与基础设施层（"底座怎么搭"）

**关注点**: 运行时架构、多渠道接入、Dashboard、事件总线

| 项目 | 核心贡献 | 评级 |
|------|---------|------|
| **SoulFlow** | 9 agent 后端 / CircuitBreaker / 多渠道 / 141 节点 workflow | (S, 已归 B 类) |
| **aintandem-pm** | Docker 沙盒 / Workflow→Phase→Step / WebSocket 分连接 | C |
| **voice-ai** | 四级优先级 Dispatcher / Fan-out Collector / contextID 旋转 | B |
| **giterm** | Session Manager + Command Channel / Tauri 跨平台 | C |

**对 Orchestrator 的意义**: Docker 运行层 + Dashboard + 事件总线的参考实现。

---

## 新增归类（最后 7 个）

| 项目 | 归入 | 评级 |
|------|------|------|
| **swarm-tools** | C 执行层（Event Sourcing + Actor Model 通信原语） | A |
| **bored** | C 执行层 + D 质量层（看板驱动 Stage Pipeline + Deslop） | A |
| **claude-code-project-template** | A 治理层 + E 记忆层（Hook 执法 + Plan Mode 读写隔离） | A |
| **Claude Multi-Agent Research** | A 治理层（工具权限剥夺做约束） | B |
| **mozaik** | B 调度层（Zod Schema AI 规划 + Autonomy Slider） | B |
| **breeze** | F 基础设施（Codex app-server WebSocket 协议） | B |
| **agentic-ai-systems** | 参考资料（Obsidian 知识库，非代码） | C |
