# Claude Code Architecture Deep Dive: Kairos / Daemon / UDS Inbox / Swarm IPC

> Source: sanbuphy/claude-code-source-code (v2.1.88 leaked via npm .map file)
> Date: 2026-04-01
> Branch: steal/round23-p1

---

## Executive Summary

Claude Code 内部有三层递进的 multi-session 架构，通过编译时 feature flags 控制：

| Layer | Feature Flag | 状态 | 核心抽象 |
|-------|-------------|------|----------|
| **Swarm (团队协作)** | `AGENT_SWARMS` | 已发布 | File-based mailbox + polling |
| **UDS Inbox (本地对等通信)** | `UDS_INBOX` | 内部可用 | Unix domain socket 直连 |
| **Bridge (跨机器通信)** | `REPL_BRIDGE` | 已发布(Remote Control) | WebSocket via Anthropic servers |
| **BG Sessions (后台会话)** | `BG_SESSIONS` | 内部可用 | `--bg` tmux detach + daemon |
| **Kairos (主动式助手)** | `KAIROS` / `PROACTIVE` | 内部原型 | Tick-driven proactive loop |

关键发现：这不是一个统一的 IPC 框架，而是**渐进式堆叠的多种通信机制**，每一层解决不同的信任边界和延迟需求。

---

## Pattern 1: PID-File Session Registry (concurrentSessions.ts)

### 架构

```
~/.claude/sessions/
  ├── 12345.json    # PID-keyed session record
  ├── 12346.json
  └── 12347.json
```

每个 Claude Code 进程启动时注册一个 PID 文件，包含：

```typescript
{
  pid: number,
  sessionId: string,
  cwd: string,
  startedAt: number,
  kind: 'interactive' | 'bg' | 'daemon' | 'daemon-worker',
  entrypoint: string,
  // UDS_INBOX feature-gated:
  messagingSocketPath?: string,
  // BG_SESSIONS feature-gated:
  name?: string,
  logPath?: string,
  agent?: string,
  // Bridge dedup:
  bridgeSessionId?: string
}
```

### Session Lifecycle

1. **注册**: `registerSession()` 在进程启动时创建 `~/.claude/sessions/<PID>.json`
2. **跳过条件**: 子 agent（`getAgentId() != null`）不注册——只有顶层会话注册
3. **活性检测**: `countConcurrentSessions()` 遍历目录，对每个 PID 调 `isProcessRunning(pid)`
4. **清理**:
   - 正常退出：`registerCleanup()` 注册的回调删除 PID 文件
   - 崩溃恢复：下次枚举时发现 PID 不存在，自动删除（WSL 特殊处理——跳过删除，避免误杀 Windows 侧会话）
5. **Session 切换**: `onSessionSwitch()` 回调更新 PID 文件中的 sessionId（`--resume` 场景）

### 关键设计决策

- **严格文件名校验**: `/^\d+\.json$/` 正则——防止 `parseInt` 把 `2026-03-14_notes.md` 解析为 PID 2026（gh-34210 事件）
- **无锁设计**: PID 文件是 write-once-per-process，不需要锁
- **Kind 来源**: 环境变量 `CLAUDE_CODE_SESSION_KIND` 由 spawner 设置，子进程直接读取

### Orchestrator 可偷点

**P0 — Session Registry Pattern**
我们的 Agent SDK 调度的子 agent 没有统一的发现机制。PID-file 注册方式可以直接搬到 Docker 环境：
- 每个 agent 容器启动时写 `/shared/sessions/<container-id>.json`
- 包含 agent 类型、启动时间、当前任务、gRPC/UDS 地址
- `orchestrator status` 命令枚举活跃 agent
- 崩溃检测：Docker health check + PID 文件存在性双重校验

---

## Pattern 2: File-Based Mailbox (teammateMailbox.ts)

### 架构

```
~/.claude/teams/{team_name}/inboxes/
  ├── researcher.json     # researcher 的收件箱
  ├── tester.json         # tester 的收件箱
  └── team-lead.json      # leader 的收件箱
```

### 消息格式

```typescript
type TeammateMessage = {
  from: string,
  text: string,
  timestamp: string,
  read: boolean,
  color?: string,
  summary?: string  // 5-10 word preview for UI
}
```

### 并发控制

使用 `proper-lockfile` 实现文件锁：

