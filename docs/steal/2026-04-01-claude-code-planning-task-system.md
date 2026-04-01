# Claude Code 规划与任务分配系统深度偷师

> Round 34 | 2026-04-01 | 来源：Claude Code 官方文档 + npm 泄露源码 + 社区逆向分析

## 概要

Claude Code 的规划系统不是一个单一功能，而是一套四层架构：**Plan Mode（只读规划）→ Task System（任务追踪）→ Agent Teams（多 Agent 协作）→ ULTRAPLAN（远程规划）**。每一层解决不同粒度的问题，可以独立使用也可以组合。

这篇报告聚焦于"规划如何产生"和"规划如何执行"的全链路，从 prompt 级别的实现到多 Agent 的任务分发。

---

## 1. Plan Mode 架构

### 1.1 本质：一个状态机

Plan Mode 不是什么魔法——**核心就是一段 system prompt + 一个权限状态机**。

状态转换：

```
Default Mode ──EnterPlanMode──→ Plan Mode ──ExitPlanModeV2──→ Default Mode
                                    │                              ▲
                                    │     (user rejects plan)      │
                                    └──────────────────────────────┘
```

- **EnterPlanMode**：将 session 的 permission mode 设为 `plan`，限制所有破坏性工具
- **ExitPlanModeV2**：提交计划供用户审批，附带语义化权限请求（如 "allow running tests"）

### 1.2 Plan Mode 的 System Prompt

从逆向的 `agent-prompt-plan-mode-enhanced.md` 可以看到完整指令：

> You function as "a software architect and planning specialist for Claude Code"

关键约束：
- **严格只读**：禁止 Write/Edit/rm/mv/cp/touch，禁止重定向操作符（`>`, `>>`），禁止 heredoc 写文件
- **Bash 白名单**：只允许 `ls`, `git status`, `git log`, `git diff`, `find`, `grep`, `cat`, `head`, `tail`
- **强制四步流程**：Understand Requirements → Explore Thoroughly → Design Solution → Detail the Plan
- **输出要求**：必须以 "Critical Files for Implementation" 结尾，列出 3-5 个关键文件

### 1.3 权限注入机制

ExitPlanModeV2 的关键创新是 **语义化权限请求**：

```typescript
allowedPrompts: z.array(allowedPromptSchema)
```

计划审批时，模型不是请求"我需要 Bash 权限"，而是请求"allow running tests"这样的语义描述。用户看到的是人话，不是系统权限枚举。一旦审批通过：

1. 验证当前 mode 确实是 `plan`
2. 注入语义权限
3. 状态切换回 `default`
4. 之前受限的工具解锁

**Fail-closed 设计**：权限只在用户明确审批后才授予，没有默认信任。

### 1.4 Plan 文档格式

Claude Code 的计划存储为 `CLAUDE_PLAN.md` 文件，**没有强制的结构化格式**——就是一个 Markdown 文件。这跟 Orchestrator 的 `plan_template.md` 有本质区别：我们有严格的模板（File Map + 编号步骤 + verify 命令 + 依赖声明），Claude Code 更自由。

用户可以在编辑器里直接修改计划（`Ctrl+G` 打开默认编辑器），Claude 会读取修改后的版本。

### 1.5 与 Orchestrator 的差距

| 维度 | Claude Code | Orchestrator |
|------|------------|-------------|
| 格式 | 自由 Markdown | 严格模板（File Map + verify 命令） |
| 审批 | 语义化权限请求 | 无（直接执行） |
| 编辑 | 用户可在编辑器中直接修改 | 无（只能重新规划） |
| 状态机 | 明确的 Enter/Exit 工具 | 无（靠 prompt 纪律） |
| 只读强制 | 工具级别硬限制 | 靠 prompt 约束（软限制） |

**可偷模式 P0**：
1. **权限状态机**——用 Enter/Exit 工具硬切换规划/执行模式，而不是靠 prompt 纪律
2. **语义化权限请求**——计划审批时附带人类可读的权限描述
3. **用户可编辑计划**——计划不是单向产出，用户可以直接在编辑器中修改

---

## 2. 任务分解策略

### 2.1 分解粒度

Claude Code 没有像 Orchestrator 那样规定"每步 2-5 分钟"，但有等效的实践指导：

- **3+ 步骤才创建任务列表**：少于 3 步不值得追踪
- **每个任务是自包含的可交付单元**：一个函数、一个测试文件、一个审查报告
- **Agent Teams 推荐 5-6 个 task/teammate**：避免上下文切换过多

