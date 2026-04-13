# R49 — Qwen Code Steal Report

**Source**: https://github.com/QwenLM/qwen-code | **Stars**: 23K | **License**: Apache-2.0
**Date**: 2026-04-13 | **Category**: Complete Framework
**Version**: 0.14.4 | **Codebase**: 418K LOC TypeScript (monorepo)

## TL;DR

阿里通义团队对 Claude Code 的完整开源重实现（TypeScript），在保持架构同构的基础上原创了三个 Claude Code 没有的系统：**Arena（多模型竞赛评估）**、**Channels（多平台消息桥接 + 三种调度模式）**、**BlockStreamer（流式分段投递）**。偷师价值在于他们解决了我们也有但还没解决好的问题——特别是 Channel 层的消息并发调度和 Agent 流式输出的分段投递。

## Architecture Overview

```
Layer 4 — Frontends
  ├── CLI (packages/cli)
  ├── WebUI (packages/webui) — React, Adapter pattern (ACP/JSONL replay)
  ├── IDE Companions (VS Code, Zed, JetBrains)
  └── SDKs (TypeScript, Java)

Layer 3 — Channels (packages/channels)
  ├── ChannelBase (abstract adapter with dispatch modes)
  ├── Platform Adapters (Telegram, WeChat, DingTalk, TMCP)
  ├── SenderGate + GroupGate (access control)
  ├── SessionRouter (per-user/thread/single isolation)
  ├── BlockStreamer (progressive message delivery)
  └── AcpBridge (spawns qwen-code --acp subprocess)

Layer 2 — Core Engine (packages/core)
  ├── AgentCore (stateless reasoning loop)
  ├── AgentHeadless / AgentInteractive (one-shot vs persistent wrappers)
  ├── CoreToolScheduler (concurrency-safe batching + permission flow)
  ├── PermissionManager (L3→L4→L5 three-level evaluation)
  ├── SubagentManager (5-level storage: session > project > user > extension > builtin)
  ├── SkillManager (context injection, not executable code)
  ├── HookSystem (14 event types, shell command I/O)
  ├── ArenaManager (multi-model competitive execution via git worktrees)
  ├── CronScheduler (in-session, deterministic jitter)
  └── MicrocompactService (time-based idle context cleanup)

Layer 1 — Models & Auth
  ├── ModelRegistry (multi-provider: Qwen OAuth, OpenAI, Anthropic, Gemini, Vertex)
  ├── ModelsConfig (runtime switching with state snapshots)
  └── OAuth2 + PKCE + dynamic client registration
```

## Steal Sheet

### P0 — Must Steal (4 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Channel Dispatch Modes | collect/steer/followup 三模式处理消息并发 | `ConversationLockManager` 只有 followup+reject，debounce 是原始 collect | 升级 `conversation_lock.py` → 三模式 + per-chat 配置 | ~4h |
| BlockStreamer 分段投递 | minChars(400)/maxChars(1000)/idleMs(1500) 三阈值 + 段落边界 + promise chain 串行化 | `message_splitter.py` 只切分完整消息，无流式投递 | 新建 `src/channels/block_streamer.py` | ~2h |
| Stream-JSON 流式桥接 | Claude Code `--output-format stream-json` 输出 NDJSON → 实时解析 text/tool 事件 | `CLIBridge` 用 `subprocess.run` 等全部输出 | `CLIBridge` 改 `Popen` 逐行读 + StreamParser | ~3h |
| Tool Concurrency Partitioning | 同步 regex 检测 read-only → 自动分批并行/串行 | 依赖 Claude Code 内置并行，无法控制 | 作为 skill/hook 层的设计参考 | ~2h |

