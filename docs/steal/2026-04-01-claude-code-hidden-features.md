# Round 23 P2: Claude Code 隐藏功能架构偷师

> 来源: Kuberwastaken/claude-code + nicepkg/claude-code（npm sourcemap 泄露镜像）
> 触发: 2026-03-31 Anthropic 意外在 npm 包中附带 .map 文件，暴露完整 TypeScript 源码
> 目标: 8 个 feature-gated 隐藏功能的架构模式提取
> 日期: 2026-04-01
> 分支: steal/round23-p1
> 详细分析: buddy-autodream-deep-dive.md / claude-code-kairos-daemon-uds-deep.md / claude-code-teleport-ultraplan-deep.md

---

## 背景

P1 偷的是执行层（Agent Loop / Compaction / Permission / Continue Sites），这次 P2 偷的是**隐藏功能层**——通过 `feature('FLAG')` 编译时门控的未发布系统。这些功能在公开版中被 dead code elimination 移除，但 sourcemap 泄露暴露了完整实现。

8 个功能组成三个架构层：

| 层 | 功能 | 本质 |
|----|------|------|
| **人格层** | Buddy（AI 宠物）、Auto-Dream（记忆整理） | 状态持久化 + 后台自省 |
| **通信层** | UDS Inbox（本地 IPC）、Bridge（跨机器）、Kairos（主动模式） | 多实例协作运行时 |
| **远程层** | Teleport（会话迁移）、Ultraplan（远程规划）、Ultrareview（远程审查） | 云端计算卸载 |

---

## P0 可偷模式（16 个）

### P0-1: Cheapest-First Gate Chain
**来源**: `services/autoDream/autoDream.ts`

后台任务激活的多层门控，按计算成本从低到高排序：

```
Gate 1: config check (内存读) ─── 0μs
Gate 2: stat(lockFile).mtime  ─── 1μs（距上次整合 >= 24h？）
Gate 3: 内存变量 throttle    ─── 0μs（距上次扫描 >= 10min？）
Gate 4: readdir + stat 扫描   ─── ~5ms（新 session 够 5 个？）
Gate 5: lock file acquire     ─── ~10ms（PID 文件 + 后验校验）
```

大多数调用在 Gate 1-2 就被拦截，永远到不了 Gate 4-5。

**Orchestrator 适配**: 所有后台任务（采集器心跳检测、SOUL 自省、日志轮转）统一用门控链。当前的 cron 触发是"到点就跑"，应该改为"到点检查是否值得跑"。

### P0-2: Lock File mtime = State
**来源**: `services/autoDream/consolidationLock.ts`

lock 文件的 `mtime` 就是 `lastConsolidatedAt` 时间戳。不需要额外状态文件——`stat().mtime` 即状态。失败时 `utimes()` 回滚 mtime，崩溃时通过死 PID 检测回收。

**Orchestrator 适配**: Docker volume 内的 lock 文件替代 SQLite 做"上次运行时间"跟踪。比在数据库里维护一行 `last_run_at` 轻得多。

### P0-3: Optimistic Lock via Write-Then-Verify
**来源**: `services/autoDream/consolidationLock.ts`

```typescript
await writeFile(path, String(process.pid))
const verify = await readFile(path, 'utf8')
if (parseInt(verify.trim(), 10) !== process.pid) return null  // 输了，退让
```

无需 flock/advisory lock——文件系统原子写 + 后验校验 = 穷人版分布式锁。

**Orchestrator 适配**: 多容器竞争同一维护任务时（如数据库清理），用文件写+后验替代 Redis 分布式锁。

### P0-4: Bones-Soul Split Persistence
**来源**: `buddy/types.ts`, `buddy/companion.ts`

状态分为"可确定性重算的部分"（Bones：种族/属性/稀有度，从 hash 推导）和"不可重现的部分"（Soul：名字/性格，模型生成）。**只持久化 Soul，Bones 每次启动重算。**

好处：
- SPECIES 数组随便改，不需要数据迁移
- 用户编辑 config 也伪造不了稀有度
- 存储体积极小