### 2.2 分解模式

从源码泄露的 `coordinatorMode.ts` 可以看到 Coordinator 的系统 prompt 有严格纪律：

> "Never reference findings abstractly; synthesize into **specific specs with file paths and line numbers**"

这跟 Orchestrator 的 "No Placeholder Iron Rule" 异曲同工——但 Claude Code 是在多 Agent 协调层面强制的，不只是计划模板层面。

### 2.3 依赖表达

Tasks API 使用 **双向依赖字段**：

- `blockedBy`（我被谁阻塞）→ "I cannot start until these tasks complete"
- `blocks`（我阻塞谁）→ "These tasks cannot start until I complete"

这不是 DAG 结构，但效果等价。当一个 task 完成时，依赖它的 tasks **自动解锁**，无需手动干预。

**可偷模式 P0**：
4. **双向依赖字段**——`blockedBy` + `blocks` 比单纯的 "depends on: step N" 更强大，支持自动解锁

---

## 3. 任务追踪系统（TodoWrite → Tasks API）

### 3.1 演进历程

Claude Code 的任务追踪经历了一次重大重构：

| 维度 | TodoWrite（旧） | Tasks API（新，v2.1.19+） |
|------|----------------|-------------------------|
| 存储 | 上下文窗口（200K token 限制） | 文件系统 `~/.claude/tasks/` |
| 持久化 | 会话结束即消失 | 跨会话、跨重启 |
| 依赖追踪 | 无 | `blockedBy` / `blocks` |
| 跨会话协调 | 不支持 | 通过 `CLAUDE_CODE_TASK_LIST_ID` |
| 广播 | 不支持 | 跨 session 广播更新 |

### 3.2 TodoWrite 的数据模型

每个 todo 包含：

| 字段 | 说明 |
|------|------|
| `content` | 祈使句形式（"Run tests"） |
| `activeForm` | 进行时形式（"Running tests"）——显示在 spinner 中 |
| `status` | `pending` / `in_progress` / `completed` |

关键约束：
- **同一时刻最多一个 `in_progress`**——这是强制的，不是建议
- **不完整不能标记完成**——测试失败、实现部分完成、错误未解决都不能标 done

### 3.3 Tasks API 的数据模型

```typescript
// TaskCreate
{
  subject: string       // 必填，简短动作标题
  description: string   // 必填，50-100 词推荐
  activeForm?: string   // 可选，进行时形式
  // status 默认 pending
}

// TaskUpdate
{
  id: string            // 不可变
  status?: 'pending' | 'in_progress' | 'completed'
  addBlockedBy?: string[]  // 添加阻塞依赖
  addBlocks?: string[]     // 添加被阻塞关系
  metadata?: {
    priority?: 'critical' | 'high' | 'medium' | 'low'
    estimated_duration?: string  // "30m" / "2h" / "1d"
    files?: string[]
    started_at?: string  // ISO 8601
    completed_at?: string
  }
}
```

### 3.4 存储与原子性

- **位置**：`~/.claude/tasks/<TASK_LIST_ID>/`
- **写入方式**：rename-based atomic write（先写临时文件，再原子重命名）
- **保证**：存活于 session 终止、context compaction、系统重启、多天中断

### 3.5 跨会话恢复

```
1. 设置 CLAUDE_CODE_TASK_LIST_ID
2. TaskList → 查看所有 pending/blocked 状态
3. TaskGet → 获取特定 task 的完整要求
4. TaskUpdate → 更新进度
```

**可偷模式 P0**：
5. **Task 持久化到文件系统**——不依赖上下文窗口，跨 session 存活
6. **双表单模式**——`content`（祈使句）+ `activeForm`（进行时），UI 状态感知
7. **原子写入**——rename-based atomic write 防止并发损坏

---

## 4. ULTRAPLAN（远程规划）

### 4.1 核心机制

ULTRAPLAN 把复杂规划任务卸载到远程 CCR（Claude Code Remote）实例：

```
本地 CLI ──触发──→ 远程 CCR (Opus 4.6, 30 分钟超时)
   │                        │
   │    轮询（3秒/次）        │ 规划中...
   │ ←──────────────────────│
   │                        │ 产出计划
   │ ←── ExitPlanMode ──── │
   │                        │
   ├── 审批 → 远程执行 → PR  │
   └── 传送回本地 → 继续执行  │
```

### 4.2 触发机制

关键词检测，不是 slash command：

