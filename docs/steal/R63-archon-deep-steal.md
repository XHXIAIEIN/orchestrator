# R63 Archon 深度偷师报告 — Worktree 所有权守卫 + 工作流并发锁 + Provider 注册表

> **仓库**: https://github.com/coleam00/Archon  
> **克隆路径**: `D:/Agent/.steal/archon/`  
> **分析日期**: 2026-04-14  
> **本轮焦点**: R47 之后（2026-04-06 后）916+ insertions 的增量，重点在 worktree 所有权守卫、工作流并发路径锁、Provider 注册表系统  
> **上次报告**: R47（2026-04-11，读过整体架构）  
> **分支**: `steal/round-deep-rescan-r60`

---

## 核心发现摘要

R47 读了架构轮廓。这次深读源码后，最大的收获有三个：

1. **Worktree 所有权守卫是个四层防御**——不是一个函数，是从 git 包一路到 resolver 的完整链条，每个采用路径（workflow reuse、linked issue、PR branch adoption）都有独立 ownership check，防止两个 clone 互相劫持 worktree。

2. **Path-lock 是基于 DB 行做分布式锁**——用 `working_path` 作为锁 token，`pending/running/paused` 状态即"持锁"，terminal 状态即"释锁"。加了"older-wins"决策机制防止两个同时 dispatch 互相 abort。

3. **Provider 注册表是 Phase 2 社区化的关键基础**——从硬编码 switch 重构成 `Map<string, ProviderRegistration>`，社区 provider 无需改核心代码就能接入。

---

## 增量 commits 全景（R47 之后）

```
33d31c4  fix: lock workflow runs by working_path (#1212)
5a4541b  fix: route canonical path failures through blocked classification
fd3f043  fix: extend worktree ownership guard to resolver adoption paths (#1206)
af9ed84  fix: prevent worktree isolation bypass via prompt and git-level adoption (#1198)
d6e24f5  feat: Phase 2 — community-friendly provider registry system (#1195)
b5c5f81  refactor: extract provider metadata seam for Phase 2 registry readiness
bf20063  feat: propagate managed execution env to all workflow surfaces (#1161)
a8ac3f0  security: prevent target repo .env from leaking into subprocesses (#1135)
37aeadb  refactor: decompose provider sendQuery() into explicit helper boundaries
c1ed765  refactor: extract providers from @archon/core into @archon/providers
```

关键统计：851 行净增（仅 workflow lock commit），916+ 行增量（整体 R47 后）。

---

## 六维扫描

### 维度 1：安全 / 治理（核心）

#### 1a. Worktree 所有权守卫——四层防御链

**背景问题**：两个 clone 同一个远端仓库时，`codebase_id` 相同（从 owner/repo 派生）。若无守卫，clone B 会通过 DB 找到 clone A 的 worktree 并"采用"它，向错误的文件系统写代码。

**守卫机制核心**——`verifyWorktreeOwnership`（`packages/git/src/worktree.ts:280`）：

```typescript
export async function verifyWorktreeOwnership(
  worktreePath: WorktreePath,
  expectedRepo: RepoPath
): Promise<void> {
  let gitContent: string;
  try {
    gitContent = await readFile(join(worktreePath, '.git'), 'utf-8');
  } catch (error) {
    const err = error as NodeJS.ErrnoException;
    if (err.code === 'EISDIR') {
      // .git 是目录 = 完整 checkout，不是 worktree，拒绝采用
      throw wrap(`Cannot adopt ${worktreePath}: path contains a full git checkout`);
    }
    throw wrap(`Cannot verify worktree ownership at ${worktreePath}: ${err.message}`);
  }
  // worktree 的 .git 文件内容格式: "gitdir: /path/to/.git/worktrees/branch"
  const match = /gitdir: (.+)\/\.git\/worktrees\//.exec(gitContent);
  if (!match) {
    throw new Error(`Cannot adopt ${worktreePath}: .git pointer is not a git-worktree reference.`);
  }
  // 解析出指向的 repo 路径，对比 expectedRepo
  const existingRepoRaw = match[1];
  if (resolve(existingRepoRaw) !== resolve(expectedRepo)) {
    throw new Error(
      `Worktree at ${worktreePath} belongs to a different clone (${existingRepoRaw}).`
    );
  }
}
```

