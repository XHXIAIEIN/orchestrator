# Round 23: Claude Code v2.1.88 Source @sanbuphy — 深挖报告

> 来源: https://github.com/sanbuphy/claude-code-source-code
> 性质: Anthropic Claude Code CLI 反编译 TypeScript 源码（npm 包 `@anthropic-ai/claude-code` unbundle）
> 规模: **1,884 文件 / ~134,572 LOC** TypeScript + React (Ink)
> 注意: 108 个 feature-gated 模块因编译时 dead-code elimination 永久缺失

---

## 架构全景

```
src/
├── query.ts                    # 主循环（1,729 LOC）— AsyncGenerator 流式 Agent Loop
├── coordinator/                # 多 Agent 编排（Coordinator/Worker 模式）
├── tools/                      # 40+ 内置工具（AgentTool/BashTool/FileEditTool/...）
├── services/
│   ├── compact/                # 三层 Context 压缩（auto/micro/session-memory）
│   ├── api/                    # Claude API 集成
│   ├── tools/                  # StreamingToolExecutor 并发工具执行
│   ├── plugins/                # 插件注册表
│   └── SessionMemory/          # 会话持久化
├── hooks/                      # 事件驱动可扩展性
├── permissions/                # 三层权限框架
├── bootstrap/state.ts          # 全局状态（memoized init + telemetry）
├── skills/bundled/             # 内置 Skill 系统
├── bridge/                     # 远程执行协议（CCR bridge）
└── components/                 # React Ink 终端 UI
```

**核心循环**: `query.ts` 是一个 **AsyncGenerator**，yield 各种事件类型（stream_request_start / text / tool_result / progress），外部消费者通过迭代协议接收，`.return()` 取消执行。这不是回调地狱，也不是 Promise 链——是一个惰性求值的状态机。

---

## 可偷模式

### P0-1: AsyncGenerator Agent Loop（异步生成器主循环）

**位置**: `src/query.ts` (1,729 LOC)

**机制**: 整个 Agent 执行循环是一个 `async function*`，每轮迭代 yield 事件：

```typescript
export async function* query(params: QueryParams): AsyncGenerator<
  StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage,
  Terminal
>
```

核心循环结构:
1. 校验配置
2. 调用 Claude API（流式）
3. yield 响应事件（UI 实时渲染）
4. 执行工具（经权限门控）
5. 追加工具结果
6. 决策树: 继续 / 压缩 / 重试 / 终止

**为什么值得偷**: Orchestrator 当前 `executor.py` 用简单 async/await，没有流式中间态。AsyncGenerator 模式让消费者（Dashboard / TG bot / CLI）可以订阅任意粒度的进度事件，而不是等完成后一次性返回。更关键的是：`.return()` 提供了原生取消机制，不需要额外的 abort flag。

**Orchestrator 适配**:
- Python 等价物: `async def query(...) -> AsyncGenerator[Event, None]`
- `yield StreamEvent(type="tool_start", tool="bash", input=...)` 替代当前的 `run_log.append()`
- Governor 消费这个 generator 实现实时审批拦截

**与已有模式对比**: Round 2 OpenHands 的 EventStream 是事件总线（发布-订阅），这里是生产者-消费者（pull-based）。两者互补：EventStream 用于跨模块广播，AsyncGenerator 用于单条执行链的流式控制。

---

### P0-2: Continue Sites（续行站点错误恢复）

**位置**: `src/query.ts` 内部状态转移

**机制**: 主循环不用 try-catch 嵌套处理错误，而是用**显式状态转移**——遇到错误时修改 state 的 `transition` 字段，然后 `continue` 回到循环顶部：

```typescript
// 遇到 max_output_tokens 溢出
state = { ...state, transition: 'reactive_compact' }
continue  // 回到循环顶部，走压缩分支

// 遇到 API 过载
state = { ...state, transition: 'retry', backoff: calculateBackoff() }
continue
```

**9 个 continue site**:
- `reactive_compact`: context 超限 → 触发压缩后重试
- `retry`: API 错误 → 指数退避重试
- `tool_error`: 工具执行失败 → 合成错误消息给模型
- `permission_denied`: 权限拒绝 → 降级到只读模式
- （其他 5 个涉及 feature-gated 模块，无法还原）

**为什么值得偷**: 传统 try-catch 嵌套 3 层以上就不可读了。Continue site 让每条恢复路径都是循环顶部的一个 `if (state.transition === 'X')` 分支，**可审计、可测试、可扩展**。添加新的错误恢复只需加一个 transition 类型 + 对应分支。

**Orchestrator 适配**:
- `executor.py` 的 `dispatch()` 目前 try-except 包裹整个调用。改为状态机：
  ```python
  class Transition(Enum):
      NORMAL = "normal"
      REACTIVE_COMPACT = "reactive_compact"
      RETRY = "retry"
      ESCALATE = "escalate"  # 上报三省六部
  ```