- 输入中包含 "ultraplan" → 自动触发
- **智能过滤**：反引号/引号/括号内、路径中（`src/ultraplan/foo.ts`）、标识符（`--ultraplan-mode`）、疑问句（`ultraplan?`）都会跳过
- 语法转换：`"please ultraplan this"` → `"please plan this"`

### 4.3 ExitPlanModeScanner

状态分类器，6 种结果类型：

```typescript
type ScanResult =
  | { kind: 'approved'; plan: string }
  | { kind: 'teleport'; plan: string }
  | { kind: 'rejected'; id: string }
  | { kind: 'pending' }
  | { kind: 'terminated'; subtype: string }
  | { kind: 'unchanged' }
```

Phase 追踪：`running` → `needs_input` → `plan_ready` → (approved | rejected 循环)

### 4.4 轮询策略

- **频率**：每 3 秒，最长 30 分钟（~600 次 API 调用）
- **容错**：5 次连续网络失败才中止
- **传送哨兵**：`__ULTRAPLAN_TELEPORT_LOCAL__` 标记"传送回本地"

### 4.5 审批后的两条路径

| 选项 | 行为 |
|------|------|
| Remote 执行 | 在 CCR 上继续，产出 Pull Request |
| Teleport to Terminal | 归档远程 session，计划回到本地执行 |

**可偷模式 P1**：
8. **远程规划 + 本地执行分离**——重规划交给更大的 context window，本地只负责执行
9. **迭代拒绝循环**——计划被拒后不重新开始，而是在原 context 中迭代修改

---

## 5. 计划到执行的交接

### 5.1 ExitPlanModeV2 的权限桥

计划审批不只是"同意/拒绝"——它带着语义化权限请求。这意味着计划不只描述"做什么"，还声明"需要什么权限"。审批一步到位，不需要执行时反复请求。

### 5.2 Team Lead 的 Plan Approval

Agent Teams 支持**计划前置审批**：

```
用户: "Spawn an architect teammate to refactor the auth module. 
       Require plan approval before they make any changes."
```

Teammate 在只读 plan mode 中工作 → 产出计划 → 发送给 Lead → Lead 审批/拒绝 → 审批后 teammate 退出 plan mode 开始实现。

Lead 可以自主决策审批，用户通过 prompt 影响判断标准（如 "only approve plans that include test coverage"）。

### 5.3 Coordinator 的 Continue vs. Spawn 决策

从源码泄露的决策表：

| 情况 | 机制 | 原因 |
|------|------|------|
| 找到精确文件要编辑 | **Continue** | Worker 保留文件上下文 |
| 广泛调研后窄实现 | **Spawn fresh** | 避免探索噪音 |
| 纠正失败 | **Continue** | Worker 有错误上下文 |
| 验证另一个 Worker 的输出 | **Spawn fresh** | 验证者需要新鲜视角 |
| 根本方向错误 | **Spawn fresh** | 防止上下文污染 |

**可偷模式 P0**：
10. **Continue vs. Spawn 决策表**——不是所有失败都应该重试，有些需要全新 context

---

## 6. 多 Agent 计划分发

### 6.1 Agent Teams 架构

四个组件：

| 组件 | 角色 |
|------|------|
| **Team Lead** | 创建团队、分派任务、综合结果 |
| **Teammates** | 独立 Claude Code 实例，各自有 context window |
| **Shared Task List** | 中央任务队列，所有 Agent 可见 |
| **Mailbox** | 点对点消息系统，不经过 Lead 中转 |

### 6.2 通信拓扑

- **Subagents**：星型（只向主 Agent 报告）
- **Agent Teams**：网状（任意 teammate 间直接通信）

这是根本性的架构差异。Subagents 像下属，Agent Teams 像同事。

### 6.3 任务认领与锁定

- Teammate 完成一个 task → 自动认领下一个未分配、未阻塞的 task
- **文件级锁定**防止竞争条件——多个 teammate 同时认领同一 task 时，锁保证只有一个成功
- Lock 实现：30 次重试，5-100ms 退避（最大 ~2.6s 等待）

### 6.4 文件所有权

**防冲突核心原则**：每个 Agent 拥有不同的文件/目录，绝不共享文件。

推荐的 7-Agent 并行化分工：
1. 组件创建
2. 样式/CSS
3. 测试文件
4. 类型定义
5. 自定义 hooks/工具
6. 路由和导入
7. 配置/文档

### 6.5 两阶段验证

