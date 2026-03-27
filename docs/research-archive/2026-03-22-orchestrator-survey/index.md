# Orchestrator 偷师研究 — 2026-03-22

共研究 **32 个项目**，全部完成。按含金量分级：

## 🏆 S 级（必偷，直接影响架构演进）

| # | 项目 | 核心偷点 | 文件 |
|---|------|---------|------|
| 1 | **Lumina OS** | Domain Pack 可插拔领域包 / 哈希链审计日志 / SLM 预消化上下文 / 确定性模板 fallback / 检查中间件管道 | [lumina-os.md](lumina-os.md) |
| 2 | **Ferment** | Intent-based routing + policy profiles / 质量感知重试 / Canary/Shadow prompt 部署 / 内建训练管线 / Effect scope 隔离 | [ferment.md](ferment.md) |
| 3 | **organvm-engine** | Seed Contract 声明式依赖图 / Punch-in/Punch-out 协调 / Authority Ceiling / 哈希链 EventSpine / Tool Checkout Line | [organvm-engine.md](organvm-engine.md) |
| 4 | **SoulFlow-Orchestrator** | Gateway 三路分流 / Role/Protocol 策略编译 / Phase Loop + Critic Gate / Novelty Policy / 并行调和确定性优先 | [soulflow.md](soulflow.md) |
| 5 | **ComposioHQ/agent-orchestrator** | 八槽插件系统 / Orchestrator 即 Agent / 反应式 YAML 生命周期 / LLM 递归任务分解 | [composio.md](composio.md) |
| 6 | **Paperclip** | Atomic Checkout / Heartbeat Protocol / Budget Hard Stop / Wakeup Coalescing / Org Chart 委派 | [paperclip.md](paperclip.md) |

## 🥇 A 级（高价值，特定模式直接可用）

| # | 项目 | 核心偷点 | 文件 |
|---|------|---------|------|
| 6 | **spencermarx/orc** | Scout-Synthesize / 两层 Review / 文件信号协议 / Adapter pattern / YOLO 模式 | [orc-spencer.md](orc-spencer.md) |
| 7 | **claude-code-workflow-orchestration** | 约束即能力 / Scratchpad 文件传递 / DONE\|{path} 协议 / Token 三层压缩 / 条件式 prompt 注入 | [workflow-orchestration.md](workflow-orchestration.md) |
| 8 | **claude-prove** | ACB Intent Manifest / Negative Space / Comprehend 苏格拉底问答 / CAFI 文件索引 / Hook-driven reporter | [claude-prove.md](claude-prove.md) |
| 9 | **claude-swarm** | Notebook Pattern 状态外置 / Competitive Planning / Frustration Detection / Protocol Governance / Git Snapshot 回滚 | [claude-swarm.md](claude-swarm.md) |
| 10 | **Conitens** | Verify Gate 硬约束 / Typed Handoff 状态机 / Provider Manifest / Room 概念 / Append-only 脱敏事件 | [conitens.md](conitens.md) |
| 11 | **Lucentia** | TokenAccountant 预算降级链 / AgentSemaphore 分级并发 / Memory Supersede / 结构化辩论引擎 / Trigger DSL | [lucentia.md](lucentia.md) |
| 12 | **codingbuddy** | PLAN→ACT→EVAL 循环 / Anti-Sycophancy / Wave Splitter 图着色 / Complexity Classifier / Agent Profile JSON Schema | [codingbuddy.md](codingbuddy.md) |

## 🥈 B 级（有亮点，选择性借鉴）

| # | 项目 | 核心偷点 | 文件 |
|---|------|---------|------|
| 13 | **safethecode/orc** | Tournament Optimizer / Doom Loop Detection / WorkerBus artifact 广播 / DAG + Phase 执行 | [orc-safe.md](orc-safe.md) |
| 14 | **Orchestra** | Claim-Execute-Release / Reconciliation Loop / Provider Cascade / Stall Detection | [orchestra.md](orchestra.md) |
| 15 | **Tmux-Orchestrator** | Self-scheduling / LEARNINGS.md 集体记忆 / Hub-and-Spoke 通信 | [tmux-orch.md](tmux-orch.md) |
| 16 | **Ludwig-AI** | Git Worktree 沙箱 / Model Fallback Chain / NEEDS_REVIEW 审核协议 / 流式响应持久化 | [ludwig.md](ludwig.md) |
| 17 | **project-artemis** | Prompt-as-SOP / 两级记忆（hot/extended）/ Learn-from-edit 反馈闭环 / 跨 Skill 连锁规则 | [artemis.md](artemis.md) |
| 18 | **voice-ai (Rapida)** | 四级优先级 Dispatcher / contextID 旋转中断 / Fan-out Collector / Phase-based Disconnect | [voice-ai.md](voice-ai.md) |

## 🥉 C 级（概念有趣，实现不足或领域偏远）

| # | 项目 | 核心偷点 | 文件 |
|---|------|---------|------|
| 19 | **cursor-cli-heavy** | Tag-based Structured Output / AI 决定并行度 / Synthesis 显式阶段 | [cursor-cli.md](cursor-cli.md) |
| 20 | **aintandem-pm** | Workflow→Phase→Step 三级模型 / Sync+Async 双模式 / "信任即环境设计" | [aintandem.md](aintandem.md) |
| 21 | **giterm** | Session Manager + Command Channel / FSD 前端分层 / 实例迁移而非销毁 | [giterm.md](giterm.md) |

## ❌ D 级（空壳或无实质内容）

| # | 项目 | 状态 |
|---|------|------|
| 22 | **Integration-Registry** | 270+ 空 Markdown 文件，零代码 |

## 补充文件

- [swarm-tools.md](swarm-tools.md) — A 级，Event Sourcing + WorkerHandoff 契约
- [batch-final.md](batch-final.md) — 最后一批 7 个（bored A / template A / 其余 B-C）
- [agenthalo.md](agenthalo.md) — B 级，Rust 98K 行 StreamAdapter + PipeTransform DAG
- [geny.md](geny.md) — B 级，LangGraph 弹性四件套
- [paperclip.md](paperclip.md) — S 级，AI 公司控制平面 31K stars

## 核心交付物

- **[STEAL-SHEET.md](STEAL-SHEET.md)** — 偷师总纲，6 维度 46 个模式 12 步实施路径
- **[taxonomy.md](taxonomy.md)** — 分类法，32 个项目按 6 个架构维度归类