**Orchestrator 适配**: Agent 人格（SOUL）的持久化策略。可推导的运行时状态（当前模型版本、工具列表）不存，只存不可重现的部分（对话摘要、用户偏好学习结果）。

### P0-5: Untrusted-Source Setting Exclusion
**来源**: `utils/paths.ts`

`projectSettings`（repo 内提交的 `.claude/settings.json`）被**故意排除**内存路径配置。原因：恶意 repo 可以设 `autoMemoryDirectory: "~/.ssh"` 获取写权限。只信任 policy/local/user 三个级别的配置。

**Orchestrator 适配**: 我们的 `.claude/settings.json` 已有信任层级，照搬——repo 内配置不能覆盖安全相关路径设置。

### P0-6: Address Scheme Registry
**来源**: `utils/peerAddress.ts`

统一寻址方案：

```typescript
function parseAddress(to: string): { scheme: 'uds' | 'bridge' | 'other', target: string }
```

一个函数解析目标地址，路由层根据 scheme 选择传输后端。

**Orchestrator 适配**:
```
docker:<container-name>  → Docker exec / gRPC
local:<agent-id>         → Agent SDK 内进程
tg:<chat-id>            → Telegram channel
ws:<session-id>         → WebSocket（Dashboard）
```
替代当前的 if/else 链路由。

### P0-7: Unified Executor Interface
**来源**: `swarm/backends/types.ts`

```typescript
type TeammateExecutor = {
  type: BackendType
  spawn(config): Promise<SpawnResult>
  sendMessage(agentId, message): Promise<void>
  terminate(agentId): Promise<boolean>
  isActive(agentId): Promise<boolean>
}
```

三种后端（tmux / iTerm2 / in-process）实现同一接口。调度层不关心执行方式。

**Orchestrator 适配**:
```typescript
interface AgentExecutor {
  type: 'docker' | 'in-process' | 'ssh'
  spawn(config: AgentConfig): Promise<AgentHandle>
  sendMessage(agentId: string, message: AgentMessage): Promise<void>
  terminate(agentId: string): Promise<boolean>
  isActive(agentId: string): Promise<boolean>
}
```

### P0-8: Unified Message Router
**来源**: `tools/SendMessageTool.ts`

一个 `sendMessage(to, message)` 入口，内部决策树：

```
parseAddress(to)
  ├── uds:   → sendToUdsSocket()
  ├── bridge: → postInterClaudeMessage()
  └── other  → agentRegistry.get(to)?
      ├── running → queuePendingMessage()
      ├── stopped → resumeAgentBackground()  // 自动唤醒！
      └── not found → writeToMailbox()
```

**关键**: 停止的 agent 收到消息会被**自动唤醒**（`resumeAgentBackground()`），不需要手动重启。

### P0-9: Session Registry Pattern
**来源**: `services/concurrentSessions.ts`

每个进程启动时写 PID 文件到 `~/.claude/sessions/<PID>.json`：

```json
{
  "pid": 12345,
  "sessionId": "abc",
  "cwd": "/project",
  "kind": "interactive",
  "messagingSocketPath": "/tmp/cc-socks/12345.sock"
}
```

活性检测：遍历目录 + `isProcessRunning(pid)`。崩溃清理：下次枚举时发现死 PID 自动删除。

**严格文件名校验**: `/^\d+\.json$/` 正则——防止 `parseInt` 把 `2026-03-14_notes.md` 解析为 PID 2026。

### P0-10: Progressive Bundle Fallback
**来源**: `utils/teleport/gitBundle.ts`

向远程运送工作区上下文时的三级降级：

```
1. git bundle create --all      → 完整 repo + refs/seed/stash (WIP)
   > 100MB? ↓
2. git bundle create HEAD       → 仅当前分支
   still too large? ↓
3. squashed-root commit         → 单个无父提交快照，无历史
```

WIP 通过 `git stash create` → `update-ref refs/seed/stash` 捕获，使其在 bundle 中可达。

### P0-11: Events-Before-Container
**来源**: `utils/teleport/api.ts` (`teleportToRemote`)