> **升级说明**: stream-json + BlockStreamer 从 P1 提升为 P0。理由：(1) BlockStreamer 没有流式数据源就是空架子，stream-json 是它的前置依赖；(2) Claude Code 原生支持 `--output-format stream-json`，我们不需自建协议；(3) 三者组合（dispatch + stream + block）才构成完整的 channel 体验升级。

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Arena 多模型竞赛 | git worktree 隔离 + 并行 PTY 子进程 + 500ms 轮询 + 结果对比 | 新建 `.claude/skills/arena/` 技能，用于 A/B 测试不同 prompt/model | ~6h |
| Microcompaction 空闲清理 | 距上次 API 调用超 N 分钟 → 清除旧 tool result，保留最近 5 条，error 永不清 | 参考设计改进我们的 condenser | ~4h |
| Cron Deterministic Jitter | `hash(id) % min(period*10%, 15min)` 避免整点雪崩，one-shot 整点任务提前 90s | 参考改进我们的 cron 调度 | ~2h |
| Approval Mode Inheritance | 父 agent permissive (yolo/auto-edit) → 子 agent 继承；trusted folder 防提权 | 参考设计我们的 subagent 权限链 | ~3h |
| Envelope Normalization | 所有平台消息统一为 Envelope (senderId, chatId, isGroup, isMentioned, referencedText) | channel 层重建时对齐这个格式 | ~3h |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Multi-Provider ModelRegistry | 5 种 authType + 运行时切换 + state snapshot 回滚 | 我们只用 Claude，不需要多模型 |
| Extension Marketplace | git/npm/marketplace/local 四来源 + consent + auto-update | Claude Code 已有 plugin 系统 |
| WebUI Adapter Pattern | ACPAdapter (实时) / JSONLAdapter (回放) 双适配器 | 有趣但我们没有 WebUI 需求 |
| Java SDK | 完整的 Java 客户端，支持终端操作和文件 I/O | 我们是 Python 生态 |
| Community GitHub Workflows | Gemini+Qwen 做 issue triage、PR review、contribution report | 有趣的 CI/CD 模式，但我们规模太小用不上 |

## Comparison Matrix (P0)

### Channel Dispatch Modes

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 消息并发检测 | `activePrompts` Map 跟踪每 session 进行中的 prompt | 无 | **Large** | Steal |
| Collect 模式 | buffer 新消息 → 当前完成后合并发送 | 无 | **Large** | Steal |
| Steer 模式 | cancel 当前 + 注入 `[cancelled]` 上下文 → 处理新消息 | 无 | **Large** | Steal |
| Followup 模式 | promise chain 串行队列 | 无 | **Large** | Steal |
| Per-group 配置 | `groups: { "*": { dispatchMode: "collect" } }` | 无 | **Large** | Steal |

```typescript
// 核心实现 — ChannelBase.ts:316-348
const active = this.activePrompts.get(sessionId);
if (active) {
  switch (mode) {
    case 'collect': {
      // Buffer → coalesce when active finishes
      let buffer = this.collectBuffers.get(sessionId);
      if (!buffer) { buffer = []; this.collectBuffers.set(sessionId, buffer); }
      buffer.push({ text: promptText, envelope });
      return;
    }
    case 'steer': {
      // Cancel running → prepend cancellation note → send new
      active.cancelled = true;
      await this.bridge.cancelSession(sessionId).catch(() => {});
      await active.done;
      promptText = `[The user sent a new message while you were working.]\n\n${promptText}`;
      break;
    }
    case 'followup': {
      break; // Chain onto session queue
    }
  }
}
```

### BlockStreamer 分段投递

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 流式分块 | minChars(400)/maxChars(1000) 双阈值 | 无，等全部生成 | **Large** | Steal |
| 段落边界检测 | `\n\n` 作为自然分割点 | 无 | **Large** | Steal |
| 空闲超时发送 | idleMs(1500) 后自动 flush | 无 | **Large** | Steal |
| 发送串行化 | `this.sending` promise chain | 无 | **Medium** | Steal |

```typescript
// 核心实现 — BlockStreamer.ts
// Emission triggers:
// 1. Buffer ≥ maxChars → force-split at best break point
// 2. Buffer ≥ minChars AND \n\n exists → emit up to boundary
// 3. Idle timer fires AND buffer ≥ minChars → emit buffer
// 4. flush() called → emit everything remaining
push(chunk: string): void {
  this.buffer += chunk;
  this.clearIdleTimer();
  this.checkEmit();
  if (this.buffer.length > 0 && this.opts.idleMs > 0) {
    this.idleTimer = setTimeout(() => this.onIdle(), this.opts.idleMs);
  }
}
```

