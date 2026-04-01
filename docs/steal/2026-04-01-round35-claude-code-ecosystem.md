# Round 35: Claude Code 生态 8 仓库偷师报告

**日期**: 2026-04-01
**分支**: steal/claude-code-ecosystem-r35
**目标**: 8 个 Claude Code 相关仓库的模式提取与升级路径

## 仓库清单

| # | 仓库 | 类型 | Star 级 |
|---|------|------|---------|
| 1 | oboard/claude-code-rev | TypeScript 源码还原 | ★★★★★ |
| 2 | griffinhilly/claude-code-synthesis | 方法论体系（18 skill） | ★★★★★ |
| 3 | shanraisshan/claude-code-best-practice | 配置百科 | ★★★★ |
| 4 | brennercruvinel/CCPlugins | 24 命令插件集 | ★★★★ |
| 5 | farouqaldori/claude-island | Dynamic Island 通知（Swift） | ★★★ |
| 6 | 0xxue/claude-island | 跨平台 Electron 版 | ★★★ |
| 7 | aissablk1/claude-island-perf-fix | 性能优化 + 安全修复 | ★★★★ |
| 8 | OneRedOak/claude-code-workflows | 工作流模板 | ★★ |

---

## P0 模式（立即可偷，高价值）

### P0-1: DreamTask 预测性预取

**来源**: claude-code-rev `/src/tasks/DreamTask.ts`

Claude Code 内部有一个 DreamTask 类型——在用户思考时后台推测下一步需求并预取结果。这不是普通的缓存，是**推测执行（speculative execution）**。

**当前缺口**: Orchestrator 的 TaskExecutor 只处理显式派单，没有预测能力。

**升级路径**:
```
1. 在 Governor 空闲时（等待用户输入），分析最近 3 轮对话的模式
2. 预测 top-3 可能的下一步操作（基于部门历史 + 上下文）
3. 启动低优先级 DreamTask，结果缓存 60s
4. 用户实际请求命中时直接返回缓存结果
```

**实施复杂度**: 中 | **预期收益**: 响应延迟降低 40-60%

---

### P0-2: 双层 Feature Gate（编译时 + 运行时）

**来源**: claude-code-rev `/src/entrypoints/cli.tsx`

```typescript
// 层 1: Bun feature() — 编译时死代码消除，零运行时开销
if (feature('COORDINATOR_MODE') && ...) { ... }

// 层 2: GrowthBook cached gate — 运行时灰度，可能过时但不阻塞
checkStatsigFeatureGate_CACHED_MAY_BE_STALE('tengu_streaming_tool_execution2')
```

**当前缺口**: Orchestrator 用 exec-policy.yaml 做运行时策略，没有编译时消除。功能开关靠 if/else 硬编码。

**升级路径**:
```
1. 在 config/ 新增 feature_gates.yaml，声明所有可选功能
2. 运行时加载时按 gate 状态动态注册/跳过模块
3. 关键路径功能（如 group_orchestration）加 cached gate，降级时不阻塞
```

**实施复杂度**: 低 | **预期收益**: 新功能上线风险降低，灰度发布能力

---

### P0-3: COMP 四文件正交文档系统

**来源**: claude-code-synthesis

| 文件 | 受众 | 更新频率 | 职责 |
|------|------|---------|------|
| CLAUDE.md | Agent | 极少 | 行为契约 |
| ORIENT.md | 人类 | 阶段变更时 | 新人导向 |
| MEMORY.md | 双方 | 每次会话 | 累积知识 |
| PLAN.md | 双方 | 每次会话 | 方向路线 |

**当前缺口**: Orchestrator 的 CLAUDE.md 承担了太多职责（行为 + 导向 + 部分知识），boot.md 做了一部分分离但不彻底。

**升级路径**:
```
1. 从 CLAUDE.md 中提取人类导向内容 → ORIENT.md
2. PLAN.md 已有（docs/plan/），但没有和 CLAUDE.md 联动
3. MEMORY.md 已有（auto memory），但缺少 ORIENT.md 层
4. 四文件各自独立维护，boot.md 编译时只拉 CLAUDE.md + MEMORY.md
```

**实施复杂度**: 低 | **预期收益**: 上下文更清晰，减少 CLAUDE.md 膨胀

---

### P0-4: Dialectic 对抗式多 Agent 审查

**来源**: claude-code-synthesis `/skills/dialectic-review/SKILL.md`

四种模式：
- **Review**: Critics(3) → Defenders(1) → Referees(1)
- **Ideate**: Generators(5) → Challengers(2) → Synthesizers(3)
- **Tradeoff**: Advocates(N) → Counter-advocates(N) → Referees(3)
- **Premortem**: Pessimists(3) → Optimists(2) → Risk Assessor(1)

**关键设计**: 每个 Agent 只拿到 subject + COMP 文件 + 上一阶段输出，**不拿对话历史**，防止锚定效应。

**当前缺口**: 中书省（LLM Council）有五元老审议，但没有对抗结构。当前是独立评分 → 汇总，不是辩论 → 裁决。

