# Claude Code Agent Dispatch & Scheduling 深度偷师

> Round 34 | 2026-04-01 | 来源：官方文档 + npm 源码泄露 + 社区逆向分析

## 概述

Claude Code 的多 Agent 调度系统是一个**三层架构**：Subagent（进程内委托）→ Agent Teams（跨会话协作）→ KAIROS（后台守护进程）。每一层解决不同粒度的并发问题，而调度的核心哲学是**编排即 prompt，不是代码**。

---

## 1. Spawn 决策矩阵：何时生成 Subagent

### 1.1 决策逻辑

Claude Code 不使用硬编码规则来决定是否 spawn subagent，而是**让 LLM 自己根据 description 字段判断**。每个 subagent 的 `description` 就是它的"招聘广告"——Claude 读到任务描述后，匹配最佳 subagent 并自动委托。

决策的关键信号：

| 信号 | 走 Subagent | 留在主线程 |
|------|------------|-----------|
| 任务产生大量输出（测试/日志/搜索） | ✅ 隔离输出，只返回摘要 | |
| 需要特定工具限制（只读） | ✅ 限制工具集 | |
| 需要不同模型（Haiku 做搜索） | ✅ 降本 | |
| 需要频繁来回对话 | | ✅ 上下文共享 |
| 快速、有针对性的修改 | | ✅ 延迟更低 |
| 多步骤共享大量上下文 | | ✅ 避免重复探索 |

### 1.2 内置 Subagent 分层

| Agent | 模型 | 工具 | 用途 |
|-------|------|------|------|
| **Explore** | Haiku（成本降低 ~80%） | 只读 | 文件发现、代码搜索 |
| **Plan** | 继承主会话 | 只读 | 规划阶段的上下文收集 |
| **General-purpose** | 继承主会话 | 全部 | 复杂多步骤任务 |
| **Bash** | 继承 | 终端命令 | 隔离上下文的命令执行 |

关键洞察：**Explore 用 Haiku 而不是 Sonnet**。文件搜索是机械操作，不需要前沿推理能力。这是一个"能力降级换成本"的模式。

### 1.3 Coordinator Mode（协调者模式）

源码泄露揭示了 `coordinatorMode.ts`：

> **编排算法是 prompt，不是代码。**

协调者通过系统提示词管理工作者 agent：
- "Do not rubber-stamp weak work"（不要对差劲的工作盖章通过）
- "You must understand findings before directing follow-up work"（必须理解发现再指导后续工作）

协调者**永远不写代码，只委托和综合**。接收 agent 输出，通过综合 pass 折叠为连贯结果。

**🔑 可偷模式：Prompt-as-Orchestrator**
- Orchestrator 当前的三省六部调度是代码驱动的
- 可以引入"六部尚书"prompt，让 LLM 自己决定任务路由
- prompt 比代码更灵活，可以处理模糊任务边界

---

## 2. Agent 生命周期管理

### 2.1 创建过程

```
父会话 → Agent Tool 调用 → 新上下文窗口（独立进程/线程）
                              ├── 系统提示词（来自 YAML frontmatter 的 body）
                              ├── 环境信息（工作目录等）
                              ├── 权限继承（来自父会话）
                              └── 工具集（按配置限制）
```

关键事实：
- Subagent 的上下文窗口**完全干净**——不继承父会话对话历史
- 从父到子的**唯一通道**是 Agent Tool 的 prompt 字符串
- Subagent **不能生成子 subagent**（防止无限嵌套）

### 2.2 上下文传递

父 Agent 向子 Agent 传递信息的唯一方式是**在 prompt 中塞入所有需要的信息**：
- 文件路径
- 错误信息
- 决策上下文
- 约束条件

Subagent 自身收到的系统提示包含：
- YAML 定义的自定义系统提示词
- 基础环境信息（工作目录等）
- 如果开启了 `memory`，还包含 MEMORY.md 的前 200 行或 25KB

**不会收到**：Claude Code 的完整系统提示词、父会话的对话历史。

### 2.3 结果上报

子 Agent 的所有中间 tool call 和结果**留在子上下文内**，只有最终消息返回父会话。这是关键的上下文节省机制——一个 10 轮的搜索任务，父会话只看到 1 条摘要。

### 2.4 终止与清理