```typescript
const LOCK_OPTIONS = {
  retries: {
    retries: 10,
    minTimeout: 5,    // 首次重试 5ms
    maxTimeout: 100,  // 最大重试间隔 100ms
  },
}
```

写入流程：
1. `ensureInboxDir()` — 确保目录存在
2. `writeFile(inboxPath, '[]', { flag: 'wx' })` — 原子创建（已存在则 EEXIST）
3. `lockfile.lock(inboxPath)` — 获取锁
4. 读取当前消息 → append → 写回
5. `release()` — 释放锁

### 消息类型系统（结构化协议消息）

不是所有消息都是纯文本。`isStructuredProtocolMessage()` 识别以下类型：

| 类型 | 方向 | 用途 |
|------|------|------|
| `permission_request` | Worker → Leader | 工具使用审批请求 |
| `permission_response` | Leader → Worker | 审批结果（含 updatedInput + permissionUpdates） |
| `sandbox_permission_request/response` | 双向 | 网络沙箱访问审批 |
| `shutdown_request` | Leader → Worker | 请求关闭 |
| `shutdown_approved/rejected` | Worker → Leader | 关闭确认/拒绝 |
| `plan_approval_request/response` | 双向 | Plan 模式审批流 |
| `team_permission_update` | Leader → All | 权限广播 |
| `mode_set_request` | Leader → Worker | 切换工作模式 |
| `idle_notification` | Worker → Leader | 空闲通知 |

### 安全模型

```
"Only accept approval responses from the team lead"
```

- Plan approval 只接受 `from === 'team-lead'` 的消息
- 防止 Worker 伪造其他 Worker 的审批
- `shutdown_response` 强制 `to === TEAM_LEAD_NAME`

### Orchestrator 可偷点

**P0 — Structured Protocol Messages over Mailbox**
文件邮箱太慢，但消息类型系统的设计很精致。我们可以用 Redis Streams 替代文件：
- 同样的消息类型分类（permission/shutdown/task_assignment）
- `XREAD BLOCK` 替代 1s 轮询
- Consumer Group 替代 `read: boolean` 标记
- 结构化消息的 type discriminated union 模式直接复用

**P1 — Permission Bridge Pattern**
Leader 收到 Worker 的 permission_request 后，通过标准 ToolUseConfirm UI 路由（而不是自定义 UI），Worker badge 标识来源。这个模式在我们的审批体系中可以增强——目前我们的 Claw 审批只支持 yes/no，不支持 updatedInput（修改工具参数后放行）。

---

## Pattern 3: Inbox Poller (useInboxPoller.ts)

### 轮询架构

```
1s interval
    │
    ├── readUnreadMessages(agentName, teamName)
    │
    ├── Categorize by type (10 buckets)
    │   ├── permissionRequests[]
    │   ├── permissionResponses[]
    │   ├── sandboxPermissionRequests[]
    │   ├── sandboxPermissionResponses[]
    │   ├── shutdownRequests[]
    │   ├── shutdownApprovals[]
    │   ├── teamPermissionUpdates[]
    │   ├── modeSetRequests[]
    │   ├── planApprovalRequests[]
    │   └── regularMessages[]
    │
    ├── Route each bucket to its handler
    │
    └── markMessagesAsRead()
```

### 两态投递策略

```
Session idle? ─── YES ──→ onSubmitTeammateMessage(formatted)  → 立即作为新 turn 提交
      │
      NO ──→ queue in AppState.inbox  → 等待当前 turn 完成后投递
```

- **空闲时**: 消息直接注入为新的 user turn，包裹在 `<teammate-message from="...">` XML 标签中
- **忙碌时**: 消息存入 AppState.inbox 队列，UI 显示未读计数
- **Pending 投递**: 当 session 变为 idle，从 AppState 中取出 pending 消息投递

### 去重机制

```typescript
// Deduplicate: if markMessagesAsRead failed on a prior poll,
// the same message will be re-read — skip if already queued.
setToolUseConfirmQueue(queue => {
  if (queue.some(q => q.toolUseID === parsed.tool_use_id)) {
    return queue
  }
  return [...queue, entry]
})
```

### 谁轮询谁