**错误码保留**（关键细节）：
```typescript
const wrap = (message: string): Error => {
  const wrapped = new Error(message, { cause: err });
  if (err.code) (wrapped as NodeJS.ErrnoException).code = err.code;
  return wrapped;
};
```
保留 `.code`（EISDIR/ENOENT/EACCES）让下游 `classifyIsolationError` 按 errno 匹配，而不是依赖 Node.js 消息格式（跨版本不稳定）。

**四条采用路径全部接入守卫**（`packages/isolation/src/resolver.ts`）：

| 路径 | 方法 | 守卫调用 | 日志事件 |
|-----|------|---------|---------|
| 按 workflow identity 复用 | `findReusable()` | `assertWorktreeOwnership()` | `isolation.reuse_refused_cross_checkout` |
| 按 linked issue 复用 | `findLinkedIssueEnv()` | `assertWorktreeOwnership()` | `isolation.linked_issue_refused_cross_checkout` |
| 按 PR 分支采用 | `tryBranchAdoption()` | `assertWorktreeOwnership()` | `isolation.branch_adoption_refused_cross_checkout` |
| canonical 路径解析失败 | `resolve()` 入口 | `isKnownIsolationError()` → `blocked` | `isolation.canonical_repo_path_resolution_failed` |

PR #1206（`fd3f043`）之前只有 `WorktreeProvider.findExisting()` 有守卫，三条 resolver 层路径完全暴露。这是个高危安全漏洞，PR 里明确说 "two clones of the same remote share codebase_id"。

**`canonicalRepoPath` 提前计算**（架构优化）：
```typescript
// resolve() 顶部一次性计算，所有子路径复用
let canonicalPath: RepoPath;
try {
  canonicalPath = await getCanonicalRepoPath(codebase.defaultCwd);
} catch (error) {
  if (!isKnownIsolationError(err)) throw err;  // 未知错误直接崩溃，不静默
  return { status: 'blocked', reason: 'creation_failed', userMessage: ... };
}
```

#### 1b. 目标 repo .env 防泄漏

**问题**：Bun 自动加载 CWD 下的 `.env` 文件。当 `cwd` 是目标 repo 时，repo 里的 `.env`（含 AWS key 等）会污染 `process.env`，进而传给 Claude Code 子进程。

**最终解法**（`a8ac3f0`，架构层面而非扫描层面）：
```typescript
// packages/providers/src/claude/provider.ts
executableArgs: ['--no-env-file'],  // 防止 Claude Code 子进程加载 cwd .env
```

配合启动时的 `stripCwdEnv()`：
```
flow: stripCwdEnv() at boot → 清除 CWD .env 注入的 key
    → ~/.archon/.env 加载为可信来源
    → process.env 干净
    → subprocess 继承干净 process.env
    → Claude Code 子进程 --no-env-file 防止再次加载 repo .env
```

**R47 报告的 Env Leak Scanner 被整体删除**——那是错误的原语（扫描/同意）。现在是结构性防护，不需要用户确认。

---

### 维度 2：记忆 / 学习

Archon 的"记忆"是 session 连续性，通过 session resume 实现。

**Session 状态机**（`packages/core/src/state/session-transitions.ts`）：

```typescript
export type TransitionTrigger =
  | 'first-message'      // 无现有 session
  | 'plan-to-execute'    // 规划完成，开始执行
  | 'isolation-changed'  // worktree 变更
  | 'reset-requested'    // /reset 命令
  | 'worktree-removed'   // worktree 被手动删除
  | 'conversation-closed'; // 平台会话关闭

const TRIGGER_BEHAVIOR: Record<TransitionTrigger, 'creates' | 'deactivates' | 'none'> = {
  'plan-to-execute': 'creates',  // 唯一立即创建新 session 的触发
  // 其他 deactivates: 只停旧 session，下次消息再创建
};
```