**升级路径**:
```
1. 在中书省增加 dialectic_mode 参数
2. review 模式：分 critic/defender/referee 三角色，串行三阶段
3. premortem 模式：用于高风险决策（生产部署、架构变更）
4. 上下文隔离：每个 agent 只拿 task spec + 上阶段摘要
```

**实施复杂度**: 中 | **预期收益**: 决策质量显著提升（尤其高风险场景）

---

### P0-5: 三次修复升级规则

**来源**: claude-code-synthesis `/skills/debug/SKILL.md`

```
连续 3 次 fix 尝试失败 → STOP
不要尝试第 4 次 → 架构可能有问题
升级到人类决策
```

**当前缺口**: Orchestrator 的 checkpoint_recovery.py 有重试逻辑，但没有硬性上限。yoyo-evolve 的 9 轮修复上限太高。

**升级路径**:
```
1. TaskExecutor 增加 fix_attempt_count 追踪
2. 同一 task 的第 3 次失败 → 标记为 ESCALATED，不再自动重试
3. 通知用户："3 次修复失败，怀疑架构问题，需要人类介入"
4. 保留所有 3 次的 diff 和错误日志供诊断
```

**实施复杂度**: 低 | **预期收益**: 防止无限循环浪费 token

---

### P0-6: Hook 性能 Guard Clause

**来源**: claude-island-perf-fix

```bash
# 第一行：前置条件不满足就零开销退出
[ -S "$SOCKET" ] || exit 0
```

活跃会话每分钟 ~150 次 hook 触发。Python hook 73ms/次 = **每分钟 11 秒 CPU 开销**。Bash guard clause 降到 20ms/次。

**当前缺口**: Orchestrator 的 guard-redflags.sh 每次都完整执行 14 个 pattern 匹配，即使输入明显无害。

**升级路径**:
```
1. 所有 hook 脚本第一行加 guard clause（检查前置条件）
2. guard-redflags.sh: 输入 < 10 字符直接 pass（短命令不可能是复杂攻击）
3. audit.sh: 检查日志文件是否可写，不可写直接 exit
4. 性能敏感 hook 用 bash 而非 python
```

**实施复杂度**: 极低 | **预期收益**: hook 开销减少 50-70%

---

### P0-7: Session State 持久化文件夹

**来源**: CCPlugins

```
project/
├── refactor/
│   ├── plan.md        # 重构路线图
│   └── state.json     # 已完成的变换 + 决策记录
├── security-scan/
│   └── state.json
```

每个长时间运行的命令在项目根目录创建专属状态文件夹，支持 `/command resume` 跨会话恢复。

**当前缺口**: Orchestrator 的 task 状态存在 SQLite（EventsDB），但没有人类可读的中间状态快照。会话断开后只能看 DB 记录，不能直接 resume。

**升级路径**:
```
1. 高价值 task（偷师、重构、审计）执行时创建 .task/<task-id>/
2. 内含 plan.md（当前计划）+ state.json（进度检查点）+ artifacts/
3. 下次会话可以 /resume <task-id> 从检查点继续
4. 完成后移到 .task/archive/
```

**实施复杂度**: 中 | **预期收益**: 长任务断点续传能力

---

## P1 模式（近期可偷，中等价值）

### P1-1: Confidence-Scored Planning

**来源**: claude-code-synthesis

计划中每一步标注置信度，低置信度步骤先派研究 agent 探索再动手。

**当前做法**: plan_template.md 有 verify 字段但没有 confidence 字段。

**升级**: 在 plan template 每步增加 `confidence: high|medium|low`，Scrutinizer 对 low 步骤自动触发 fact-finding。

---

### P1-2: Red Flag 语言检测

**来源**: claude-code-synthesis

"should work" / "probably fine" / "seems to" / "Perfect!" → 触发强制验证。

**当前做法**: verification-gate skill 有 banned phrases 但只在完成声明时检查，不覆盖中间过程。

**升级**: PostToolUse hook 扫描 agent 输出中的乐观语言，触发 warning 或要求提供证据。

---

### P1-3: 按模型分派策略

**来源**: claude-code-synthesis

| 模型 | 适用场景 |
|------|---------|
| Haiku | 批量机械活（分类、标签、格式转换） |
| Sonnet | 定义清晰的执行任务、高并发并行 |
| Opus | 判断/裁决、新颖关联、审查其他 agent |

**当前做法**: manifest.yaml 有 `model: sonnet|haiku`，但选择标准不明确。

**升级**: manifest.yaml 增加 `model_rationale` 字段，文档化选择原因。Scrutinizer 根据 cognitive_mode 建议最优模型。

---

### P1-4: De-Para 迁移映射

**来源**: CCPlugins `/refactor`

重构时生成 Before-After 对照表，100% 覆盖检查。

**升级**: 大规模重构任务输出时附带 de-para 表，ReviewManager 验证覆盖率。

---

### P1-5: Agent Frontmatter 高级字段

**来源**: claude-code-best-practice