| 角色 | 轮询目标 | 排除条件 |
|------|---------|---------|
| Team Lead | 自己的 inbox（team-lead.json） | — |
| Process-based Teammate | 自己的 inbox（`CLAUDE_CODE_AGENT_NAME`） | — |
| In-process Teammate | **不轮询** | 使用 `waitForNextPromptOrShutdown()` 代替 |
| Standalone session | 不轮询 | 返回 undefined |

In-process teammate 不用 InboxPoller 的原因：它们共享 React context 和 AppState，用 InboxPoller 会导致消息路由混乱。

### Orchestrator 可偷点

**P1 — Two-State Delivery Pattern**
当 agent 正在处理请求时，新消息不打断当前 turn，而是排队。这比我们当前的「消息丢失或重入」模式好：
- Agent 处理中 → 消息进 pending queue
- Agent turn 结束 → drain pending queue 作为下一个 turn 的上下文
- 解决了 Agent SDK 的 concurrent message 问题

---

## Pattern 4: UDS Inbox (Unix Domain Socket Cross-Session IPC)

### 地址系统 (peerAddress.ts)

```typescript
function parseAddress(to: string): { scheme: 'uds' | 'bridge' | 'other', target: string }
```

三种寻址 scheme：

| Scheme | 格式 | 用途 |
|--------|------|------|
| `uds:` | `uds:/tmp/cc-socks/1234.sock` | 同机器上另一个 Claude Code 会话 |
| `bridge:` | `bridge:session_01AbCd...` | 跨机器的 Remote Control 会话 |
| `other` | `researcher` | 同 team 内的 teammate name |
| **Legacy** | `/tmp/cc-socks/...` (bare path) | 旧版 UDS 发送者兼容 |

### 消息流

```
SendMessageTool.call()
    │
    ├── parseAddress(input.to)
    │
    ├── scheme === 'uds' ──→ sendToUdsSocket(addr.target, message)
    │                         (纯文本写入 Unix socket)
    │
    ├── scheme === 'bridge' ──→ postInterClaudeMessage(addr.target, message)
    │                           (通过 Anthropic API 中继)
    │
    └── scheme === 'other' ──→
        ├── 查找 agentNameRegistry → 本地 agent?
        │   ├── running → queuePendingMessage()
        │   └── stopped → resumeAgentBackground()
        │
        └── 不是本地 agent → writeToMailbox() (文件邮箱)
```

### 消息投递语义

From the prompt:
```
"A listed peer is alive and will process your message — no "busy" state;
messages enqueue and drain at the receiver's next tool round."
```

接收端看到的格式：
```xml
<cross-session-message from="uds:/tmp/cc-socks/1234.sock">
  check if tests pass over there
</cross-session-message>
```

回复时，`from` 属性直接作为 `to` 使用。

### 权限控制

- UDS 消息（同机器）：自动放行
- Bridge 消息（跨机器）：需要用户明确同意
  ```typescript
  behavior: 'ask',
  message: 'Send a message to Remote Control session ${input.to}?'
  ```
- 结构化消息不能跨 session 发送——只有纯文本可以

### 发现机制

每个会话注册时在 PID 文件中写入 `messagingSocketPath`。`ListPeers` 工具（未找到独立文件，可能是 concurrentSessions 的枚举 + bridge session 列表的组合）读取所有 PID 文件和 bridge sessions，展示可达的 peer 列表。

Bridge session 去重：本地 PID 文件记录 `bridgeSessionId`，如果一个 session 同时通过 UDS 和 bridge 可达，优先显示 UDS（本地优先）。

### Orchestrator 可偷点

**P0 — Address Scheme Registry**
统一寻址方案是我们缺失的核心抽象：
```
docker:<container-name>  → Docker exec / gRPC
local:<agent-id>         → Agent SDK 内进程
tg:<chat-id>            → Telegram channel
ws:<session-id>         → WebSocket（Dashboard）
```
一个 `parseAddress()` 函数，SendMessage 工具根据 scheme 路由到不同后端。比我们当前的 if/else 链优雅得多。

**P1 — Local-Preferred Dedup**
当同一 agent 通过多个通道可达时（Docker network + Tailscale），优先本地通道。避免消息重复投递。

---

## Pattern 5: Bridge (Cross-Machine WebSocket IPC)

### 架构