`plan-to-execute` 自动检测：
```typescript
export function detectPlanToExecuteTransition(
  commandName: string, lastCommand: string
): TransitionTrigger | null {
  if (commandName === 'execute' && lastCommand === 'plan-feature') return 'plan-to-execute';
  if (commandName === 'execute-github' && lastCommand === 'plan-feature-github') return 'plan-to-execute';
  return null;
}
```

**DAG 断点续跑**（`packages/workflows/src/executor.ts`）：

```typescript
// 查找同一 workflow + worktree 的上次 failed run
resumableRun = await deps.store.findResumableRun(workflow.name, cwd);
// 加载已完成节点的输出（用于 $node_id.output 变量替换）
priorNodes = await deps.store.getCompletedDagNodeOutputs(resumableRun.id);
// 跳过已完成节点，从断点重新运行
// 通知用户：▶️ Resuming workflow `name` — skipping N already-completed node(s).
// 注意：AI session context 不恢复，依赖前序节点上下文的节点需重读 artifacts
```

---

### 维度 3：执行 / 编排（核心，60% 重量）

#### 3a. DAG 工作流引擎（R47 已知，本次深入节点类型）

**7种节点类型**（`packages/workflows/src/schemas/dag-node.ts`）：

| 节点类型 | 字段 | 用途 |
|---------|------|------|
| `command` | `command: string` | 加载 `.archon/commands/name.md` |
| `prompt` | `prompt: string` | 内联 prompt |
| `bash` | `bash: string` | 无 AI 的 shell 脚本 |
| `script` | `script: string`, `runtime: 'bun'|'uv'` | TS/Python 脚本 |
| `loop` | `loop: LoopNodeConfig` | AI prompt 循环直到完成信号 |
| `approval` | `approval: {message, capture_response, on_reject}` | 暂停等待人工审批 |
| `cancel` | `cancel: string` | 以给定原因终止工作流 |

**触发规则（trigger_rule）**：
```typescript
export const triggerRuleSchema = z.enum([
  'all_success',              // 默认：所有上游完成
  'one_success',              // 任一上游完成（用于竞速）
  'none_failed_min_one_success', // 无失败且至少一成功
  'all_done',                 // 无论成败，等所有上游完成
]);
```

**Kahn 算法拓扑排序**（`buildTopologicalLayers`）：
```typescript
// Layer 0: 无依赖节点（同层并发）
// Layer N: 所有依赖都在 0..N-1 层的节点
// 运行时循环检测：sum(layer sizes) < nodes.length 则有环
```

**节点变量替换**（`substituteNodeOutputRefs`）：
```typescript
// $node_id.output       → 节点完整输出文本
// $node_id.output.field → JSON 解析后取字段（数字/布尔不加引号）
// escapedForBash=true 时用 shell quote 包装（防注入）
```

#### 3b. Idle Timeout——把挂死转成干净退出

**核心问题**：MCP 连接没关闭、子进程没退出时，`for await` 永远阻塞，`node_completed` 永远不写入。

**解法**（`packages/workflows/src/utils/idle-timeout.ts`）：

```typescript
export async function* withIdleTimeout<T>(
  generator: AsyncGenerator<T>,
  timeoutMs: number,   // 默认 30 分钟
  onTimeout?: () => void,
  shouldResetTimer?: (value: T) => boolean
): AsyncGenerator<T> {
  while (true) {
    const timeoutPromise = new Promise(resolve => setTimeout(resolve, remaining, IDLE_TIMEOUT_SENTINEL));
    const nextPromise = generator.next();
    const result = await Promise.race([nextPromise, timeoutPromise]);
    
    if (result === IDLE_TIMEOUT_SENTINEL) {
      nextPromise.catch(() => {}); // 防止 unhandled rejection
      onTimeout?.();               // abort subprocess
      return;                      // 不 throw，干净退出
    }
    // 每次收到值重置计时器（除非 shouldResetTimer 返回 false）
    yield result.value;
  }
}
```