初始配置（权限模式、第一条消息）写入 threadstore **后** 容器才启动。容器读到的第一条事件就是正确的权限模式——消除了就绪竞态。

**Orchestrator 适配**: dispatch agent 时先写 Redis（任务描述、权限配置），再起容器。当前是容器启动后才通过 API 注入，存在竞态窗口。

### P0-12: Stateful Event Stream Classifier
**来源**: `commands/ultraplan.tsx` (`ExitPlanModeScanner`)

纯状态机，处理流式事件序列，输出分类结果：

```typescript
class ExitPlanModeScanner {
  ingest(newEvents: SDKMessage[]): 'approved' | 'teleport' | 'rejected' | 'pending' | 'terminated' | 'unchanged'
}
```

无 I/O、无副作用、纯状态转换。优先级：approved > terminated > rejected > pending > unchanged。

**Orchestrator 适配**: Agent 输出流的结构化解析——当前是正则匹配输出文本，应改为状态机分类器。

### P0-13: Three-Tier Feature Read
**来源**: GrowthBook 集成层

```
CACHED_MAY_BE_STALE  → sync，永不阻塞，render loop 安全
CACHED_OR_BLOCKING   → async，安全门控必须等到最新值
DEPRECATED           → 旧接口兼容
```

热路径永远不等待远程配置刷新。安全相关的门控必须等。

**Orchestrator 适配**: Docker 环境变量 + settings.json 两层，热路径读缓存，安全检查读最新。

### P0-14: Self-Contained Snapshot Coalescing
**来源**: `bridge/ccrClient.ts`

流式输出 100ms 窗口内合并，每次 flush 是**完整状态**而非 diff。迟到的客户端看到完整文本，不需要回放历史。

**Orchestrator 适配**: Dashboard 实时 agent 输出推送——当前是增量文本，应改为每次推送完整当前状态。

### P0-15: Structured Protocol Messages
**来源**: `swarm/teammateMailbox.ts`

10 种结构化消息类型（permission_request/response、shutdown_request/response、plan_approval 等），通过 `isStructuredProtocolMessage()` 判别。纯文本消息和协议消息共用同一通道。

**Orchestrator 适配**: Redis Streams 替代文件邮箱，保持类型系统：
- `task_assignment` / `task_result` / `permission_request` / `permission_response` / `shutdown` / `heartbeat`
- Consumer Group 替代 `read: boolean` 标记

### P0-16: Session Overage Confirmation
**来源**: `services/api/ultrareviewQuota.ts`

每 session 一次性确认计费，确认后自动放行。关键：**只在操作成功后才持久化标志**——Escape 取消不置位，防止用户误触后被收费。

**Orchestrator 适配**: 任何需要用户确认的高成本操作（大量 API 调用、GPU 密集任务），用同样的"确认一次，本次会话放行"模式。

---

## P1 可偷模式（10 个）

| # | 模式 | 来源 | 描述 |
|---|------|------|------|
| P1-1 | **Two-State Delivery** | useInboxPoller.ts | Agent 忙时排队，idle 时 drain。解决 concurrent message 问题 |
| P1-2 | **Permission Bridge** | leaderPermissionBridge | 审批支持 `updatedInput`（修改工具参数后放行）|
| P1-3 | **Tick-Driven Proactive Loop** | Kairos state | 定期 tick + 15s blocking budget + AFK 检测 |
| P1-4 | **Control Protocol** | bridgeMessaging.ts | Dashboard → Agent 的 interrupt/set_model/set_mode |
| P1-5 | **Auto-Resume on Message** | SendMessageTool.ts | Agent 停止后收到消息自动唤醒 |
| P1-6 | **Closure-Scoped Agent State** | autoDream.ts | 状态封在闭包内而非模块顶层，测试时调初始化即干净 |
| P1-7 | **Background-Agent-as-Visible-Task** | DreamTask | 后台 agent 通过 Task 注册暴露到 UI（footer pill + 详情弹窗）|
| P1-8 | **4-Phase Consolidation Prompt** | consolidationPrompt.ts | Orient → Gather → Consolidate → Prune 记忆整理框架 |
| P1-9 | **Keyword Trigger with Context Exclusion** | keyword.ts | 智能关键词检测，跳过引号/路径/问号后缀 |
| P1-10 | **Config Read with Type Guard + Bounds Clamp** | reviewRemote.ts | `posInt(value, fallback, max)` 防御性配置读取 |

