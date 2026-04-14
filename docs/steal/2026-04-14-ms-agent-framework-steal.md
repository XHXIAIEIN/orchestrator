# R57 — Microsoft Agent Framework Steal Report

**Source**: https://github.com/microsoft/agent-framework | **Stars**: 9.4k | **License**: MIT
**Date**: 2026-04-14 | **Category**: Complete framework
**Lineage**: AutoGen (57.1k stars) + Semantic Kernel (27.7k stars) → MAF 1.0 (released 2026-04-02)

---

## TL;DR

Microsoft Agent Framework 1.0 是 AutoGen + Semantic Kernel 合并后的统一产物，2025-10 进入 public preview，2026-04-02 发布 GA。核心赌注是：**显式图执行 + 中间件管道 + 类型安全** 三者组合解决 LLM agent 的不可预测性问题。最值得偷的是三层中间件系统（agent/function/chat 三个插入点）和 Pregel 超步执行模型；最弱的地方是错误恢复语义不清晰、没有自主学习回路。

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT LAYER                              │
│  Azure Foundry Managed │ Azure Durable Functions │ Local Harness │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                    ORCHESTRATION LAYER                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              WORKFLOW ENGINE                             │    │
│  │  WorkflowBuilder → Directed Graph → Superstep Executor   │    │
│  │                                                          │    │
│  │  Patterns: Sequential │ Concurrent │ Handoff             │    │
│  │           │ GroupChat │ Magentic (LLM orchestrator)      │    │
│  │                                                          │    │
│  │  Execution: Pregel BSP (Bulk Synchronous Parallel)       │    │
│  │  - Each superstep: collect → route → execute (parallel)  │    │
│  │  - Synchronization barrier between supersteps            │    │
│  │  - Checkpoint at superstep boundaries                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  EXECUTOR (processing unit):                                     │
│    Agent Executor │ Function Executor                            │
│    @handler decorator + type-safe message routing                │
│    WorkflowContext: send_message() │ yield_output()              │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                      AGENT LAYER                                 │
│                                                                  │
│  Base: Agent (Python) / AIAgent (C#)                             │
│  Protocol: SupportsChatGetResponse / IChatClient                 │
│                                                                  │
│  Agent Types:                                                    │
│    ChatClientAgent — wraps any IChatClient                       │
│    FoundryAgent — Azure AI Foundry backend                       │
│    A2AAgent — remote agent proxy via A2A protocol                │
│    Custom BaseAgent — full control                               │
│                                                                  │
│  Execution Loop: input → [middleware chain] → LLM → tool call?   │
│    → [function middleware] → tool exec → back to LLM → output    │
│                                                                  │
│  MIDDLEWARE PIPELINE (3 layers):                                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Agent Middleware  ← wraps entire agent.run()           │     │
│  │  └─ Function Middleware ← wraps each tool invocation   │     │
│  │     └─ Chat Middleware ← wraps each LLM call           │     │
│  │         (runs inside tool-calling loop, multi-trigger)  │     │
│  └────────────────────────────────────────────────────────┘     │
│  Scope: agent-level (persistent) │ run-level (per-invocation)   │
│  Termination: raise MiddlewareTermination, set context.result    │
│                                                                  │
│  SESSION / STATE:                                                │
│    AgentSession: session_id + service_session_id + state dict    │
│    History: local in-memory │ service-managed (Foundry/OAI)      │
│    Serialization: to_dict() / from_dict()                        │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                      TOOL / EXTENSION LAYER                      │
│                                                                  │
│  Function Tools: @tool(approval_mode=...) decorator              │
│  Approval: human-in-the-loop gate, pause/resume                  │
│  MCP: Hosted MCP (Foundry) │ Local MCP (any provider)            │
│  Code Interpreter │ File Search │ Web Search                     │
│  Agent-as-Tool: agent.as_tool() — composition primitive          │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                   PROVIDER / INFERENCE LAYER                     │
│  OpenAI │ Azure OpenAI │ Foundry │ Anthropic │ Bedrock │ Ollama  │
│  GitHub Copilot │ Gemini (preview)                               │
│  Unified: Microsoft.Extensions.AI (IChatClient interface)        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Steal Sheet

### P0 — 必抄

**1. 三层中间件分离设计**
MAF 把拦截点分成三层，粒度精确：
- `AgentMiddleware`：包整个 `agent.run()`，看输入输出、可终止
- `FunctionMiddleware`：包每次工具调用，能改参数/结果/终止循环
- `ChatMiddleware`：包每次 LLM 请求（注意：在 tool-calling 循环内每次都触发）

Orchestrator 现有的 `transformer_pipeline.py` 和 `gate_chain.py` 是单层概念，缺少在工具调用粒度上的钩子。`tool_call_recovery.py` 只做错误恢复，不是通用中间件。

抄法：在 `executor.py` 里加三层钩子点，用 `call_next` 链式调用，支持 agent/function/chat 三个独立注册点。

**2. 中间件执行顺序语义的显式文档化**
MAF 明确说明：`agent-level [A1,A2] + run-level [R1,R2] → A1→A2→R1→R2→Agent→R2→R1→A2→A1`

这是洋葱模型，但 MAF 做了"agent-level wraps run-level"的双层作用域，让持久策略（安全/合规）和一次性定制（单次请求 debug）分离。Orchestrator 目前没有这个两级注册机制。

**3. Agent-as-Tool 组合原语**
`agent.as_tool()` 一行把任何 agent 变成另一个 agent 的工具，实现递归组合。这比 Orchestrator 现有的 `task_handoff.py` 更轻量——不需要全量 dispatch，只是函数调用包装。

**4. Pregel BSP 超步模型**
工作流执行用 Bulk Synchronous Parallel：
- 每个超步内所有 executor 并行
- 超步边界是同步屏障，也是 checkpoint 点
- 确定性执行：相同输入总是相同顺序

相比之下 Orchestrator 的 `plan_executor.py` 是线性顺序执行或手动并发，没有系统性的 checkpoint 语义。

**5. MiddlewareTermination 显式终止语义**
设置 `context.result` 然后 raise `MiddlewareTermination` — 不是通过返回值信号，而是通过异常精确终止链条。比返回 None 或特殊标记更清晰。

### P1 — 值得参考

**6. 结构化 WorkflowContext**
`WorkflowContext` 有 `send_message()` 和 `yield_output()` 两个明确的输出通道。消息流和最终输出分离，避免 executor 误把中间消息当输出。

**7. YAML 声明式 agent 定义**
`declarative-agents/` 目录支持 YAML 定义 agent，降低配置成本。Orchestrator 的 department manifest 思路类似但耦合更深。

**8. 工具审批 (approval_mode)**
`@tool(approval_mode="always_require")` 在工具粒度上做 human-in-the-loop。比 Orchestrator 的 `approval.py` 更精细（当前是全局会话级）。

**9. A2A 协议代理**
`A2AAgent` 把远程 agent 当本地 agent 用，跨系统调用透明化。Orchestrator 没有标准化的跨边界 agent 通信协议。

### P2 — 参考即可

- OpenTelemetry 原生集成（Orchestrator 有自己的 event_stream）
- 会话序列化 `to_dict/from_dict`（Orchestrator 有 SQLite 持久化）
- 类型安全 message routing（Python typing 系统做的，Orchestrator 更动态）

---

## Architecture Comparison

### Orchestrator vs MAF — 层对层

| 维度 | Orchestrator | MAF |
|------|-------------|-----|
| **核心抽象** | `executor.py` + `dispatcher.py` + `governor.py` | `Agent` + `WorkflowBuilder` + `Orchestration` |
| **执行模型** | 事件驱动 + 调度队列 (Governor loop) | Pregel BSP 超步 (workflow) + 同步 run() (single agent) |
| **多 agent 协作** | `group_orchestration.py` + 部门系统 | 5 种内置模式 (sequential/concurrent/handoff/groupchat/magentic) |
| **中间件/钩子** | `gate_chain.py` + `lifecycle_hooks.py` (单层) | 三层分离 (agent/function/chat)，两级作用域 |
| **状态管理** | `session_manager.py` + SQLite events.db | `AgentSession` + 可插拔后端 (local/service-managed) |
| **工具系统** | `tools.py` + `function_catalog.py` + MCP | `@tool` 装饰器 + 7 种工具类型 + MCP |
| **错误恢复** | `tool_call_recovery.py` + `resilient_retry.py` | 中间件层 + `MiddlewareTermination`（细节薄弱）|
| **观测性** | `event_stream.py` + events.db + channel | OpenTelemetry 原生 |
| **自主演化** | `apo.py` + `growth_loops.py` + eval 框架 | 无 |
| **记忆系统** | `knowledge_graph.py` + vector store + memory files | 可插拔 context providers（基础） |
| **协议互通** | 无标准跨边界协议 | A2A + MCP |
| **部署** | Docker + local daemon | Foundry / Azure Functions / Local |

### 关键差异分析

**MAF 赢在**：
1. 中间件粒度。三层独立钩子比 Orchestrator 的单层更精确，function-level 拦截是 Orchestrator 没有的。
2. 多 agent 编排的内置标准化。5 种模式文档清晰，Orchestrator 的 `group_orchestration.py` 是自制实现，没有 Magentic 这种动态协调器模式。
3. 类型安全的 workflow。Pregel 模型提供编译期验证，Orchestrator 是运行时动态路由。
4. 工业级可操作性。A2A + MCP + OpenTelemetry 覆盖了跨系统场景。

**Orchestrator 赢在**：
1. 自主演化能力。`apo.py`、`growth_loops.py`、eval 框架 — MAF 完全没有。
2. 主动观测。采集器 + events.db + Governor 形成的闭环让 Orchestrator 能主动感知和响应，MAF 是被动框架。
3. 知识图谱 + 长期记忆。MAF 的 context providers 只是基础多轮历史，Orchestrator 有 vector store + 知识图谱。
4. 个性化 identity 系统。MAF 是工具框架，没有身份概念。

---

## Comparison Matrix

| 维度 | MAF 得分 | Orchestrator 得分 | 差距 |
|------|---------|-----------------|------|
| 架构层次清晰度 | 9 | 7 | MAF +2（层边界更清晰）|
| 多 agent 编排广度 | 9 | 6 | MAF +3（5种内置模式）|
| 中间件/钩子系统 | 9 | 5 | MAF +4（三层分离）|
| 工具生态 | 8 | 7 | MAF +1 |
| 状态/会话管理 | 7 | 8 | Orch +1（SQLite 持久化更成熟）|
| 错误恢复语义 | 5 | 7 | Orch +2（retry/recovery 更完整）|
| 自主演化 | 0 | 9 | Orch +9（MAF 没有）|
| 主动感知 | 0 | 9 | Orch +9（MAF 是被动框架）|
| 长期记忆 | 4 | 8 | Orch +4 |
| 可观测性标准化 | 8 | 5 | MAF +3（OTel 原生）|
| 跨系统互通 | 8 | 3 | MAF +5（A2A + MCP）|
| 部署灵活性 | 8 | 6 | MAF +2 |

---

## Gaps

### Orchestrator 的真实差距（需要补的）

**Gap 1: Function-level 中间件钩子**
最高优先级。目前 `tool_call_recovery.py` 只做错误恢复，不是通用中间件。没有在每次工具调用前后注入自定义逻辑的标准方法。

补法：在 `executor.py` / `tools.py` 的 tool invocation 路径上加 `function_middleware_chain`，参考 MAF 的 `FunctionInvocationContext`。

**Gap 2: Workflow 显式图执行**
Orchestrator 的多步骤任务依赖 `plan_executor.py` 线性展开，没有图结构。遇到需要并行分支然后汇聚的模式（fan-out/fan-in）就要手动写胶水代码。

补法：参考 MAF 的 `WorkflowBuilder` + 超步模型，在 `plan_executor.py` 或新建 `workflow_engine.py` 里加图执行支持，不需要完整 Pregel，先支持 fan-out/barrier 就够用。

**Gap 3: 跨边界 agent 通信**
Orchestrator 没有标准协议接入外部 agent。现在如果要调用另一个系统的 agent，只能走 API 封装工具，丢失 agent 语义。

补法：参考 MAF 的 A2A proxy 模式，`agent_client.py` 加 A2A 协议支持，让外部 agent 作为本地 agent 使用。

**Gap 4: 工具审批粒度**
`approval.py` 是会话级审批，不能在工具维度精细控制。MAF 的 `approval_mode="always_require"` 可以精确到每个函数。

### MAF 的真实差距（不用抄的方向）

- 没有自主演化（Orchestrator 的护城河）
- 没有主动观测和 proactive 行为
- 错误恢复文档模糊，没有 retry 策略规范
- 没有长期记忆语义，context providers 只是多轮历史
- 严重依赖 Azure 生态（Foundry），离 Azure 就弱很多

---

## Adjacent Discoveries

**Magentic-One 模式**：有独立的 Manager agent 做动态任务规划和 agent 选择，类似 Orchestrator 的 Governor，但 Magentic Manager 是 LLM-driven 的动态调度，而 Governor 是规则/状态机 driven。值得对比研究。

**Declarative Agents (YAML)**：在 `declarative-agents/` 目录下，支持不写代码定义 agent。Orchestrator 的 department manifest 是类似方向但更复杂（JSON + Python 混合）。

**DevUI**：预览功能，浏览器端调试器可视化 workflow 执行。Orchestrator 的 Dashboard 更全面但不专门针对 agent 执行路径。

**Skills 生态系统**（preview）：MAF 有 Skills 的概念，可复用 domain 能力。和 Orchestrator 的 `.claude/skills/` 几乎同构，但 MAF 的 skill 是更标准化的 Python 包。

**`IResettableExecutor`**：有状态 executor 需要实现重置接口，保证跨 workflow run 的状态隔离。Orchestrator 的 executor 目前依赖外部状态清理，没有这个约束接口。

---

## Meta Insights

**1. Microsoft 赌的是"显式控制 > 自主性"**
整个 MAF 的设计哲学是把 LLM 的不确定性限制在最小范围——用 Pregel 超步保证确定性，用类型系统保证消息安全，用显式 workflow graph 限制执行路径。这和 AutoGen v0.2 的"让 agent 自由对话"方向是相反的。

Orchestrator 走的路子不一样：Governor + APO + growth_loops 是在拥抱不确定性、让系统自主演化。这不是弱点，是刻意选择的差异化。

**2. 中间件三层分离是可以无缝移植的工程模式**
MAF 的三层钩子（agent/function/chat）不依赖任何 Microsoft 基础设施，是纯粹的软件工程模式。Orchestrator 可以在不破坏现有架构的情况下逐步引入，代价极低。

**3. 超步模型 vs 事件驱动的取舍**
MAF 的 Pregel 超步牺牲了一定的响应性（必须等 barrier）换取确定性和可 checkpoint。Orchestrator 的事件驱动模型响应性更好但更难 checkpoint 和 replay。两者各有适用场景，不是非此即彼。

**4. 缺失：agent 的 identity 和自我意识**
MAF 把 agent 看成纯粹的计算单元，没有 identity、没有跨会话记忆、没有自我描述能力。这是工程框架的正常选择，但也意味着 MAF 构建出来的系统永远不会"认识自己"。Orchestrator 在这个维度走得更远，这是真实的差异化。

**5. 开源策略：合并而不是竞争**
AutoGen + SK 合并成 MAF 说明 Microsoft 认识到两条路线不能同时维护。这是大公司内部的 alignment 成本外显。开源社区用脚投票（AutoGen 57k，SK 27k，MAF 才 9.4k）说明合并初期社区还在观望。Orchestrator 可以从两个原始仓库偷师，不必完全跟着 MAF 走。