**关键设计决策**：
- 超时时**不调用** `generator.return()`——会阻塞在 pending `.next()`
- `onTimeout` 通过 abort signal 异步清理子进程
- 是"死锁检测器"而非"工作时间限制器"——每条消息都重置计时器

#### 3c. Working Path Lock——DB 行作分布式锁

**问题**：两个 dispatch 解析到相同 worktree 路径，并发写同一 branch，代码互相破坏。

**机制**（`packages/core/src/db/workflows.ts`）：

```typescript
// 状态语义：pending/running/paused = 持锁，terminal = 释锁
// 5 分钟 stale-pending 窗口：超过 5 分钟的 pending 行视为 orphan（崩溃残留）
export const STALE_PENDING_AGE_MS = 5 * 60 * 1000;

export async function getActiveWorkflowRunByPath(
  workingPath: string,
  self?: { id: string; startedAt: Date }
): Promise<WorkflowRun | null> {
  // "older-wins" 决策：比较 (started_at, id) 总序
  // PostgreSQL: started_at TIMESTAMPTZ, cast ISO param to timestamptz
  // SQLite: datetime() 函数强制时序比较（直接字符串比较是错的，因为格式不同）
  const colExpr = isPostgres ? 'started_at' : 'datetime(started_at)';
  const paramExpr = isPostgres ? `${startedAtParam}::timestamptz` : `datetime(${startedAtParam})`;
  clauses.push(`(${colExpr} < ${paramExpr} OR (${colExpr} = ${paramExpr} AND id < ${idParam}))`);
}
```

**工作流程**：
```
dispatch A, B 同时到达
  → 各自创建 workflow_run 行（pending 状态）
  → 各自调用 getActiveWorkflowRunByPath(cwd, self={id, startedAt})
  → 先启动的 A 的 started_at 较早 → A 的 self 在查询中排除自己后找不到对手
  → B 的查询找到 A 的行 → B 将自己标记 cancelled → 返回 "worktree in use" 错误
```

**状态感知错误消息**：
```
running: "running X minutes, run `abc12345`" + Wait/Cancel/Use different branch
paused:  "paused waiting for user input"     + Approve/Reject/Cancel/Use different branch
```

**SQLite datetime() Bug 修复**（该 commit 的核心亮点）：
SQLite 存储 `CURRENT_TIMESTAMP` 为 `"YYYY-MM-DD HH:MM:SS"`（无时区），而传入参数是 ISO 8601 `"YYYY-MM-DDTHH:MM:SS.mmmZ"`。直接字符串比较时第 11 位是空格（0x20）vs T（0x54），所有 column 值都"早于"所有 ISO 参数，导致 `started_at < $param` 永远为 true，两个 dispatch 互相 abort。

---

### 维度 4：Context / Budget

#### 4a. Provider 注册表——能力感知的 Provider 选择

**问题**：一个 DAG 节点指定了某 provider 不支持的功能（如 Codex 不支持 MCP），应该怎么处理？

**解法**（`packages/providers/src/registry.ts` + `dag-executor.ts`）：