### Stream-JSON 流式桥接 (P0 新增)

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 流式数据源 | AcpBridge NDJSON via `@agentclientprotocol/sdk` | `CLIBridge` 用 `subprocess.run` 等全量 | **Large** | Steal |
| 事件解析 | `handleSessionUpdate` 分发 13 种事件类型 | 无 | **Large** | Steal (简化版) |
| chunk → BlockStreamer | `bridge.on('textChunk', onChunk)` 事件驱动 | 无 | **Large** | Steal |
| session 复用 | ACP 长连接 + `loadSession` 恢复 | `CLIBridge` 用 `--resume` flag | **Small** | 已有方案 |

```python
# 我们的适配方案 — CLIBridge 改造核心逻辑
# 不需要 ACP SDK，Claude Code 原生 stream-json 就够了
proc = subprocess.Popen(
    [binary, "--output-format", "stream-json", "--print", message],
    stdout=subprocess.PIPE, text=True, cwd=self._cwd,
)
for line in proc.stdout:
    event = json.loads(line)
    if event.get("type") == "assistant" and event.get("subtype") == "text":
        yield event["content"]  # → BlockStreamer.push()
```

### Tool Concurrency Partitioning

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| 并发安全检测 | 同步 regex 判定 read-only (fail-closed) | Claude Code 内置，我们无控制 | **Small** | Reference |
| 批次分区 | consecutive safe → parallel batch, unsafe → sequential | 同上 | **Small** | Reference |
| Agent tool 并发 | Agent 调用标记为 concurrency-safe（独立子进程） | Claude Code 已支持 | **None** | Skip |

```typescript
// 核心实现 — coreToolScheduler.ts:375-386
function partitionToolCalls(calls: ScheduledToolCall[]): ToolBatch[] {
  return calls.reduce<ToolBatch[]>((batches, call) => {
    const safe = isConcurrencySafe(call);
    const lastBatch = batches[batches.length - 1];
    if (safe && lastBatch?.concurrent) {
      lastBatch.calls.push(call);  // merge into parallel batch
    } else {
      batches.push({ concurrent: safe, calls: [call] });
    }
    return batches;
  }, []);
}
```

## Gaps Identified

| Dimension | They have | We have | Gap |
|-----------|----------|---------|-----|
| **Execution / Orchestration** | Arena 多模型竞赛 + git worktree 隔离 | 单模型执行 | 缺少对比评估机制 |
| **Execution / Orchestration** | 三种 Dispatch Mode (collect/steer/followup) | TG channel 无并发控制 | **Critical** — 群消息场景 |
| **Context / Budget** | Microcompaction (time-based idle cleanup) | condenser 存在但较简单 | Medium |
| **Context / Budget** | BlockStreamer 流式分段 | 等全部生成才发 | **Critical** — UX |
| **Failure / Recovery** | Tool error 返回 Levenshtein 建议 | 无 | Small |
| **Quality / Review** | Terminal benchmarks 集成 | 无 benchmark | Medium |
| **Security / Governance** | L3→L4→L5 三级权限 + trusted folder | guard.sh hook 拦截 | 架构相当，实现路径不同 |
| **Memory / Learning** | 无持久化 memory 系统 | SOUL/memory 完整体系 | **我们领先** |

## Event-Driven Feedback System (用户特别关注)

Qwen Code 的操作反馈体验来自三层 event-driven 架构：

### Layer 1 — Core Event System (13 种事件)

```typescript
// agent-events.ts
enum AgentEventType {
  START, ROUND_START, ROUND_END, ROUND_TEXT,
  STREAM_TEXT,           // 流式文本，区分 thought vs regular
  TOOL_CALL,             // tool 被请求
  TOOL_OUTPUT_UPDATE,    // tool 执行中的增量输出
  TOOL_WAITING_APPROVAL, // 等待用户确认
  TOOL_RESULT,           // tool 完成
  USAGE_METADATA,        // token 用量
  FINISH, ERROR, STATUS_CHANGE
}
// 每个事件都带 timestamp + subagentId + round，UI 精确知道 agent 在做什么
```

### Layer 2 — Tool Status Indicator (6 种视觉状态)

```
Pending → Executing (spinner) → Success ✓ | Error ✗ | Canceled ⊘ | Confirming ⚠
```

每个 tool call 都有独立的生命周期指示器，用户一眼看到哪个工具在跑、哪个等确认、哪个完成了。

### Layer 3 — StatusLine (用户可定制状态栏)