- `maxTurns`：限制最大 agentic turn 数
- 自动压缩：~95% 容量时触发（可通过 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 调低）
- Worktree 隔离的 subagent：无变更时自动清理 worktree；有变更时保留供审查
- Transcript 持久化：`~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`
- 默认 30 天自动清理（`cleanupPeriodDays`）

### 2.5 记忆存续

Subagent 的 `memory` 字段支持三个 scope：

| Scope | 路径 | 用途 |
|-------|------|------|
| `user` | `~/.claude/agent-memory/<name>/` | 跨项目学习 |
| `project` | `.claude/agent-memory/<name>/` | 项目特定，可 git 追踪 |
| `local` | `.claude/agent-memory-local/<name>/` | 项目特定，不入 git |

**🔑 可偷模式：Agent Persistent Memory**
- 每个 Agent 有自己的记忆目录，跨会话积累知识
- Orchestrator 可以给每个六部（吏/户/礼/兵/刑/工）独立的记忆目录
- Agent 可以自己维护和整理记忆（`MEMORY.md` 超限时自动整理）

---

## 3. 隔离机制

### 3.1 Git Worktree 隔离

```yaml
---
name: isolated-worker
isolation: worktree
---
```

效果：
- 每个 subagent 获得**独立的仓库工作目录副本**
- 共享相同的 git 历史和远程连接
- Agent A 改 `src/auth.ts` 的同时，Agent B 可以改同一文件的不同版本
- 无变更时 worktree 自动回收

### 3.2 文件系统隔离

- 没有沙箱级别的文件系统隔离
- `--add-dir` 授予文件访问但**不授予配置发现**（不扫描该目录下的 agents/skills/CLAUDE.md）
- 写入 `.git`、`.claude`、`.vscode`、`.idea` 目录仍会触发确认（即使 `bypassPermissions` 模式）

### 3.3 上下文隔离

每个 subagent 的上下文窗口完全独立：
- 不继承父会话对话历史
- 只接收自己的系统提示 + Agent Tool prompt
- 中间结果不回传父上下文

### 3.4 权限隔离

- Subagent **继承**父会话的权限上下文
- 可以通过 `permissionMode` 覆盖：`default` / `acceptEdits` / `dontAsk` / `bypassPermissions` / `plan`
- **但**：如果父会话使用 `bypassPermissions`，子会话必须服从，不能覆盖
- 如果父会话使用 auto mode，子会话继承 auto mode 的 block/allow 规则
- Plugin 来源的 subagent **不支持** `hooks`、`mcpServers`、`permissionMode`（安全限制）

**🔑 可偷模式：Permission Cascade with Override**
- 权限向下继承但可覆盖（除了最高权限）
- Orchestrator 可以实现类似的"六部权限降级"——兵部有写权限，礼部只有读权限

---

## 4. 调度与并发

### 4.1 最大并发数

**没有硬性限制**。实际受限于：
- Token 消耗线性增长（每个 teammate 独立上下文窗口）
- 协调开销随 agent 数增加
- 收益递减：超过一定数量后额外 agent 不能等比加速

推荐起步：**3-5 个 teammates**，每个 teammate 5-6 个 task。

### 4.2 任务调度模式

没有传统意义上的优先级队列。调度是**分布式自治**的：

```
1. Team Lead 创建 task list
2. Teammates 轮询 TaskList()
3. 找到 status: "pending" 且无 owner 的 task
4. TaskUpdate() 抢占（原子写入，先到先得）
5. 执行 → 完成 → 再轮询
```

Task 的 `blockedBy` 字段实现依赖链——被阻塞的 task 在前置完成前不能被认领。

### 4.3 资源竞争处理

**同文件编辑防护**：
- 方案一：Worktree 隔离——每个 agent 在自己的目录工作，完全避免冲突
- 方案二：Task 粒度设计——Team Lead 拆任务时确保每个 teammate 负责不同文件集合
- **没有文件级锁**——如果两个 agent 在同一个 worktree 编辑同一文件，是 last-write-wins

Task 认领使用**文件锁**防止两个 teammate 同时 claim 同一个 task。但文件内容的并发编辑没有保护。

**🔑 可偷模式：File Ownership Declaration**
- Task 创建时声明"本任务涉及哪些文件"
- 调度器检查文件归属冲突，阻止重叠
- Orchestrator 的六部可以按模块划分"领地"

---

## 5. 通信协议

### 5.1 文件系统 IPC