```typescript
// 每个 provider 声明能力 flags
export interface ProviderCapabilities {
  sessionResume: boolean;
  mcp: boolean;
  hooks: boolean;
  skills: boolean;
  toolRestrictions: boolean;
  structuredOutput: boolean;
  envInjection: boolean;
  costControl: boolean;
  effortControl: boolean;
  thinkingControl: boolean;
  fallbackModel: boolean;
  sandbox: boolean;
}

// dag-executor 在运行前检查能力并发 warning
const capChecks: [string, keyof ProviderCapabilities, boolean][] = [
  ['mcp', 'mcp', node.mcp !== undefined],
  ['hooks', 'hooks', node.hooks !== undefined],
  // ...
];
for (const [field, cap, isSet] of capChecks) {
  if (isSet && !caps[cap]) unsupported.push(field);
}
if (unsupported.length > 0) {
  await safeSendMessage(platform, conversationId,
    `Warning: Node '${node.id}' uses ${unsupported.join(', ')} but ${provider} doesn't support them`
  );
}
```

**Provider 从模型名推断**：
```typescript
// 'sonnet'/'opus'/'haiku'/以 'claude-' 开头 → claude provider
// 其他 → 当前配置的 provider（codex）
function inferProviderFromModel(modelName: string, configProvider: string): string
```

#### 4b. 节点级 effort/thinking 控制

```typescript
// YAML 节点可声明 thinking 的三种形式：
// thinking: adaptive   → { type: 'adaptive' }
// thinking: enabled    → { type: 'enabled' }
// thinking: disabled   → { type: 'disabled' }
// thinking:
//   type: enabled
//   budgetTokens: 10000
```

工作流级别默认值 + 节点级别 override，通过 `??` 合并：
```typescript
effort: node.effort ?? workflowLevelOptions.effort,
thinking: node.thinking ?? workflowLevelOptions.thinking,
```

---

### 维度 5：失败 / 恢复

#### 5a. 错误分类三级体系

```typescript
// FATAL：不重试（auth/permission/credits）
export const FATAL_PATTERNS = [
  'unauthorized', 'forbidden', 'invalid token', 'authentication failed',
  'permission denied', '401', '403', 'credit balance', 'auth error',
];

// TRANSIENT：指数退避重试
export const TRANSIENT_PATTERNS = [
  'timeout', 'econnrefused', 'rate limit', 'too many requests',
  '429', '503', '502', 'exited with code', 'claude code crash',
];