| 字段 | 用途 |
|------|------|
| `isolation: "worktree"` | Git worktree 隔离，自动清理 |
| `skills:` | 预加载领域知识（注入不调用） |
| `mcpServers:` | Agent 级 MCP 作用域限定 |
| `initialPrompt:` | Agent 启动时自动提交首轮 |
| `effort: low\|medium\|high\|max` | 模型 effort 覆盖 |

**升级**: 检查 Orchestrator agent dispatch 是否充分利用这些字段，补齐缺失的。

---

### P1-6: PTC + Tool Search Token 优化

**来源**: claude-code-best-practice

- **Programmatic Tool Calling**: 3+ 依赖调用批量化 → 省 37% token
- **Tool Search Tool**: defer 10+ tool 定义 → 省 85% token

**当前做法**: Orchestrator 通过 manifest allowed_tools 限制工具集，但没有 defer loading。

**升级**: 低频工具（如 WebSearch、远程触发）改为 deferred，按需加载。

---

### P1-7: 4 种 Context 压缩策略

**来源**: claude-code-rev

| 策略 | 触发 | 效果 |
|------|------|------|
| Auto-compact | 达到阈值自动触发 | 通用压缩 |
| Snip compact | HISTORY_SNIP gate | 历史片段裁剪 |
| Context Collapse | feature gate | 合并相似上下文 |
| Microcompact | 边界检测 | 微粒度压缩 |

**当前做法**: 依赖 Claude Code 内置压缩，没有 Orchestrator 层面的主动策略。

**升级**: 长对话 task 主动触发 compact，而不是等 Claude Code 自动处理。在 PostCompact hook 重新注入关键上下文。

---

## P2 模式（长期参考）

### P2-1: Bridge 远程会话编排
40+ 文件的远程会话系统，JWT 刷新、指数退避、trusted device token。当 Orchestrator 需要远程 agent 时参考。

### P2-2: Coordinator Mode Worker 工具限制
多 Agent 编排时 worker 只拿安全工具子集（READ, EDIT, AGENT_TOOL），不能 BASH。比当前 manifest 的 allowed_tools 更细粒度。

### P2-3: ML 分类器自动审批
权限系统除了规则和 hook，还有 ML 分类器做 bash 命令自动审批。当 Orchestrator 权限判断足够复杂时考虑。

### P2-4: Claude Island 通知层
Dynamic Island 式通知 + 权限审批 UI。当 Claw 需要更丰富的视觉反馈时参考 3 态 UI 模式（Dot/Collapsed/Expanded）。

### P2-5: 对话式命令语言
CCPlugins 用 "I'll analyze..." 而非命令式 "Analyze..."，研究表明触发更好的协作推理。考虑在 SKILL.md 中采用。

---

## 安全发现

### SEC-1: Shell 脚本 JSON 注入（claude-island-perf-fix 修复）
**问题**: bash 字符串拼接构建 JSON → 注入风险
**修复**: 用 `jq` 构建 JSON，参数化传入
**我们的状况**: guard-redflags.sh 用 grep pattern matching，不构建 JSON，风险较低。但 audit.sh 的日志格式化可以检查一下。

### SEC-2: Socket 所有权验证
**问题**: `/tmp/claude-island.sock` 可被其他用户抢占
**修复**: `stat -f '%u' "$SOCKET"` 验证 owner = current user
**适用**: Orchestrator 的 Unix socket 通信（如有）需要类似检查。

### SEC-3: Hook 输入大小限制
**问题**: 恶意大输入导致 hook 脚本 OOM
**修复**: `head -c 65536` 限制输入
**升级**: guard-redflags.sh 加 `head -c 65536` 前置。

---

## 实施优先级排序

| 序号 | 模式 | 复杂度 | 收益 | 建议时间 |
|------|------|--------|------|---------|
| 1 | P0-6 Hook Guard Clause | 极低 | hook 开销 -50% | 本周 |
| 2 | P0-5 三次修复上限 | 低 | 防止 token 浪费 | 本周 |
| 3 | P0-3 COMP 四文件 | 低 | 上下文清晰度 | 本周 |
| 4 | P1-2 Red Flag 检测 | 低 | 验证纪律 | 下周 |
| 5 | P0-7 Session State 持久化 | 中 | 断点续传 | 下周 |
| 6 | P0-4 Dialectic Review | 中 | 决策质量 | 下周 |
| 7 | P0-1 DreamTask 预取 | 中 | 响应延迟 -40% | 两周内 |
| 8 | P0-2 Feature Gate | 低 | 灰度发布 | 两周内 |

---

## 总结

Round 35 覆盖 8 个仓库，提取 **7 个 P0 + 7 个 P1 + 5 个 P2 = 19 个模式**。

最大的惊喜是 `claude-code-rev` 的源码还原——DreamTask、4 种压缩策略、双层 Gate 这些在 npm 包层面完全不可见的内部架构。`claude-code-synthesis` 的 COMP 系统和 Dialectic Review 是方法论层面的重大参考。`claude-island-perf-fix` 的 hook 性能优化直接适用于我们的 guard 体系。

**下一步**: 从 P0-6（Guard Clause）开始，因为改动最小、见效最快——两行代码，hook 性能翻倍。