所有 agent 通信基于**本地文件系统**，不是消息队列或 WebSocket：

```
~/.claude/teams/{team-name}/
├── config.json                    # 成员列表（agentId, name, agentType, color, tmuxPaneId）
└── inboxes/
    ├── team-lead.json             # 领导邮箱
    ├── worker-1.json              # 工人邮箱
    └── worker-2.json

~/.claude/tasks/{team-name}/
├── {task-id-1}.json
├── {task-id-2}.json
└── ...
```

### 5.2 消息格式

```json
{
  "from": "team-lead",
  "text": "message content",
  "timestamp": "2026-01-25T23:38:32.588Z",
  "read": false
}
```

结构化消息通过 `text` 字段内嵌 JSON，类型包括：
- `shutdown_request` / `shutdown_approved`
- `idle_notification`
- `task_completed`
- `plan_approval_request`
- `join_request`
- `permission_request`

### 5.3 SendMessage 工具

- 只在 Agent Teams 启用时可用（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`）
- `write`：点对点消息
- `broadcast`：群发（开销 = N × 单条消息，N = teammate 数）
- 消息自动作为新对话 turn 送达——不需要轮询

### 5.4 TeammateTool 13 操作

| 分类 | 操作 | 说明 |
|------|------|------|
| 生命周期 | `spawnTeam` | 创建团队目录和配置 |
| | `discoverTeams` | 发现已有团队 |
| | `cleanup` | 清理团队资源（成员都退出后） |
| 成员管理 | `requestJoin` | 请求加入 |
| | `approveJoin` | 批准加入 |
| | `rejectJoin` | 拒绝加入 |
| 通信 | `write` | 点对点消息 |
| | `broadcast` | 群发 |
| 质量门 | `approvePlan` | 批准计划 |
| | `rejectPlan` | 否决计划（附反馈） |
| 关停 | `requestShutdown` | 请求关停 |
| | `approveShutdown` | 批准关停 |
| | `rejectShutdown` | 拒绝关停 |

**🔑 可偷模式：File-Based Agent IPC**
- 不需要 Redis/MQ，文件系统就够了
- Orchestrator 可以在 `.claude/departments/` 下实现六部邮箱
- 消息格式统一为 JSON，类型字段驱动路由

---

## 6. 后台 Agent（KAIROS 守护进程）

### 6.1 Tick 系统

KAIROS 把标准聊天循环变成**长生命周期的自治系统**，核心是 tick 引擎：

```javascript
const tickContent = `<${TICK_TAG}>${new Date().toLocaleTimeString()}</${TICK_TAG}>`;
// setTimeout(0) 注入 <tick> 消息到消息队列
```

- `setTimeout(0)` 确保 tick 让出事件循环，用户输入优先
- 每个 tick，模型评估：有未完成工作？→ 执行。没有？→ 睡眠
- 系统提示：*"你会收到 `<tick>` 提示保持清醒——它们的意思是'你醒着呢，接下来干什么？'"*

### 6.2 Sleep 与成本管理

`SleepTool` 让 agent 自己决定休眠时长：

> "每次醒来花费一次 API 调用，但 prompt 缓存 5 分钟不活动就过期——请权衡。"

这是一个**经济学驱动的调度决策**：agent 必须在响应速度和缓存命中率之间找平衡。

### 6.3 15 秒阻塞预算

```javascript
const ASSISTANT_BLOCKING_BUDGET_MS = 15_000;
// 超时后：如果 shellCommand.status === 'running' → startBackgrounding()
```

- Shell 命令超过 15 秒自动移至后台
- `.unref()` 防止计时器阻止 Node 进程退出
- 命令继续运行，完成后 agent 收到通知

### 6.4 Append-Only 日志 + autoDream

放弃重写 MEMORY.md，改为**追加式每日日志**：

```
logs/YYYY/MM/YYYY-MM-DD.md
```

夜间 `/dream` 处理：
- 蒸馏日志为结构化主题文件
- 更新 MEMORY.md 作为索引
- 合并离散观察、删除逻辑矛盾、将模糊洞察转化为确定事实

### 6.5 输出通道：SendUserMessage

后台 agent 不能假设 stdout 到达用户，因此强制使用 `SendUserMessage`（BriefTool）：

- `status: 'normal'`：用户主动请求的回复
- `status: 'proactive'`：主动推送
- 三层过滤：Brief-only / Default / Transcript（ctrl+o）

### 6.6 tmux/iTerm2 会话管理

Agent Teams 支持三种后端：

| 后端 | 进程模型 | 可见性 | 持久性 |
|------|---------|--------|--------|
| `in-process` | 同 Node.js，异步 task | 隐藏 | 随领导退出 |
| `tmux` | 独立 pane/session | 可见 | 存活于领导退出 |
| `iterm2` | 分屏 pane（macOS） | 并排可见 | 随窗口关闭 |

自动检测：`$TMUX` → `$TERM_PROGRAM` → `which tmux` → `which it2`

**🔑 可偷模式：Tick-Driven Daemon + Sleep Economics**
- Orchestrator 的 wake-watcher 可以引入 tick 机制
- agent 自己决定睡多久，基于 API 成本和缓存过期的经济计算
- append-only 日志 + 夜间蒸馏 = 不需要实时整理记忆

---

## 7. Agent Teams 协作

### 7.1 五种协作模式

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **Leader** | 层级制任务指派 | 复杂项目分工 |
| **Swarm** | 自组织并行执行 | 独立 task 批量处理 |
| **Pipeline** | 依赖链顺序执行 | 多阶段工作流 |
| **Council** | 多视角决策 | 架构评审、方案论证 |
| **Watchdog** | 质量监控 | 代码审查、安全审计 |

### 7.2 Task 依赖波

```javascript
TaskCreate({ subject: "Step 1: 设计 API" })
TaskCreate({ subject: "Step 2: 实现 API" })
TaskUpdate({ taskId: "2", addBlockedBy: ["1"] })
```

- 独立 task 全并行
- 有依赖的 task 等前置完成后自动解锁
- 形成"执行波"——每波内并行，波间串行

### 7.3 计划审批流

```
Teammate（plan mode）→ 完成计划 → plan_approval_request → Team Lead
    ← approve → 退出 plan mode，开始实现
    ← reject（附反馈）→ 留在 plan mode，修改后重提