// 优先级：FATAL > TRANSIENT（防止 "unauthorized: exited with code 1" 被错误重试）
export function classifyError(error: Error): 'TRANSIENT' | 'FATAL' | 'UNKNOWN' {
  if (matchesPattern(message, FATAL_PATTERNS)) return 'FATAL';
  if (matchesPattern(message, TRANSIENT_PATTERNS)) return 'TRANSIENT';
  return 'UNKNOWN';
}
```

**节点默认重试**：`maxRetries=2, delay=3000ms, onError='transient'`（只重试 TRANSIENT，不重试 FATAL）。

**消息发送重试**（critical message 专用）：
- 普通消息：TRANSIENT 失败抑制，继续；FATAL 抛出
- Critical 消息（失败/完成通知）：最多 3 次，指数退避（1s, 2s, 3s）

**UNKNOWN 错误连续计数**（防止陷入未知循环）：
```typescript
const UNKNOWN_ERROR_THRESHOLD = 3;
if (errorType === 'UNKNOWN' && unknownErrorTracker) {
  unknownErrorTracker.count++;
  if (unknownErrorTracker.count >= UNKNOWN_ERROR_THRESHOLD) {
    throw new Error(`3 consecutive unrecognized errors — aborting workflow`);
  }
}
```

#### 5b. Orphan Cleanup——防止 DB 行成为永久锁

**四个清理点**（`executor.ts`）：

1. **Resume 取代 pre-created row**：`preCreatedRun.id != resumableRun.id` → 取消 pre-created
2. **Resume 激活失败**：取消 pre-created row，防止 pending 卡路径
3. **Path lock check 失败**：取消 workflowRun，释放 lock token
4. **Isolation store create 失败**（`resolver.ts`）：清理已创建的孤立 worktree

```typescript
// provider.create() 成功 → worktree 在磁盘存在
// store.create() 失败 → DB 行没写进去 → orphan worktree
try {
  env = await this.store.create({ ... });
} catch (storeError) {
  // 清理孤立 worktree
  await this.provider.destroy(isolatedEnv.workingPath, { force: true });
  throw err; // 重新抛出 store 错误
}
```

#### 5c. Credit 耗尽检测（流式输出内容）

Claude SDK 以普通 assistant text 形式返回 credit 耗尽，不抛异常：
```typescript
const CREDIT_EXHAUSTION_OUTPUT_PATTERNS = [
  "you're out of extra usage", 'out of credits', 'credit balance', 'insufficient credit',
];
// 每个消息 chunk 都调用 detectCreditExhaustion(text)
// 检测到后标记 FATAL，停止工作流
```

---

### 维度 6：质量 / 测试

#### 6a. Provider 单元测试策略

`packages/providers/src/claude/provider.ts` 中所有文件 I/O 和 logger 都用懒初始化模式：
```typescript
let cachedLog: ReturnType<typeof createLogger> | undefined;
function getLog(): ReturnType<typeof createLogger> {
  if (!cachedLog) cachedLog = createLogger('provider.claude');
  return cachedLog;
}
```
原因：模块加载时 `createLogger` 立即调用会在测试 mock 设置之前初始化，导致无法 intercept。lazy init 让测试可以在首次调用 `getLog()` 前设置 mock。

#### 6b. 工作流锁测试

`packages/workflows/src/executor-preamble.test.ts` + `executor.test.ts` 增加了 35+360 行测试，覆盖：
- SQLite datetime() vs ISO 字符串比较的边界 bug
- 两个 dispatch 的 older-wins 决策
- Resume 时 orphan pre-created row 的清理
- Path lock 查询失败时的自清理

#### 6c. E2E Smoke Test Workflows

`c9c6ab4` 增加了完整的 e2e smoke test workflow YAML 文件，验证整个执行链而非 unit mock。

---

## 五层深度分析——核心模块

### 模块：IsolationResolver

```
调度层（Dispatch）: orchestrator 调用 resolver.resolve(request)
  ↓
实践层（Practice）: 6 步 resolution 顺序（existing→no-codebase→reuse→linked→adoption→create）
  ↓
消费层（Consumer）: 每个步骤消费 store 查询结果 + git 命令输出
  ↓
状态层（State）: IsolationEnvironmentRow 在 DB 中；worktree 在磁盘上；两者可以不一致（需要清理）
  ↓
边界层（Boundary）: isKnownIsolationError() + classifyIsolationError() 把 known errors → blocked
                    unknown errors → throw（崩溃，不静默吞掉）
```

**关键不变量**：
- `findReusable/findLinkedIssueEnv/tryBranchAdoption` 任一路径发现 cross-clone mismatch → **throw**（不 continue），因为 clone 状态异常，用户需要介入
- `markDestroyedBestEffort` 只处理 stale 清理，永远不 throw（非关键路径）
- `provider.create()` 成功但 `store.create()` 失败 → **必须**清理 orphan worktree，然后重新抛 store 错误

### 模块：DAG Executor

```
调度层: executeWorkflow() → resume check → path lock → executeDagWorkflow()
  ↓
实践层: buildTopologicalLayers() → 按层 Promise.allSettled 并发执行
  ↓
消费层: executeNodeInternal() — 加载 prompt → substituteWorkflowVariables → sendQuery
  ↓
状态层: nodeOutputs: Map<string, NodeOutput> — 内存 + DB events 双写（断点续跑用 DB）
  ↓
边界层: withIdleTimeout() 包装 sendQuery 的 generator
        classifyError() 分流 FATAL/TRANSIENT/UNKNOWN
        UNKNOWN_ERROR_THRESHOLD=3 连续未知错误中止