```
Claude Code A (本地)                Anthropic API                Claude Code B (远程)
     │                                  │                              │
     │── createCodeSession() ──────────►│                              │
     │◄── cse_xxxxx (session ID) ──────│                              │
     │                                  │                              │
     │── fetchRemoteCredentials() ─────►│                              │
     │◄── worker_jwt + api_base_url ───│                              │
     │                                  │                              │
     │── WebSocket subscribe ──────────►│◄── WebSocket subscribe ──────│
     │                                  │                              │
     │── SDKMessage ──────────────────►│──────────────────────────────►│
     │◄──────────────────────────────── │◄── SDKMessage ───────────────│
```

### SessionsWebSocket (sessionRunner 的客户端)

- 认证：OAuth Bearer token in WebSocket headers
- 心跳：30s ping interval
- 重连：最多 5 次，2s 间隔
- 特殊关闭码：
  - 4003: 永久关闭，不重连
  - 4001: Session not found，最多重试 3 次（指数退避）

### 消息回声去重 (BoundedUUIDSet)

```typescript
class BoundedUUIDSet {
  // 固定容量环形缓冲区
  // 每条消息有 UUID
  // 发送的消息 UUID 存入 recentPostedUUIDs
  // 收到的消息如果 UUID 在 recentPostedUUIDs 中 → 丢弃（回声）
  // 收到的消息如果 UUID 在 recentInboundUUIDs 中 → 丢弃（重复投递）
}
```

### Control Protocol

Server → Client 的控制请求：

| Subtype | 行为 |
|---------|------|
| `initialize` | 返回 capabilities（必须回复，否则 server 10-14s 超时杀连接）|
| `set_model` | 切换模型 |
| `set_max_thinking_tokens` | 调整 thinking budget |
| `set_permission_mode` | 切换权限模式（有拒绝能力）|
| `interrupt` | 中断当前 turn |

Outbound-only 模式：只发不收，所有 mutable 请求返回 error（initialize 除外）。

### Orchestrator 可偷点

**P1 — Control Protocol Pattern**
Bridge 的 control_request/control_response 是一个通用的远程控制框架：
- 我们的 Dashboard → Agent 通信可以用同样的模式
- `interrupt`（中断执行）、`set_model`（运行时切换模型）、`set_permission_mode`（运行时调权限）
- Response 必须及时回复，否则视为连接死亡——这个超时机制比我们的 fire-and-forget 健壮

**P2 — BoundedUUIDSet for Echo Dedup**
固定容量的环形缓冲区 + Set 组合，O(1) 查找 O(1) 淘汰。比用 Map + TTL 清理简洁。可用于 Telegram bot 的消息去重。

---

## Pattern 6: Swarm Backend Abstraction (backends/types.ts)

### 三种后端

| Backend | 进程模型 | UI | 适用场景 |
|---------|---------|------|---------|
| **tmux** | 独立进程，tmux pane | 终端分屏 | 默认，最成熟 |
| **iterm2** | 独立进程，iTerm2 split | macOS native | iTerm2 用户 |
| **in-process** | 同进程，AsyncLocalStorage 隔离 | React 组件 | 快速 spawn，共享资源 |

### TeammateExecutor 统一接口

```typescript
type TeammateExecutor = {
  type: BackendType
  isAvailable(): Promise<boolean>
  spawn(config: TeammateSpawnConfig): Promise<TeammateSpawnResult>
  sendMessage(agentId: string, message: TeammateMessage): Promise<void>
  terminate(agentId: string, reason?: string): Promise<boolean>
  kill(agentId: string): Promise<boolean>
  isActive(agentId: string): Promise<boolean>
}
```

### In-Process Runner 的隔离策略

`inProcessRunner.ts` 使用 `runWithTeammateContext()` (AsyncLocalStorage) 实现同进程内的 agent 隔离：
- 每个 in-process teammate 有独立的 `TeammateContext`
- `runWithAgentContext()` 嵌套 AsyncLocalStorage 层
- AbortController 用于 lifecycle 管理（leader 可以 abort 任意 teammate）
- 权限请求通过 `leaderPermissionBridge` 路由到 leader 的 ToolUseConfirm UI

### Permission Bridge (in-process)

```
In-process Worker                    Leader
    │                                  │
    ├── createPermissionRequest() ────►│
    │   (via leaderPermissionBridge)   │
    │                                  ├── ToolUseConfirm UI
    │                                  │   (带 worker badge 标识)
    │◄── processMailboxPermissionResponse()
    │   (approve/reject + updatedInput)
```