- **实现阶段**：Tasks 1-5 并行（核心开发）
- **验证阶段**：顺序执行（防止验证半成品文件）

### 6.6 资源消耗

3 个 teammate ≈ 3-4x 单 session 的 token 消耗。推荐 3-5 个 teammate，超过后边际收益递减。

**可偷模式 P0**：
11. **Shared Task List + 文件锁认领**——中央任务队列 + 原子认领，防止竞争
12. **网状通信拓扑**——teammate 间直接通信，不需要经过 Lead 中转
13. **两阶段执行**——实现并行 + 验证串行

---

## 7. 计划质量保证

### 7.1 Hooks 作为质量门

Agent Teams 提供三个 Hook 事件：

| Hook | 触发时机 | exit code 2 的效果 |
|------|---------|-------------------|
| `TeammateIdle` | Teammate 即将空闲 | 发送反馈，让 teammate 继续工作 |
| `TaskCreated` | 任务被创建时 | 阻止创建，发送反馈 |
| `TaskCompleted` | 任务被标记完成时 | 阻止完成，发送反馈 |

这是一个**可编程的质量门**——你可以在 hook 里跑测试、lint、覆盖率检查，不通过就拒绝完成。

### 7.2 Coordinator 的纪律

从泄露的 coordinator prompt：

> "Do not rubber-stamp weak work"
> "You must understand findings before directing follow-up work"

这不是客气话——它是防止 Coordinator 退化为转发器的硬约束。

### 7.3 计划迭代

Plan Mode 支持**无限迭代**：
- 用户拒绝 → 计划留在 context 中 → Claude 修改 → 重新提交
- ULTRAPLAN 的 rejected 状态也支持迭代，不会丢失 context

### 7.4 与 Orchestrator 的差距

Orchestrator 的 `plan_template.md` 有 "No Placeholder Iron Rule"，但**没有运行时强制机制**。Claude Code 通过：
- Hook 在 task 创建/完成时自动拦截
- Coordinator prompt 约束不得抽象引用
- Plan mode 的工具级只读限制

我们的 Iron Rule 只在 prompt 层面，没有程序化强制。

**可偷模式 P0**：
14. **Task Hooks 质量门**——TaskCreated/TaskCompleted hook 实现可编程的 Definition of Done
15. **反橡皮图章 prompt**——Coordinator 被明确要求"不准通过低质量工作"

---

## 8. 与 Orchestrator 规划体系的对比

### 8.1 Orchestrator 的优势

| 维度 | Orchestrator 做得更好 |
|------|---------------------|
| **计划格式** | 严格的模板（File Map + verify + 依赖声明）比自由 Markdown 更可靠 |
| **No Placeholder Rule** | 明确禁用短语列表 + 替代方案，比 "be specific" 更有操作性 |
| **步骤粒度** | 明确 "2-5 分钟" 约束 |
| **验证命令** | 每步必须有 `→ verify:` 命令 |

### 8.2 Orchestrator 缺少什么

| 维度 | Claude Code 有而我们没有 |
|------|-------------------------|
| **权限状态机** | 硬切换规划/执行模式，不靠 prompt 纪律 |
| **计划审批流** | ExitPlanModeV2 + 语义化权限请求 |
| **用户可编辑计划** | `Ctrl+G` 在编辑器中修改 |
| **任务持久化** | 文件系统存储，跨 session 存活 |
| **双向依赖** | `blockedBy` + `blocks` 自动解锁 |
| **多 Agent 任务队列** | Shared Task List + 文件锁认领 |
| **网状通信** | Teammate 间直接消息 |
| **质量门 Hooks** | TaskCreated/TaskCompleted 可编程拦截 |
| **远程规划** | 卸载到大 context window 的 CCR |
| **Continue vs. Spawn 决策** | 明确的决策表指导何时复用/何时新建 |
| **两阶段执行** | 实现并行 + 验证串行 |

---

## 可偷模式汇总

### P0（直接可实施）