```

---

## P0/P1/P2 Pattern 矩阵

### P0 — 必须偷（3 个新增）

| Pattern | 机制 | 我们现状 | 对比矩阵 | 不可替代性 |
|---------|------|---------|---------|----------|
| **Working Path Lock** | DB 行作 lock token，`pending/running/paused`=持锁，older-wins tiebreaker，5min stale window | 无并发控制 | 我们的 agent 任务没有路径级互斥，多 agent 同时写同目录会互相破坏 | 任何需要并发 agent 执行的系统都需要这个原语 |
| **Idle Timeout as Deadlock Detector** | `withIdleTimeout` 包装 AsyncGenerator，Symbol sentinel + Promise.race，超时触发 abort 而非抛异常 | 无超时保护，agent 挂死无法恢复 | `generator.return()` 会阻塞这是关键细节，不是显而易见的 | 子进程挂死场景通用，任何 AsyncGenerator 消费都适用 |
| **Provider Registry with Capability Flags** | `Map<id, ProviderRegistration>`，每个 provider 声明 12 项 capability，dispatch 前预检并发 warning | 硬编码单 provider，无能力声明 | 未来支持多 provider 的必要基础设施 | 不偷就得重新设计 |

#### P0 深度：Working Path Lock

**三重验证**：
1. **代码验证**：`executor.ts:478-560` 完整 path lock 逻辑，含状态感知消息
2. **测试验证**：`executor.test.ts` 360 行新增，覆盖 SQLite datetime() bug + older-wins 等 edge case
3. **commit 验证**：`33d31c4` PR message 明确说明修复了 `#1036, #1188` 两个 issues，851 行净增

**适配 Orchestrator 的方案**：

Orchestrator 没有 worktree，但有 agent 任务。可以用同样的 DB 行锁原语：
```python
# task_runs 表加 working_path 字段（或 task_id）
# dispatch 前 query: SELECT * WHERE working_path = ? AND status IN ('running', 'paused')
# 找到 → 返回 "任务已在运行" 而不是并发执行
# Telegram /status 命令可以用同一查询
```

#### P0 深度：Idle Timeout

**核心片段**（可直接移植）：
```typescript
// packages/workflows/src/utils/idle-timeout.ts
export async function* withIdleTimeout<T>(
  generator: AsyncGenerator<T>,
  timeoutMs: number,
  onTimeout?: () => void
): AsyncGenerator<T> {
  let timerStartedAt = Date.now();
  while (true) {
    const remaining = Math.max(0, timeoutMs - (Date.now() - timerStartedAt));
    const timeoutPromise = new Promise<typeof IDLE_TIMEOUT_SENTINEL>(resolve =>
      setTimeout(() => resolve(IDLE_TIMEOUT_SENTINEL), remaining)
    );
    const nextPromise = generator.next();
    const result = await Promise.race([nextPromise, timeoutPromise]);
    if (result === IDLE_TIMEOUT_SENTINEL) {
      nextPromise.catch(() => {});  // 防 unhandled rejection
      onTimeout?.();
      return;
    }
    timerStartedAt = Date.now();  // 每次 yield 重置
    yield result.value;
  }
}
```

Python 版等价实现：用 `asyncio.wait_for` 包装 `__anext__` 调用，`asyncio.TimeoutError` 时调用 cleanup callback。

#### P0 深度：Provider Registry

**注册模式**（可直接借鉴）：
```typescript
interface ProviderRegistration {
  id: string;
  displayName: string;
  factory: () => IAgentProvider;
  capabilities: ProviderCapabilities;
  isModelCompatible: (model: string) => boolean;
  builtIn: boolean;
}

// 启动时注册内置 provider
registerBuiltinProviders();  // idempotent

// 社区 provider（Phase 2 设计目标）：
registerProvider({
  id: 'my-provider',
  factory: () => new MyProvider(),
  capabilities: { mcp: false, hooks: false, ... },
  ...
});
```

**Orchestrator 的对应概念**：我们的 skill/agent 调度也可以用注册表——每个 skill 声明 `capabilities`（需要 internet? 需要 docker? 支持 streaming?），dispatch 前预检。

---

