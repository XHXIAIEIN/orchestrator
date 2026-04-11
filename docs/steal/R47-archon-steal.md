# R47 — Archon Steal Report

**Source**: https://github.com/coleam00/Archon | **Stars**: 15.9K | **License**: MIT
**Date**: 2026-04-11 | **Category**: Complete Framework

## TL;DR

Archon 是一个围绕 Claude Code 构建的远程编排平台，核心创新在于 **YAML DAG 工作流引擎** + **多平台适配器** + **worktree 隔离** + **对抗式开发循环**。它解决的问题是：如何让 AI coding agent 在远程、多平台（Slack/Telegram/Discord/Web）环境下可控地执行复杂多步任务。

与 Orchestrator 的关系：Archon 是我们在 "Claude Code plugin" 路线上的直接参照物——它把我们用 hooks/skills/agents 做的事情，包装成了一个可部署的产品形态。

## Architecture Overview

```
Layer 4: Platform Adapters (Slack / Telegram / Discord / Web / CLI)
         ↓ IPlatformAdapter interface
Layer 3: Orchestrator Agent (message routing, command parsing, session state)
         ↓ handleMessage() → deterministic commands | AI routing
Layer 2: Workflow Engine (DAG executor, condition evaluator, loop nodes, approval gates)
         ↓ YAML workflow definitions → node execution → variable substitution
Layer 1: Client Abstraction (Claude SDK / Codex SDK via factory pattern)
         ↓ AsyncGenerator<MessageChunk> streaming
Layer 0: Infrastructure (SQLite/Postgres, git worktree isolation, env security)
```

**Monorepo 结构** (7 packages):
- `core` — orchestrator agent, prompt builder, clients, DB, security utils
- `workflows` — DAG executor, schemas, condition evaluator, hooks
- `isolation` — worktree provider, resolver, PR state
- `adapters` — Slack, Telegram, Discord adapters
- `server` — HTTP API, web adapter, SSE streaming
- `web` — React dashboard
- `cli` — CLI interface
- `paths` — path resolution, logger, update checker

## Steal Sheet

### P0 — Must Steal (6 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **DAG Workflow Engine** | 拓扑排序分层执行，Promise.allSettled 并行层，6种节点类型（command/prompt/bash/loop/approval/cancel/script），trigger_rule 控制依赖行为 | 我们没有工作流引擎，任务是线性的 | 不需要完整引擎，但 **DAG 节点 + 条件分支 + 审批门** 的设计模式可用于 skill 编排 | ~4h |
| **Approval Gate + Rejection Loop** | workflow 暂停等待用户 approve/reject，reject 时带 $REJECTION_REASON 回注 on_reject prompt，max_attempts 防无限循环 | 我们的 skill 没有暂停/恢复机制 | 在 Telegram bot 的任务派单流程中加入审批门 | ~2h |
| **Adversarial Development Loop** | GAN 启发的三角色（Negotiator → Generator → Evaluator），JSON 状态机驱动，硬性 7/10 通过阈值，evaluator 只读不改 | 完全没有对抗式开发 | 适配为 **adversarial-review skill**：generator 写代码，evaluator 打分+攻击，失败重试 | ~3h |
| **Fresh Context Loop + Disk State** | 循环节点每次迭代 fresh_context=true，状态通过磁盘文件（progress.txt, prd.json）传递而非上下文窗口 | 我们的 agent 依赖上下文窗口，长任务会 context 溢出 | 长任务 skill 采用 **disk-state pattern**：每次迭代从磁盘读状态，写进展到 progress.txt | ~2h |
| **Env Leak Scanner** | 扫描工作目录的 .env 文件检测敏感 key（ANTHROPIC_API_KEY 等），因为 Bun 自动加载 CWD 的 .env 会绕过 allowlist | 我们的 Docker 环境有 .env 但没有泄漏检测 | 在 guard hook 中加入 env 变量泄漏检测 | ~1h |
| **Prime Context Injection** | /prime 命令读取 CLAUDE.md + 关键入口文件 + 包结构，输出 <300 字可扫描摘要；4个领域变体（backend/frontend/isolation/workflows） | 我们没有系统的 context priming | 为 Orchestrator 创建 **/prime skill** + 领域变体（docker/channel/soul） | ~1.5h |