```

Lead 自主做审批决策。用户可通过 prompt 影响审批标准：
- "只批准包含测试覆盖的计划"
- "拒绝修改数据库 schema 的计划"

### 7.4 合并冲突处理

**核心策略：避免冲突而不是解决冲突。**

1. Worktree 隔离：每个 agent 在独立 worktree，各自独立分支
2. 任务粒度：Lead 拆任务时确保文件集不重叠
3. 顺序合并：工作完成后，Lead 顺序合并各分支
4. 人工审查：有冲突的 worktree 保留供人工处理

**没有自动冲突解决**——这是有意为之。合并冲突意味着任务拆分有问题。

**🔑 可偷模式：Conflict Prevention > Conflict Resolution**
- 在调度层面避免冲突，而不是在合并层面解决冲突
- Task 创建时声明文件归属
- 调度器拒绝文件集重叠的并行任务

---

## 8. 错误恢复

### 8.1 Subagent 崩溃

当前**没有自动重试机制**。恢复策略：

- Background subagent 权限不足失败 → 启动新的 foreground subagent 重试（交互式权限批准）
- 增量提交 + 独立对话历史 → 崩溃后可通过引用之前工作恢复
- Transcript 持久化 → 即使主会话压缩，subagent 转录不受影响

### 8.2 超时处理

- `maxTurns` 限制最大回合数
- 15 秒阻塞预算（KAIROS 的 `ASSISTANT_BLOCKING_BUDGET_MS`）
- 压缩超时可导致会话破坏性失败（已知 bug：404/400 错误）
- SDK 侧：Grep 返回 10 万+ 匹配时直接 AbortError 崩溃

### 8.3 部分结果收集

- AbortError 推荐处理：捕获错误，返回带截断元数据的部分结果
- Subagent 完成时只返回最终消息，中间结果留在子上下文
- 如果 subagent 异常退出，父会话收到错误而非结果

### 8.4 Agent Teams 的故障处理

- Teammate 停止后自动通知 Lead
- Lead 可以观察到 task 卡住（通过 TaskList），手动重分配
- 替代 teammate 可以被 spawn 来接管工作
- 5 分钟心跳超时后自动终止

**🔑 可偷模式：Heartbeat + Auto-Reassign**
- Teammate 5 分钟无心跳 → 自动终止
- Lead 检测卡住的 task → spawn 替代者
- Orchestrator 可以给每个六部 agent 加心跳机制

---

## 9. 高价值可偷清单（P0）

| # | 模式 | 来源 | 说明 | Orchestrator 适用点 |
|---|------|------|------|-------------------|
| 1 | **Prompt-as-Orchestrator** | coordinatorMode.ts | 编排逻辑是 prompt 不是代码 | 三省六部调度改为 LLM prompt 驱动 |
| 2 | **Model Tier Routing** | Explore=Haiku | 机械任务用便宜模型 | 搜索/索引用 Haiku，推理用 Opus |
| 3 | **File-Based Agent IPC** | teams/inboxes/*.json | 文件系统做 agent 通信 | `.claude/departments/` 邮箱 |
| 4 | **Tick-Driven Daemon** | KAIROS tick engine | setTimeout(0) + <tick> | wake-watcher 引入 tick 机制 |
| 5 | **Sleep Economics** | SleepTool | Agent 自决休眠时长（成本 vs 缓存） | 采集器根据 API 成本自动调频 |
| 6 | **15s Blocking Budget** | ASSISTANT_BLOCKING_BUDGET_MS | 长命令自动后台化 | Shell 命令超时自动转后台 |
| 7 | **Append-Only + Dream** | KAIROS autoDream | 追加日志 + 夜间蒸馏 | 六部日报追加写 + 夜间整理 |
| 8 | **Task Dependency Wave** | TaskCreate + blockedBy | 依赖链自动解锁 | 六部任务依赖图 |
| 9 | **Conflict Prevention** | Worktree + 文件归属 | 调度层面避免冲突 | Task 声明文件集，调度器检查重叠 |
| 10 | **Agent Persistent Memory** | memory: user/project/local | 跨会话记忆积累 | 每部独立记忆目录 |
| 11 | **Plan Approval Gate** | approvePlan/rejectPlan | 实现前必须过审 | 中书省审议嵌入实现流程 |
| 12 | **Graceful Shutdown Protocol** | requestShutdown 握手 | 不是 kill 而是协商退出 | Agent 完成当前任务后再退出 |
| 13 | **Permission Cascade** | 权限继承 + 覆盖 | 父→子权限降级 | 六部按职能分配权限 |
| 14 | **Proactive Message Tagging** | status: normal/proactive | 区分主动和被动消息 | 通知分级：请求回复 vs 主动推送 |

---

## 10. 与已有偷师的交叉引用

| 本次发现 | 已有偷师报告 | 关系 |
|---------|-------------|------|
| Prompt-as-Orchestrator | Round 28 coordinatorMode | 本次更深入：13 操作 + 决策矩阵 |
| KAIROS tick 系统 | Round 28 KAIROS 初探 | 本次补充：Sleep Economics + 15s Budget |
| File-Based IPC | Round 29 Agent Teams | 本次补充：邮箱目录结构 + 消息格式 |
| Memory Persistence | Round 30 yoyo-evolve | 类似模式但 Claude Code 的 scope 分层更清晰 |
| Task Dependency | Round 22 Review Swarm | 相似但 Claude Code 用文件锁而非进程锁 |

---

## Sources

- [Create custom subagents - Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
- [Orchestrate teams of Claude Code sessions - Claude Code Docs](https://code.claude.com/docs/en/agent-teams)
- [Architecture of KAIROS, the Unreleased Always-on Background Agent](https://codepointer.substack.com/p/claude-code-architecture-of-kairos)
- [The Claude Code Source Leak](https://alex000kim.com/posts/2026-03-31-claude-code-source-leak/)
- [Claude Code's Hidden Multi-Agent System](https://paddo.dev/blog/claude-code-hidden-swarm/)
- [From Tasks to Swarms: Agent Teams in Claude Code](https://alexop.dev/posts/from-tasks-to-swarms-agent-teams-in-claude-code/)
- [TeammateTool System Prompt](https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/tool-description-teammatetool.md)
- [Claude Code Swarm Orchestration Skill](https://gist.github.com/kieranklaassen/4f2aba89594a4aea4ad64d753984b2ea)
- [Parallel AI Coding with Git Worktrees](https://docs.agentinterviews.com/blog/parallel-ai-coding-with-gitworktrees/)
- [I Read the Leaked Claude Code Source. Then I Built the Roadmap Myself.](https://dreadheadio.github.io/claude-code-roadmap/claude-code-roadmap-blog.html)