### P1 — 值得做（4 个新增）

| Pattern | 机制 | 适配建议 | 工作量 |
|---------|------|---------|--------|
| **3-tier Error Classification with FATAL priority** | FATAL patterns 优先于 TRANSIENT patterns，防止含两种 pattern 的错误被误重试 | 我们的 hooks 错误处理是 catch-all，加入这套分类 | ~1h |
| **Consecutive UNKNOWN Error Threshold** | 3 次连续未知错误中止，防止陷入死循环 | agent loop 里加计数器 | ~30min |
| **parseDbTimestamp with TZ awareness** | SQLite 返回无时区字符串，自动检测格式加 Z 后缀 | 我们用 Python，SQLite datetime 处理同样有这个 pitfall | ~30min |
| **formatDuration** | `500ms→"1s"`, `65000ms→"1m 5s"`, `3700000ms→"1h 1m"` | 工作流状态消息/Telegram 通知中的时长格式化 | ~30min |

**formatDuration 代码**（直接可用）：
```typescript
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '0s';
  const totalSeconds = Math.max(1, Math.floor(ms / 1000)); // 0ms→"1s"（展示运行中）
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes > 0) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
  return `${seconds}s`;
}
```

---

### P2 — 仅参考（3 个）

| Pattern | 原因 |
|---------|------|
| **DAG 工作流 YAML 引擎** | R47 已评估，我们用 skill 编排替代，不需要完整引擎 |
| **Session Resume（AI context 连续性）** | 依赖 Claude Agent SDK 的 session persistence，我们用不同的上下文管理策略 |
| **Community Provider Phase 2** | 等他们实现完，我们再看具体 API 设计 |

---

## 路径依赖分析

### Archon 的路径依赖

1. **Bun runtime 强绑定**：`Bun.YAML.parse`、`bun:sqlite`、`bun test`——迁移 Node.js 需要大量替换
2. **Claude Agent SDK 深度集成**：`@anthropic-ai/claude-agent-sdk` 的 `query()` + `HookCallback` 类型贯穿整个 provider 层
3. **git worktree 作为隔离单元**：整套 isolation 系统依赖 git worktree 命令，非 git 项目无法使用

### 对 Orchestrator 的影响

- **可以直接拿的**：Working Path Lock 逻辑（纯 DB 操作）、Idle Timeout（纯 async 工具）、Error Classification（纯字符串匹配）、formatDuration（纯数学）
- **需要适配的**：Provider Registry 的思路移植到 Python，capability flags 类型用 dataclass 实现
- **不需要的**：整套 worktree isolation（我们用 Docker 隔离）

---

## 实施优先级

### 立即执行（本 session 内）

1. **Working Path Lock** — 在 Orchestrator 的任务派单系统加路径锁：
   - 在 `task_runs` 或 `channel_sessions` 表加 `working_path` 列
   - dispatch 前 query 检查活跃任务
   - 找到冲突 → 返回状态感知错误消息
   - **预估**：~2h

2. **Idle Timeout Python 移植** — 包装 agent streaming generator：
   - `asyncio.wait_for` 实现等价逻辑
   - `shouldResetTimer` predicate 控制是否重置
   - **预估**：~1.5h

### 本轮偷师收益总结

| 项目 | R47 状态 | R63 新增 |
|------|---------|---------|
| Worktree 安全 | 知道有守卫，不知道具体机制 | 完整四层链条 + 错误码保留细节 |
| 工作流并发 | 不知道有锁 | SQLite datetime bug + older-wins tiebreaker |
| Provider 架构 | 知道 IAssistantClient 接口 | 完整注册表 + capability flags 设计 |
| .env 安全 | 知道有扫描器 | 扫描器被删，结构性防护才是正确答案 |
| Idle Timeout | 完全不知道 | Symbol sentinel + abort 模式 |

---

*报告基于 2026-04-14 克隆快照，commit `33d31c4`（HEAD）*