### P1 — Worth Doing (8 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Confidence-Based Filtering** | code-reviewer 等 agent 对每个发现打 0-100 信心分，只输出 80+ 的 | 我们的 code-review agent 没有信心阈值 | agent 定义中加入 confidence threshold | ~1h |
| **Handoff Document** | 结构化会话交接文档：Goal/Completed/In-Progress/Key Decisions/Dead Ends/Files Changed/Current State/Context for Next Session | 我们用 remember skill 但不够结构化 | 创建 /handoff skill 生成标准交接文档 | ~1.5h |
| **Smart PR Review Routing** | haiku 分类器判断 PR 类型，条件路由到不同 review agent，`trigger_rule: one_success` 提前启动综合 | 我们的 PR review 是全量跑 | 加入分类前置步骤，跳过不相关的 agent | ~2h |
| **Message Splitting + Markdown Fallback** | 两轮拆分（段落→行），平台限长自适应，MarkdownV2 失败降级纯文本 | 我们的 Telegram bot 消息拆分比较粗暴 | 采用 paragraph-first splitting + graceful fallback | ~1h |
| **Conversation Lock Manager** | 非阻塞锁 + per-conversation 队列 + 全局并发上限，返回 started/queued-conversation/queued-capacity | 我们的 bot 没有并发控制 | conversation_lock 模块 | ~2h |
| **Session State Machine** | 5 种 transition trigger，parent_session_id 链表形成审计轨迹，plan-to-execute 自动创建新 session | 我们没有 session 概念 | 在 task 管理中引入 session 审计 | ~3h |
| **Error Classification (FATAL/TRANSIENT)** | 模式匹配错误信息分类，FATAL 不重试，TRANSIENT 指数退避，per-node retry 配置 | 我们的错误处理是 catch-all | executor 层加入 error taxonomy | ~2h |
| **Rule Scoping by Path** | 每个 rule 文件明确适用路径（`packages/adapters/**/*.ts`），不是全局笼统规则 | 我们的 CLAUDE.md 规则是全局的 | 考虑拆分为 per-module 规则 | ~1h |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Codex Client Fallback** | 模型不可用时自动降级（gpt-5.3-codex → gpt-5.2-codex） | 我们单模型，不需要 fallback |
| **Background Workflow Event Bridge** | worker 会话事件通过 SSE bridge 实时传到 parent 会话 | 需要 web UI 前端，我们暂时不做 |
| **Worktree Adoption** | 检测 skill 创建的 worktree 并自动 adopt，而不是重新创建 | 我们的隔离方式不同（Docker） |
| **Thread Context Inheritance** | 子对话继承父对话的 codebase context | 我们的 Telegram bot 还没有线程概念 |
| **Credential Sanitizer** | 正则替换输出中的 GH_TOKEN 值 + URL embedded credentials | 我们在 Docker 内部，暴露风险较低 |

## Comparison Matrix (P0 Patterns)

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| **工作流编排** | YAML DAG + 拓扑排序 + 6种节点类型 | 线性 skill 执行，无 DAG | **Large** | 提取 DAG 概念用于 skill 编排设计 |
| **审批门** | approval node + on_reject + max_attempts | 无暂停/恢复 | **Large** | 在 TG bot 任务流中实现 |
| **对抗式开发** | 三角色状态机 + 7/10 硬门槛 | 无 | **Large** | 作为新 skill 实现 |
| **长任务状态** | disk-based progress.txt + fresh context loop | 依赖上下文窗口 | **Medium** | 长 skill 任务采用磁盘状态模式 |
| **Env 泄漏检测** | 文件扫描 + allowlist + 3种 context error | 无 | **Medium** | guard hook 扩展 |
| **Context Priming** | /prime + 4 领域变体 | 无系统化 priming | **Medium** | 创建 /prime skill |