| # | 模式 | 来源 | 实施建议 |
|---|------|------|---------|
| 1 | 权限状态机 | Plan Mode | 在 dispatch-gate 中增加 plan/execute 模式切换 |
| 2 | 语义化权限请求 | ExitPlanModeV2 | 计划审批时附带"需要什么能力"的描述 |
| 3 | 用户可编辑计划 | Plan Mode | 计划写入文件后允许用户修改，reload 后继续 |
| 4 | 双向依赖字段 | Tasks API | plan_template.md 增加 `blocks:` 字段 |
| 5 | Task 文件持久化 | Tasks API | 三省六部的任务状态写入 `.claude/tasks/` |
| 6 | 双表单模式 | TodoWrite | 每个 task 同时有祈使句和进行时描述 |
| 7 | 原子写入 | Tasks API | rename-based atomic write 防并发损坏 |
| 10 | Continue vs. Spawn 决策表 | coordinatorMode | 在 sub-agent 派单时加入决策矩阵 |
| 11 | Shared Task List + 锁 | Agent Teams | 中央任务队列 + 原子认领 |
| 12 | 网状通信拓扑 | Agent Teams | teammate 间直接通信能力 |
| 13 | 两阶段执行 | Agent Teams | 实现并行 + 验证串行 |
| 14 | Task Hooks 质量门 | Agent Teams | TaskCreated/TaskCompleted 钩子 |
| 15 | 反橡皮图章 prompt | coordinatorMode | Coordinator 系统 prompt 加 "不准通过低质量工作" |

### P1（需要更多基础设施）

| # | 模式 | 来源 | 实施建议 |
|---|------|------|---------|
| 8 | 远程规划 + 本地执行分离 | ULTRAPLAN | 需要远程 CCR 基础设施 |
| 9 | 迭代拒绝循环 | ULTRAPLAN | 被拒后原地迭代，不重新开始 |

---

## 架构启示

### 最核心的洞察

Claude Code 的规划体系有一个贯穿始终的设计哲学：**规划和执行是不同的权限域**。

这不是"先想后做"的软约束——它是通过状态机、工具白名单、权限注入三层硬编码的。在 Plan Mode 中你物理上无法写文件，不是不建议写，是工具被禁用了。

Orchestrator 目前靠 prompt 纪律维持"先规划后执行"，但 prompt 纪律是会退化的。需要的是硬切换机制。

### 第二个洞察

**Task 和 Plan 是两回事**。Plan 是高层设计文档，Task 是可追踪的执行单元。Claude Code 让你先在 Plan Mode 中产出设计，然后 TaskCreate 把设计分解为可追踪的 tasks。Orchestrator 的 plan_template.md 把两者混在了一起——steps 既是计划也是执行清单。

### 第三个洞察

**质量控制在运行时，不在模板里**。Orchestrator 的 "No Placeholder Iron Rule" 是模板级别的约束，Claude Code 的 TaskCreated/TaskCompleted hooks 是运行时级别的门控。前者靠自觉，后者靠代码。

---

## Sources

- [Claude Code Agent Teams 官方文档](https://code.claude.com/docs/en/agent-teams)
- [Claude Code Common Workflows](https://code.claude.com/docs/en/common-workflows)
- [Claude Code Plan Mode — DeepWiki](https://deepwiki.com/ChinaSiro/claude-code-sourcemap/3.5-plan-mode-and-worktree-tools)
- [Plan Mode Enhanced Prompt](https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/agent-prompt-plan-mode-enhanced.md)
- [Claude Code System Prompts 仓库](https://github.com/Piebald-AI/claude-code-system-prompts)
- [Tasks API vs TodoWrite — DeepWiki](https://deepwiki.com/FlorianBruniaux/claude-code-ultimate-guide/7.1-tasks-api-vs-todowrite)
- [Task Operations and Lifecycle — DeepWiki](https://deepwiki.com/FlorianBruniaux/claude-code-ultimate-guide/8.2-task-operations-and-lifecycle)
- [TodoWrite Tool Description](https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/tool-description-todowrite.md)
- [TaskCreate Tool Description](https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/tool-description-taskcreate.md)
- [Claude Code 源码逆向分析](https://sathwick.xyz/blog/claude-code.html)
- [Claude Code 架构深度分析 — Glorics](https://glorics.com/claude-code-architecture-deep-dive)
- [Claude Code 源码泄露分析 — Alex Kim](https://alex000kim.com/posts/2026-03-31-claude-code-source-leak/)
- [Claude Code Task Distribution](https://claudefa.st/blog/guide/agents/task-distribution)
- [Claude Code Sub-Agent Best Practices](https://claudefa.st/blog/guide/agents/sub-agent-best-practices)
- [Todo Lists — Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/todo-tracking)
- [ClaudeLog Plan Mode](https://claudelog.com/mechanics/plan-mode/)
- [Plan Mode — codewithmukesh](https://codewithmukesh.com/blog/plan-mode-claude-code/)