---

## P2 长远模式（5 个）

| # | 模式 | 来源 | 描述 |
|---|------|------|------|
| P2-1 | **BoundedUUIDSet Echo Dedup** | bridgeMessaging.ts | 环形缓冲 + Set，O(1) 查找淘汰，用于消息去重 |
| P2-2 | **Session Kind Hierarchy** | concurrentSessions.ts | interactive/bg/daemon/daemon-worker 决定生命周期策略 |
| P2-3 | **Local-Preferred Dedup** | replBridgeHandle.ts | 多通道可达时优先本地，避免重复投递 |
| P2-4 | **Rolling Timezone Launch Window** | useBuddyNotification.ts | 用本地日期做 feature launch，24h 全球滚动 buzz |
| P2-5 | **Parameterized ASCII Sprite System** | buddy/sprites.ts | 占位符模板 + 属性注入，18×6×8=864 种组合 |

---

## 与 Round 23 P1 的关系

P1 偷了 **12 个执行层模式**（Agent Loop / Continue Sites / Compaction / Permission）。
P2 偷了 **31 个功能层模式**（16 P0 + 10 P1 + 5 P2）。

**零重叠**——P1 关注的是 `query.ts` 主循环和工具执行，P2 关注的是 feature-gated 隐藏系统。

---

## 实施路线图

### 本周（立即）

| 模式 | 预计工时 | 影响 |
|------|---------|------|
| Cheapest-First Gate Chain | 2h | 后台任务调度全面升级 |
| Lock File mtime = State | 1h | 零依赖状态追踪 |
| Events-Before-Container | 2h | 消除 agent dispatch 竞态 |
| Untrusted-Source Setting Exclusion | 1h | 安全加固 |

### 下周

| 模式 | 预计工时 | 影响 |
|------|---------|------|
| Address Scheme Registry | 4h | 统一寻址，替代 if/else 路由 |
| Unified Executor Interface | 4h | Agent 调度抽象层 |
| Unified Message Router | 3h | 单入口消息路由 |
| Session Registry | 2h | Agent 发现与状态枚举 |

### 下下周

| 模式 | 预计工时 | 影响 |
|------|---------|------|
| Stateful Event Stream Classifier | 3h | Agent 输出结构化解析 |
| Progressive Bundle Fallback | 4h | 工作区上下文运送 |
| Self-Contained Snapshot Coalescing | 2h | Dashboard 实时输出推送 |
| Structured Protocol Messages | 4h | Redis Streams 消息类型系统 |

### 远期

Three-Tier Feature Read / Two-State Delivery / Tick-Driven Proactive Loop / Control Protocol / Background-Agent-as-Visible-Task

---

## 最有价值的 3 个发现

1. **Address Scheme Registry + Unified Router + Unified Executor = 完整的多 Agent 通信框架**。这三个组合起来，就是我们缺的"Agent 操作系统"核心。当前 Orchestrator 的 agent 调度是 ad-hoc 的——Docker exec 一条路径，Agent SDK 一条路径，Telegram 一条路径。统一后所有路由逻辑集中在一个 `sendMessage(to, message)` 入口。

2. **Cheapest-First Gate Chain 是通用的后台任务范式**。不是"到点就跑"，而是"到点检查是否值得跑"。五层门控从 0μs 到 10ms，99% 的无效调用在最廉价层被拦截。这个模式可以套到采集器、SOUL 自省、日志轮转、所有后台任务。

3. **Events-Before-Container 消除了一整类竞态 bug**。先写配置，再起容器。简单到不需要解释，但我们一直在犯"容器起了再注入配置"的错误。