Worker 与 Leader 在同一进程中，但使用与 tmux backend 相同的 permission 协议（通过 mailbox 或 bridge 发送）。唯一区别是路由方式——in-process 直接调用回调，tmux 通过文件 mailbox。

### Orchestrator 可偷点

**P0 — Unified Executor Interface**
我们的 Agent SDK 调度目前是 ad-hoc 的。定义一个 `AgentExecutor` 接口：
```typescript
interface AgentExecutor {
  type: 'docker' | 'in-process' | 'ssh'
  spawn(config: AgentConfig): Promise<AgentHandle>
  sendMessage(agentId: string, message: AgentMessage): Promise<void>
  terminate(agentId: string): Promise<boolean>
  isActive(agentId: string): Promise<boolean>
}
```
Docker 后端、In-process 后端、未来的 SSH 后端都实现这个接口。调度层不关心执行方式。

---

## Pattern 7: Kairos / Proactive Mode (bootstrap/state.ts + feature flags)

### 已知实现细节

从源码和分析文档拼出的架构：

```
state.ts:
  kairosActive: boolean          // 全局开关
  afkModeHeaderLatched: boolean  // AFK 模式 header 锁存

Feature flags:
  KAIROS     → push notifications, file sends
  PROACTIVE  → sleep tool, proactive behavior
  BG_SESSIONS → background daemon workers
```

### Kairos 模式特征

1. **Persistent always-on**: 不等用户输入，持续运行
2. **Tick-driven**: 定期接收 tick prompt，决定是否主动行动
3. **15s blocking budget**: 任何主动操作如果会阻塞用户超过 15s，则 defer
4. **Append-only daily log**: observations, decisions, actions 记录到日志文件
5. **AFK Mode**: 检测用户离开，切换到更积极的主动模式

### Session Kind 层级

```typescript
type SessionKind = 'interactive' | 'bg' | 'daemon' | 'daemon-worker'
```

- `interactive`: 用户直接交互的终端会话
- `bg`: `claude --bg` 启动的后台 tmux 会话（detach 而不是 kill）
- `daemon`: Daemon 监督进程
- `daemon-worker`: Daemon 下的工作进程

`isBgSession()` 返回 true 时，退出路径（/exit, Ctrl+C, Ctrl+D）应该 detach client 而不是 kill 进程。

### Orchestrator 可偷点

**P1 — Tick-Driven Proactive Loop**
Kairos 的 tick 模型适合我们的三省六部巡检：
- 每 N 分钟 tick 一次，agent 评估是否需要主动行动
- 15s blocking budget 防止巡检阻塞核心功能
- 状态记录到 append-only log，便于审计
- AFK 检测：如果 Telegram 超过 30 分钟无消息，切换到 proactive 扫描模式

**P2 — Session Kind Hierarchy**
我们的 agent 也需要 kind 分类：
- `dispatch`: 三省六部派单的子 agent
- `daemon`: 后台持续运行的守护进程（数据采集器）
- `interactive`: Dashboard 上的交互式会话
- kind 决定生命周期管理策略（dispatch 完成即销毁，daemon 崩溃重启，interactive 用户控制）

---

## Pattern 8: SendMessageTool — 统一消息路由

### 路由决策树

这是整个 IPC 架构最精华的部分——一个工具函数内统一了所有通信方式：

```
SendMessageTool.call(input)
│
├── UDS_INBOX && typeof message === 'string'?
│   ├── scheme === 'bridge' → postInterClaudeMessage()     # 跨机器
│   └── scheme === 'uds'    → sendToUdsSocket()            # 同机器
│
├── typeof message === 'string' && to !== '*'?
│   ├── agentNameRegistry.get(to) exists?
│   │   ├── task.status === 'running' → queuePendingMessage()  # 排队
│   │   └── task.status !== 'running' → resumeAgentBackground()  # 唤醒
│   └── no registry entry → resumeAgentBackground() attempt
│
├── to === '*' → handleBroadcast()    # 全员广播
│
└── structured message?
    ├── shutdown_request → handleShutdownRequest()
    ├── shutdown_response → handleShutdownApproval/Rejection()
    └── plan_approval_response → handlePlanApproval/Rejection()
```

### 关键设计