```typescript
// useStatusLine.ts — 监听 7 种状态变化，300ms debounce
interface StatusLineCommandInput {
  session_id, version, model, context_window (size/used%/remaining%),
  workspace, git.branch, metrics (per-model tokens + file changes), vim.mode
}
// Event-driven 而非 polling — "triggered by state changes, not blind polling"
```

**我们能偷的**: 不是 UI 组件（我们是 CLI plugin），而是**事件粒度的设计哲学**：
- 每个 tool call 有 6 种生命周期状态，不是简单的"开始/结束"
- `TOOL_OUTPUT_UPDATE` 支持执行中的增量反馈（比如 shell 命令边跑边输出）
- `STREAM_TEXT` 区分 thought vs regular text，让 UI 可以分别展示
- StatusLine 的 JSON stdin 协议让用户可以用任意脚本定制显示

## Adjacent Discoveries

1. **AcpBridge 协议**: Qwen Code 用 NDJSON over stdio 做 agent ↔ channel 通信，这个协议比我们现在的直接函数调用更适合跨进程场景。如果未来 channel 层需要独立部署，这是参考架构。

2. **GitHub Workflow AI 自动化**: 他们用 Gemini 做 issue dedup、PR triage、contribution report。虽然我们规模小用不上，但 `community-report.yml` 的 GraphQL + AI 分类模式值得记住。

3. **Extension System 设计**: install/uninstall/enable/disable/update/link/list/new/settings 完整生命周期。Claude Code 的 plugin 系统已经覆盖了核心场景，但他们的 consent request 和 workspace trust checking 机制值得关注。

4. **OAuth2 + PKCE**: 完整的 OAuth 流程实现，包括 dynamic client registration。如果我们未来需要做多用户认证（比如 TG channel 的用户身份绑定），这是现成参考。

5. **Deterministic Jitter 算法**: `hash(id) % min(period * 10%, 15min)` — 简单优雅，避免整点雪崩。one-shot 任务整点提前 90s 也是巧妙的设计。

## Triple Validation (P0 Patterns)

### Channel Dispatch Modes

| Check | Result | Evidence |
|-------|--------|----------|
| **Cross-domain reproduction** | ✅ Pass | Slack (threads as queues), Discord (rate-limited message dispatch), 我们的 TG channel 已遇到消息覆盖问题 |
| **Generative power** | ✅ Pass | 给定新场景"微信群 10 人同时 @bot"→ 可预测：collect 模式合并、steer 模式取最新、followup 串行 |
| **Exclusivity** | ✅ Pass | 不是通用的"消息队列"——三模式切换 + per-group 配置 + cancelled 上下文注入是独特组合 |

**Score: 3/3 — Confirmed P0**

### BlockStreamer

| Check | Result | Evidence |
|-------|--------|----------|
| **Cross-domain reproduction** | ✅ Pass | Telegram Bot API 的 "typing..." + 分段发送是常见模式；SSE streaming 的 chunk flush 同理 |
| **Generative power** | ✅ Pass | 给定"agent 输出 3000 字"→ 可预测：400 字时检查段落边界 → 1000 字强制分割 → 1.5s 无输入则 flush |
| **Exclusivity** | ✅ Pass | 三阈值 (min/max/idle) + 段落边界 + 串行化发送的组合超出通用 "chunked transfer" |

**Score: 3/3 — Confirmed P0**

### Stream-JSON 流式桥接 (P0 新增)

| Check | Result | Evidence |
|-------|--------|----------|
| **Cross-domain reproduction** | ✅ Pass | SSE streaming (ChatGPT web)、Jupyter kernel output streaming、任何 LSP stdio 通信 |
| **Generative power** | ✅ Pass | 给定"agent 需要 3 分钟处理"→ 可预测：用户 30s 后就该看到第一段输出，而非 180s 后看到一大段 |
| **Exclusivity** | ✅ Pass | 不是通用 streaming — 关键在 NDJSON 事件分类 (text/tool/result) + 与 BlockStreamer 的管道组合 |

**Score: 3/3 — Confirmed P0**

### Tool Concurrency Partitioning

| Check | Result | Evidence |
|-------|--------|----------|
| **Cross-domain reproduction** | ✅ Pass | 数据库 read/write lock 分离、Git 并发 read + exclusive write |
| **Generative power** | ✅ Pass | 给定新 tool 列表 → 可预测哪些可并行 |
| **Exclusivity** | ⚠️ Partial | 同步 regex fail-closed 是独特选择，但核心概念（read-only detection）较通用 |