## Gaps Identified

| Dimension | Their Coverage | Our Coverage | Gap |
|-----------|---------------|-------------|-----|
| **Security / Governance** | Env leak scanner, credential sanitizer, subprocess env allowlist, path traversal validation | guard hook (拦截命令), audit hook (日志) | 缺少运行时 env 泄漏检测和凭证清洗 |
| **Memory / Learning** | Handoff documents, progress.txt pattern extraction, session audit trail | memory 系统 + remember skill | 缺少结构化交接和 per-task 进展跟踪 |
| **Execution / Orchestration** | DAG engine, 6 node types, condition evaluator, variable substitution | 线性 skill/agent 执行 | 缺少 DAG 编排、条件分支、审批门 |
| **Context / Budget** | Fresh context loops, batch chunk truncation (last 20 + 200 total), prompt builder | boot.md + skill routing | 缺少显式 context 管理策略 |
| **Failure / Recovery** | FATAL/TRANSIENT classification, exponential backoff, retry per node, stale env detection | stuck detector (旧), 无分类重试 | 缺少 error taxonomy 和结构化重试 |
| **Quality / Review** | Confidence scoring (80+), 5 parallel review agents, adversarial evaluation, validation pyramid | verification gate, code-review agent | 缺少信心过滤和对抗式评估 |

## Adjacent Discoveries

1. **telegramify-markdown** — 专门处理 Telegram MarkdownV2 转换的库，解决了我们 TG bot 的 markdown 格式问题
2. **Bun 的 `import ... with { type: 'file' }` 嵌入** — 可以把 CLI 脚本嵌入编译后的二进制中
3. **Slack Bolt + Socket Mode** — 比 webhook 更简单的 Slack bot 接入方式
4. **`<promise>SIGNAL</promise>` 完成信号** — 用 XML 标签包裹信号防止误触发，比纯文本匹配更可靠
5. **Ralph Story-Driven Development** — 用 prd.json 的 user story 结构驱动实现，每个 story 有 dependsOn 和 passes 字段，进展通过 progress.txt 的 "Codebase Patterns" 段累积学习

## Meta Insights

### 1. Archon 验证了 "Claude Code Plugin 即产品" 路线

Archon 本质上就是把 `.claude/` 目录（agents + skills + commands + rules）包装成一个可部署的服务。它的核心价值不在 TypeScript 代码，而在那些精心设计的 **workflow YAML** 和 **command markdown**。这验证了我们 R46 后的认知：真正有价值的是 prompt 工程和工作流设计，不是基础设施代码。

### 2. 状态外化是长任务的银弹

Archon 所有长任务（PIV loop, Ralph, Adversarial Dev）都用同一个模式：**fresh context + disk state**。每次迭代从磁盘读取完整状态（plan.md, progress.txt, prd.json, state.json），执行一步，写回磁盘。这完全绕过了 context window 限制，使得 15-60 次迭代的工作流成为可能。我们的长任务 skill 应该采用这个模式。

### 3. 对抗式质量保证比自我审查有效

Adversarial Dev 的 Generator/Evaluator 分离是一个深刻洞见：让写代码的 agent 自己评审代码，本质上是自我审查，存在结构性 sycophancy。分离角色 + 硬性评分阈值 + evaluator 只读权限，从结构上消除了这个问题。这比我们目前的 verification gate（同一个 agent 自己验证自己）更可靠。

### 4. 条件路由 = 效率 × 质量

Smart PR Review 的 haiku 分类器 + 条件路由模式很巧妙：用便宜的模型决定哪些贵的 agent 需要运行。这比"全部跑一遍"既省 token 又减少噪音。分类器本身成本极低（几百 token），但能省掉 3-4 个不必要的 agent 调用。

### 5. "Prime" 是被低估的效率工具

在每次对话开始时系统化地注入项目上下文（结构、规则、入口点），比依赖 CLAUDE.md 被动加载更有效。Prime 是主动的、领域特化的、输出可扫描的。我们的 boot.md 做了类似的事，但缺少领域变体和标准化格式。