1. **统一入口**: LLM 只需要调一个工具，路由逻辑全在 `call()` 内
2. **Agent 唤醒**: stopped agent 收到消息时自动 `resumeAgentBackground()`——不需要显式重启
3. **广播开销提示**: `"*"` broadcast 的 prompt 明确说 "expensive (linear in team size)"
4. **结构化消息限制**: 只能发给同 team 内的具名 teammate，不能广播，不能跨 session

### Orchestrator 可偷点

**P0 — Unified Message Router**
一个 `sendMessage(to, message)` 入口，内部根据地址 scheme 路由。这比我们当前的 "Telegram 用 bot API，审批用 Redis，agent 用 SDK" 分散方式好得多。

**P1 — Auto-Resume on Message**
Agent 停止后收到消息自动恢复执行。我们的 agent 目前停了就停了，需要手动重启。可以改为：收到新任务时自动 spawn agent 处理。

---

## Consolidated Steal Priorities

### P0 (立即实施)

| # | Pattern | 来源 | 实施方案 |
|---|---------|------|---------|
| 1 | **Address Scheme Registry** | peerAddress.ts | `parseAddress()` 统一寻址，route to Docker/local/TG/WS backends |
| 2 | **Unified Executor Interface** | backends/types.ts | `AgentExecutor` 抽象（Docker/in-process/SSH） |
| 3 | **Session Registry** | concurrentSessions.ts | `/shared/sessions/<id>.json` PID 文件注册，`status` 命令枚举 |
| 4 | **Unified Message Router** | SendMessageTool.ts | 单入口 `sendMessage(to, message)` 按 scheme 路由 |

### P1 (本轮计划)

| # | Pattern | 来源 | 实施方案 |
|---|---------|------|---------|
| 5 | **Two-State Delivery** | useInboxPoller.ts | Agent 忙时排队，idle 时 drain |
| 6 | **Permission Bridge** | leaderPermissionBridge | 审批支持 updatedInput（修改参数后放行）|
| 7 | **Tick-Driven Proactive Loop** | Kairos state | 三省六部定时巡检 + blocking budget |
| 8 | **Control Protocol** | bridgeMessaging.ts | Dashboard → Agent 的 interrupt/set_model/set_mode 远程控制 |
| 9 | **Auto-Resume on Message** | SendMessageTool.ts | Agent 停止后收到消息自动唤醒 |
| 10 | **Structured Protocol Messages** | teammateMailbox.ts | Redis Streams 替代文件邮箱，保持消息类型系统 |

### P2 (后续迭代)

| # | Pattern | 来源 | 实施方案 |
|---|---------|------|---------|
| 11 | **BoundedUUIDSet Echo Dedup** | bridgeMessaging.ts | 环形缓冲 + Set 用于 TG bot 消息去重 |
| 12 | **Session Kind Hierarchy** | concurrentSessions.ts | Agent kind 分类决定生命周期策略 |
| 13 | **Local-Preferred Dedup** | replBridgeHandle.ts | 多通道可达时优先本地通道 |

---

## Architecture Diagrams

### Full IPC Stack

```
┌──────────────────────────────────────────────────────────┐
│                    SendMessageTool                        │
│              (Unified message routing)                    │
├──────────┬──────────┬──────────┬────────────────────────┤
│  UDS     │  Bridge  │ Mailbox  │   In-Process            │
│  Socket  │  WS/API  │  File    │   Direct Call           │
├──────────┼──────────┼──────────┼────────────────────────┤
│ Same     │ Cross    │ Same     │   Same Process          │
│ Machine  │ Machine  │ Machine  │                         │
│ <1ms     │ ~100ms   │ ~50ms    │   <0.1ms               │
└──────────┴──────────┴──────────┴────────────────────────┘
         ▲                ▲
         │                │
    ListPeers         useInboxPoller
    (Discovery)       (1s Polling)
         │                │
    PID-File          File Locking
    Registry          (proper-lockfile)
```

### Session Lifecycle

```
Process Start
    │
    ├── registerSession()        ← Write PID file
    │   ├── mkdir sessions/
    │   ├── writeFile PID.json
    │   └── registerCleanup()    ← Delete on exit
    │
    ├── onSessionSwitch()        ← Update on --resume
    │
    ├── updateSessionBridgeId()  ← Bridge connected
    │
    ├── updateSessionActivity()  ← busy/idle/waiting
    │
    └── Process Exit
        └── unlink PID.json      ← Cleanup callback
            (or stale-sweep on next enumeration)
```