- 每轮循环检查 `state.transition`，走对应分支

**与已有模式对比**: Round 2 的 StuckDetector 检测卡死后触发恢复。Continue site 更通用——不只处理"卡住"，而是所有类型的异常都统一走状态转移。

---

### P0-3: Triple Compaction（三层 Context 压缩）

**位置**: `src/services/compact/`（11 个模块）

**三层策略**:

| 层 | 名称 | 触发条件 | 机制 | Token 开销 |
|----|------|---------|------|-----------|
| L1 | **Microcompact** | input_tokens > 180K | 服务端 `context_edits` 指令，清除工具输入/输出 | **0**（API 端执行） |
| L2 | **Session Memory Compact** | 在 L3 之前 | 独立总结会话记忆，与主对话分离 | 中 |
| L3 | **Auto-compact** | input_tokens 仍超限 | 调用 API 总结旧消息，保留最近 ~40K tokens | 高 |

**Microcompact 细节**（最有价值的发现）:

```typescript
{
  type: 'clear_tool_uses_20250919',
  trigger: { type: 'input_tokens', value: 180_000 },
  clear_at_least: { type: 'input_tokens', value: 140_000 },
  clear_tool_inputs: ['bash', 'grep', 'find']
}
```

这是 API 原生能力——在请求中附带 `context_edits`，服务端直接裁剪指定工具的输入/输出，**不消耗额外 token**。比客户端压缩快 10x+。

**Circuit Breaker**: Auto-compact 连续失败 3 次后停止尝试，避免无限循环。

**为什么值得偷**: Orchestrator 的 agent dispatch 是无状态的（每次派单新 session），但主进程（Claude Code 本身）会话越来越长。我们用的是 Claude Code 自身的压缩，但没有主动管理。了解它的三层策略，可以在 Governor 层面更智能地决定何时该压缩、何时该新开会话。

**Orchestrator 适配**:
- **L1 已有**: Claude Code 的 microcompact 对我们透明生效
- **L2 可偷**: `session-state.md` 的更新逻辑可以参考 session memory compact 的时机（在主压缩前先保存关键状态）
- **L3 策略可偷**: Circuit breaker 模式——连续 3 次压缩失败后，自动新开会话而不是继续压缩

---

### P0-4: Three-Tier Permission Gate（三层权限门控）

**位置**: `src/permissions/`, `src/hooks/toolPermission/`, `src/utils/permissions/PermissionMode.ts`

**三层决策流**:

```
工具调用 → [Pre-use Hook] → [Pattern Rule] → [Interactive Prompt]
   │            │                  │                  │
   │       插件可提前拦截      正则匹配允许/拒绝    用户逐一确认
   │            ↓                  ↓                  ↓
   │       allow/deny          allow/deny          allow/deny/ask
   └────────────────────────────────────────────────────→ 执行
```

**Layer 1 — Pre-use Hook**: 插件和 skill 可以注册 `AllowToolUse` hook，在权限检查之前拦截：
```typescript
type PermissionDecision =
  | { behavior: 'allow'; updatedInput: Record<string, unknown> }
  | { behavior: 'deny'; message: string; interrupt?: boolean }
  | { behavior: 'ask' }  // 透传到下一层
```

**Layer 2 — Pattern Rule**: `settings.json` 中的正则规则：
```json
{
  "toolPermissionRules": {
    "bash": {
      "allow": ["git status", "npm test"],
      "deny": ["rm -rf /"]
    }
  }
}
```
使用 shell tokenization 感知的正则匹配，不是简单字符串包含。

**Layer 3 — Interactive Prompt**: 前两层都没匹配时，弹 UI 让用户确认。

**Permission Modes**: `default`(逐一确认) / `plan`(只读) / `acceptEdits`(自动批准编辑) / `bypassPermissions`(全放行) / `dontAsk`(静默拒绝，给 agent 用) / `auto`(内部分类器)

**远程覆盖**: 后端托管设置可以覆盖本地 `settings.json`，实现 IT 策略管控。

**为什么值得偷**: 我们的 `guard.sh` 是单层 bash 脚本拦截。没有"先 hook 再规则再交互"的分层。添加新安全规则要改 bash 脚本，没有声明式配置。

**Orchestrator 适配**:
- guard.sh 保持作为 Layer 1（shell-level 硬拦截）
- 新增 Layer 2: `permission_rules.yaml` 声明式规则（正则匹配工具 + 参数）
- Layer 3: Governor 审批作为最后一道防线
- `PermissionDecision` 三值返回（allow/deny/escalate）替代 guard.sh 的二值（pass/block）

---

### P1-1: Streaming Tool Executor（流式并发工具执行器）