**Score: 2/3 — P0 with caveat (exclusivity partial, core concept is common)**

## Knowledge Irreplaceability

| Pattern | Pitfall | Judgment | Hidden Context | Failure | Behavioral | Score |
|---------|---------|----------|----------------|---------|-----------|-------|
| Dispatch Modes | ✅ steer 需要 cancelled 上下文注入否则 agent 困惑 | ✅ collect 适合群聊、steer 适合 1v1 | ✅ per-group 覆盖是因为同一 bot 可能同时服务群和私聊 | — | ✅ 默认 steer 而非 followup（用户期望即时响应） | **4/6** |
| BlockStreamer | ✅ 不分段时长回复在 TG 超时 | ✅ 400/1000/1500 三阈值是经验值 | ✅ 串行化防止消息乱序 | — | — | **3/6** |
| Stream-JSON 桥接 | ✅ ACP SDK 坑多，NDJSON 更轻量 | ✅ stream-json 优于 ACP（不需额外依赖） | ✅ Claude Code 原生支持但文档未强调此用法 | — | ✅ 事件驱动而非 polling | **4/6** |
| Tool Concurrency | — | ✅ fail-closed 比 fail-open 安全 | ✅ 同步 regex 而非 async AST 是性能权衡 | — | — | **2/6** |

## Meta Insights

1. **克隆项目的偷师价值在"差异"不在"同构"**: Qwen Code 90% 与 Claude Code 同构，真正的偷师价值集中在那 10% 的原创差异——Arena、Channels、BlockStreamer。这验证了一个元规则：**分析竞品时，先找差异集，再深入差异集**。

2. **Channel 层是 AI Agent 的"最后一公里"**: 引擎再强，用户通过 Telegram 群聊使用时，消息并发、流式分段、上下文注入这些"最后一公里"问题直接决定体验。Qwen Code 在这一层投入了显著工程量（ChannelBase + BlockStreamer + 3 dispatch modes + SenderGate + GroupGate），说明他们在生产环境遇到了这些问题。

3. **Arena = 内建的 A/B Testing 框架**: 把多模型竞赛做成 first-class feature 而不是外部脚本，这个决策暗示了一个趋势——**agent 质量保证从"测完再上线"转向"运行时对比选优"**。我们的 adversarial-dev skill 走的是类似路线，但 Arena 的 git worktree 隔离 + 并行执行更工程化。

4. **"Skills as Context, Not Code"**: Qwen Code 的 Skill 不是可执行代码，而是注入 LLM 上下文的 markdown 指导。这和我们的 SKILL.md 设计完全一致——验证了这个架构选择是正确的。两个独立团队独立到达相同设计，说明这是收敛解。

5. **Permission 三级评估是行业共识**: L3 (tool intrinsic) → L4 (rule override) → L5 (interactive confirm) 的三层模型，与 Claude Code 的 permission 设计几乎一致。这不是偶然——安全模型在收敛。我们的 guard.sh hook 对应的是 L4 层。

## Deep Dive — 实现级细节（Phase 2 补充）

### ChannelBase.handleInbound 完整消息流

源码精读后绘制的完整消息处理流程（`ChannelBase.ts:238-428`）：

```
Inbound Message
  │
  ├─ GroupGate.check() — 群策略 + allowlist + mention 过滤
  ├─ SenderGate.check() — 用户鉴权（allowlist/pairing/open）
  ├─ parseCommand() — slash 命令拦截（/clear, /help, /status + 平台命令）
  ├─ SessionRouter.resolve() — 路由键 = channelName:senderId:chatId (user scope)
  │                             或 channelName:threadId (thread scope)
  │                             或 channelName:__single__ (single scope)
  ├─ Envelope 预处理 — referencedText 注入引用、attachments 解析
  ├─ Instructions 注入 — 首次消息追加 channel instructions
  │
  ├─ Dispatch Mode 决策 — per-group override → channel config → default 'steer'
  │   ├─ collect: buffer.push() → return (不进入 queue)
  │   ├─ steer:  cancel active → await done → prepend [cancelled] note
  │   └─ followup: fall through to queue
  │
  └─ Session Queue 串行化
      ├─ Register activePrompts[sessionId]
      ├─ onPromptStart() — typing indicator
      ├─ BlockStreamer 创建（if blockStreaming === 'on'）
      ├─ bridge.on('textChunk') → streamer.push()
      ├─ bridge.prompt(sessionId, text) — 阻塞等待
      ├─ if !cancelled: streamer.flush() 或 onResponseComplete()
      └─ finally:
          ├─ bridge.off('textChunk')
          ├─ onPromptEnd()
          ├─ activePrompts.delete()
          ├─ promptState.resolve() — 释放 steer 等待者
          └─ Drain collectBuffers → 合并为 syntheticEnvelope → handleInbound()
```