**位置**: `src/services/tools/StreamingToolExecutor.ts` (~400 LOC)

**机制**: 工具执行有两种模式：
- **Streaming**: 实时 yield 进度（用于 Bash、文件读取等长操作）
- **Batch**: 并发执行多个工具，带权限门控

关键设计: `isConcurrencySafe()` 方法决定工具是否可以并发执行。文件编辑不能并发（可能冲突），grep 搜索可以。

**与已有模式对比**: Round 17 VibeVoice 的 Queue-per-Agent 是消息队列隔离，这里是工具级的并发安全标记。更细粒度。

---

### P1-2: Content Replacement State（内容替换状态）

**位置**: 整个 `query.ts` 循环中的状态追踪

```typescript
type ContentReplacementState = {
  records: { toolUseId: string, replacedAt: number }[]
}
```

**机制**: 当工具结果超过 `maxResultSizeChars` 时，结果被替换为摘要引用。所有 fork（子 agent）继承父进程的替换记录，避免重复传输。

**为什么值得偷**: Agent dispatch 时，工具结果（特别是 grep 大量输出）会撑爆 context。有了替换状态，可以只传摘要 + 引用 ID，子 agent 需要完整内容时再按 ID 取回。

---

### P1-3: Checkpoint Profiling（检查点性能剖析）

**位置**: 散布在 `query.ts` 关键节点

```typescript
queryCheckpoint('init_configs_enabled')
queryCheckpoint('init_after_graceful_shutdown')
queryCheckpoint('api_call_start')
queryCheckpoint('tool_execution_complete')
```

**机制**: 轻量级时间戳标记，不需要 OpenTelemetry 全家桶。每个 checkpoint 记录名称 + 时间戳，事后分析延迟瓶颈。

**为什么值得偷**: Orchestrator 当前的 `run_log` 只记录结果，不记录耗时分布。加 checkpoint 后可以知道"Governor 审批花了 3 秒"还是"API 调用花了 15 秒"。对排查慢任务极其有用。

**Orchestrator 适配**: 在 `executor.py` 的关键路径加 `checkpoint(name)` 调用，写入 `events.db` 的新表 `checkpoints(session_id, name, timestamp_ms)`。

---

### P1-4: Render-Time Prompt Injection（渲染时 Prompt 注入）

**位置**: `query.ts` 主循环，每次 API 调用前

**机制**: System prompt 不是在启动时一次性构建，而是**每次 API 调用前现场组装**：

```typescript
// 每轮迭代重新构建 system prompt
const systemPrompt = buildSystemPrompt({
  availableTools: currentTools,     // 可能因权限变化而不同
  workingDirectory: cwd,            // 可能 cd 了
  featureFlags: getActiveFlags(),   // 可能运行中开启
  coordinatorMode: isCoordinator(), // 可能切换了模式
  agentDefinitions: loadAgents(),   // 可能新增了 agent
})
```

**为什么值得偷**: Orchestrator 的 `boot.md` 是编译时产物，session 内不变。但如果 Governor 在会话中途更新了规则、或者三省六部的状态变了，当前 prompt 不会反映这些变化。Render-time injection 让 prompt 始终是最新态。

**Orchestrator 适配**: `context_pack.py` 的输出不应该缓存到 `boot.md` 后就不动了。可以在 executor 每次 dispatch 前重新调用 `compile_boot()` 的轻量版本，至少刷新动态部分（当前任务状态 / Governor 规则 / 最新 checkpoint）。

---

### P1-5: Coordinator Scratchpad（协调器共享草稿板）

**位置**: `src/coordinator/coordinatorMode.ts`

**机制**: Coordinator 模式下，所有 Worker 共享一个 **scratchpad 目录**作为跨 worker 通信通道：

```
.claude/scratchpad/
├── worker-1-findings.md    # Worker 1 的研究结果
├── worker-2-changes.md     # Worker 2 的代码变更
└── shared-context.md       # Coordinator 整理的共享上下文
```

Worker 之间不直接通信，通过文件系统实现异步知识共享。Coordinator 负责读取、整合、分发。

**与已有模式对比**: 三省六部的派单是单向的（中书省→尚书省→六部）。Scratchpad 是一个松耦合的共享状态层，任何 worker 都可以写入，coordinator 聚合。

---

### P2-1: Memoized Init Guard（单次初始化守卫）

**位置**: `src/bootstrap/state.ts`

```typescript
import memoize from 'lodash-es/memoize'
export const init = memoize(async () => {
  // 初始化 telemetry, OTLP, session ID, etc.
  // 绝不会执行第二次
})
```

**为什么值得偷**: 简单但有效。Orchestrator 的 `boot.md` 编译可能在热重载时被多次触发。Memoize 保证幂等。

---

### P2-2: Feature Gate Dead Code Elimination（特性门控死代码消除）

```typescript
if (feature('VOICE_MODE')) { /* 整块代码编译时删除 */ }
if (feature('REACTIVE_COMPACT')) { /* 实验性功能 */ }
```

**机制**: `bun:bundle` 在编译时将 feature flag 求值为常量，未启用的分支被 tree-shaker 完全删除。结果是发布包里找不到任何未上线功能的代码。

**Orchestrator 适配**: 我们是 Python，没有编译时 tree-shaking。但可以用类似模式做运行时 feature gate，配合 `config.yaml` 的 feature flags 控制实验性模块的加载。

---

### P2-3: Lazy Telemetry Loading（懒加载遥测）

```typescript
// OpenTelemetry 800KB，只在启用时才加载
if (telemetryEnabled) {
  const otel = await import('@opentelemetry/sdk-node')
}
```

**为什么提**: Orchestrator 在 Docker 里，启动时间不敏感。但如果将来做桌面轻客户端，这个模式值得参考。

---

## 与 Orchestrator 现有架构对比

| 维度 | Claude Code | Orchestrator | 差距 |
|------|------------|-------------|------|
| 主循环 | AsyncGenerator 流式 | async/await 单次返回 | **大** — 缺少流式中间态 |
| 错误恢复 | 9 个 Continue Site | try-except 包裹 | **大** — 不可审计 |
| Context 压缩 | 三层（micro/session/auto）| 依赖 Claude Code 内置 | **中** — 可主动管理时机 |
| 权限 | 三层（hook→rule→prompt）| guard.sh 单层 | **大** — 缺声明式规则 |
| 工具并发 | isConcurrencySafe 标记 | 无并发工具执行 | **中** |
| 性能剖析 | Checkpoint profiling | run_log 只记结果 | **中** |
| Prompt 构建 | 每次调用现场组装 | 编译时固定 boot.md | **中** — 动态部分不刷新 |
| 多 Agent 通信 | Scratchpad 文件共享 | 三省六部单向派单 | **小** — 已有方案，可增强 |

---

## 实施优先级

### 必偷（P0）— 4 个

| # | 模式 | 预估工作量 | 落地位置 |
|---|------|-----------|---------|
| 1 | AsyncGenerator Agent Loop | 2-3 天 | `executor.py` 重构为 generator |
| 2 | Continue Sites | 1 天 | `executor.py` 状态机 |
| 3 | Triple Compaction 策略 | 1 天 | `governor.py` 压缩决策 + circuit breaker |
| 4 | Three-Tier Permission Gate | 2 天 | `guard.sh` → `permission_rules.yaml` + 三层流程 |

### 值得偷（P1）— 5 个

| # | 模式 | 预估工作量 | 落地位置 |
|---|------|-----------|---------|
| 1 | Streaming Tool Executor | 1 天 | executor 工具并发标记 |
| 2 | Content Replacement State | 0.5 天 | dispatch 时大输出替换 |
| 3 | Checkpoint Profiling | 0.5 天 | events.db 新表 |
| 4 | Render-Time Prompt Injection | 1 天 | compile_boot 动态刷新 |
| 5 | Coordinator Scratchpad | 0.5 天 | 三省六部共享上下文目录 |

### 可偷（P2）— 3 个

| # | 模式 | 说明 |
|---|------|------|
| 1 | Memoized Init Guard | Python `functools.lru_cache` 等价 |
| 2 | Feature Gate | config.yaml feature flags |
| 3 | Lazy Telemetry | 桌面客户端时再考虑 |

---

## 关键 Insight

1. **Claude Code 不是对话系统，是状态机**。表面上看是聊天，底层是一个 9 态的执行循环。每条消息不是"回复"，是状态转移的产物。Orchestrator 可以从这个视角重新审视 executor——不是"调用 API 然后返回结果"，而是"进入循环，每轮 yield 事件，直到达到终态"。

2. **权限是分层的，不是二值的**。guard.sh 的 pass/block 是最简模型。生产级系统需要"hook 可以改写输入"（比如自动加 --dry-run）、"规则可以有例外"（比如 git push 在特定分支上自动放行）、"最后一道防线是人"。三层模型让每层各司其职。

3. **134K 行代码里最核心的只有 1,729 行**。`query.ts` 一个文件承载了整个 Agent 的智慧。其余都是工具实现、UI 渲染、基础设施。这印证了一个设计哲学：**核心循环要足够小，小到一个人能完全理解**。

4. **Microcompact 是 Anthropic 的隐藏 API 能力**。客户端可以在请求中附带 `context_edits` 指令，让服务端裁剪旧工具结果，零额外 token 开销。这个能力没有在公开 API 文档中出现，但 Claude Code 大量使用。如果这个能力开放给 SDK 用户，Orchestrator 的长会话管理会简单很多。