**关键设计决策**：
1. collect buffer drain 是**递归调用 handleInbound**（非直接发送），这意味着合并后的消息会重新经过 dispatch mode 检查——如果此时又有新消息进来，会再次 buffer
2. `sessionQueues` 用 `.then()` 链式串行化，即使是 steer 模式也会先等 active 结束后才开始新 prompt
3. `promptState.resolve()` 在 finally 中调用，确保 steer 的 `await active.done` 不会永远阻塞

### BlockStreamer 四种触发条件

```
Trigger 1: buffer ≥ maxChars (1000)
  → findBreakPoint(): \n\n > \n > space > hard cut
  → while loop: 可能产生多个 block（超长输入时）

Trigger 2: buffer ≥ minChars (400) AND \n\n exists
  → findBlockBoundary(): lastIndexOf('\n\n')
  → 只在 minChars 之后的位置切（防止过短段落）

Trigger 3: idle timer (1500ms) AND buffer ≥ minChars
  → onIdle(): emit 整个 buffer
  → 保护：buffer < minChars 时 idle 不触发（等更多内容）

Trigger 4: flush() — 响应完成
  → emit 所有剩余 buffer（无 minChars 限制）
```

**串行化机制**：`this.sending = this.sending.then(() => this.opts.send(trimmed))` — 无锁 promise chain，保证消息顺序。每个 `emitBlock` 都挂在前一个 send 完成之后。

### Stream-JSON 与 BlockStreamer 的集成点

Qwen Code 的 `AcpBridge` 通过 `@agentclientprotocol/sdk` 的 NDJSON stream 接收 `agent_message_chunk` 事件。但 Claude Code 有更简单的路径：

```
claude --output-format stream-json -p "message"
```

输出 NDJSON，每行一个事件：
```json
{"type":"assistant","subtype":"text","content":"Hello "}
{"type":"tool_use","name":"Read","input":{...}}
{"type":"tool_result","content":"..."}
{"type":"assistant","subtype":"text","content":" world"}
{"type":"result","text":"Hello world","session_id":"abc123"}
```

**我们的集成方案**：
1. `CLIBridge.chat()` 改用 `Popen` + 逐行读取 stdout
2. 每读一行 → 解析 JSON → if type=="assistant" && subtype=="text" → yield chunk
3. chunk → `BlockStreamer.push(chunk)`
4. `BlockStreamer` → `send_fn(chat_id, block_text)`
5. 最后一行 `type=="result"` → `BlockStreamer.flush()` → 返回完整文本

### 与我们现有架构的 diff

| Component | Qwen Code | Our Current | Gap Action |
|-----------|-----------|-------------|------------|
| Message dispatch | `ChannelBase.handleInbound` 内置三模式 | `ConversationLockManager` 只有 queue+reject | **重写**: 添加 collect/steer mode |
| Streaming source | `AcpBridge` NDJSON via ACP SDK | `CLIBridge.subprocess.run` 等全量输出 | **重写**: 改 Popen + stream-json |
| Progressive delivery | `BlockStreamer` 类 (134 LOC) | 无 | **新建**: Python 移植 ~100 LOC |
| Session routing | `SessionRouter` (user/thread/single scope) | `chat_engine` 按 chat_id 直接查 | **待定**: 当前场景够用 |
| Typing indicator | `onPromptStart/End` hook + 4s interval | `_keep_typing` 线程 + 4s interval | **一致**: 已覆盖 |
| Message splitting | `splitHtmlForTelegram` (4096 limit) | `message_splitter.split_message` (多平台) | **我们更好**: 支持三轮切分 |
| Access control | `SenderGate` + `GroupGate` + `PairingStore` | `ch_cfg.ALLOWED_USERS` + `user_can()` | **待定**: pairing 模式有趣但非必需 |
