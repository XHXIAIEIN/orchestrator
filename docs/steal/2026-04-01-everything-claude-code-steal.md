# 偷师报告：affaan-m/everything-claude-code

**仓库**: https://github.com/affaan-m/everything-claude-code
**星数**: 128K+ (截至 2026-04-01)
**定位**: Claude Code 插件生态 — 30 个专业 Agent、135+ Skill、60+ Command、完整 Hook 生命周期
**语言**: JavaScript (hooks/scripts) + Rust (ecc2 控制面) + Markdown (知识库)
**版本**: v1.9.0

---

## 仓库概述

Everything Claude Code (ECC) 是目前 Claude Code 生态中最大的第三方插件仓库。它做的事情和 Orchestrator 有大量重叠但路径不同：Orchestrator 走的是"单体管家 + SOUL 灵魂系统 + Docker 容器化"路线，ECC 走的是"Claude Code 原生插件 + 跨 IDE 适配 + 社区分发"路线。

核心架构是六层：
1. **Rules** — 按语言分门别类的编码/安全/测试规范（13 种语言 x 5 维度）
2. **Agents** — 30 个专业子 Agent（planner、code-reviewer、security-reviewer、build-error-resolver 等）
3. **Skills** — 135+ 个知识卡片（从 TDD 到 strategic-compact 到 continuous-learning-v2）
4. **Commands** — 60+ 个 slash 命令（/orchestrate、/santa-loop、/devfleet、/prp-plan 等）
5. **Hooks** — 完整的生命周期 hook 系统（PreToolUse → PostToolUse → Stop → SessionEnd）
6. **ecc2** — Rust 写的控制面 TUI（session manager + worktree + daemon + observability）

同时它适配了 5 个 IDE surface：Claude Code (.claude/)、Cursor (.cursor/)、Codex (.codex/)、OpenCode (.opencode/)、Kiro (.kiro/) 和 Trae (.trae/) —— 这个跨平台策略本身就是一个模式。

---

## 模式清单

### P0 — 立即可偷

#### 1. Instinct-Based Continuous Learning (本能学习系统)
**来源**: `skills/continuous-learning-v2/SKILL.md`、`commands/evolve.md`、`commands/learn.md`
**核心思路**: 用 PreToolUse/PostToolUse hook 100% 捕获所有工具调用，写入 observations.jsonl，后台用 Haiku 分析提取原子"本能"（trigger + action + confidence 0.3-0.9）。本能按项目隔离（git remote hash），高置信度的自动提升到全局。本能自动聚类后可"进化"为 skill/command/agent。
**与 Orchestrator 的关系**: 我们有 experiences.jsonl 和 MEMORY.md，但是：
- **缺少自动捕获**: 我们的经验记录是手动的，ECC 用 hook 100% 自动捕获
- **缺少置信度衰减**: 我们没有 confidence scoring 和 decay 机制
- **缺少项目隔离**: 我们的记忆是全局的，没有按项目哈希隔离
- **缺少进化管道**: 本能 → 聚类 → skill/command/agent 的自动进化路径

#### 2. Run-With-Flags Hook Runner (条件化 Hook 执行器)
**来源**: `hooks/hooks.json`、`scripts/hooks/run-with-flags.js`
**核心思路**: 所有 hook 通过一个统一的 runner 执行，支持 flag 级别控制（`minimal`/`standard`/`strict`）。每个 hook 注册时声明自己在哪些 flag 级别下激活。用户通过环境变量选择级别，一个开关控制整套行为。
**与 Orchestrator 的关系**: 我们的 guard.sh/audit.sh 是硬编码的。ECC 的 flag 分级（minimal = 最小干扰，standard = 日常，strict = 严格审查）可以直接偷过来，让 hook 系统更灵活。

#### 3. Strategic Compact (战略性压缩)
**来源**: `skills/strategic-compact/SKILL.md`
**核心思路**: 用 hook 追踪 tool call 次数，到阈值时建议用户手动 /compact，而不是让系统自动压缩。关键洞察：自动压缩往往在任务中间触发，丢失关键上下文。提供一张"压缩决策表"：研究→规划时压缩✓、实现中间不压缩✗、调试后压缩✓。还有"什么能活过压缩"的清单。
**与 Orchestrator 的关系**: 我们的 9-section compact template 已经很好了，但缺少"什么时候该压缩"的决策引导。这个 Trigger-Table Lazy Loading 概念（用关键词映射延迟加载 skill 而不是全部预加载）也很有价值。

#### 4. Santa Loop (对抗性双审循环)
**来源**: `commands/santa-loop.md`
**核心思路**: 两个独立审查者（Claude Opus + 外部模型如 GPT-5.4/Gemini 2.5 Pro），无共享上下文，必须双方都通过才放行。NAUGHTY 时修复后重新起新审查者（防锚定偏见），最多 3 轮。模型多样性是核心——不同训练数据、不同盲点。
**与 Orchestrator 的关系**: 我们的 Review Swarm (Round 22) 是并行审查但用同一模型族。Santa Loop 的关键差异是**跨模型族审查** + **新鲜审查者**（每轮无记忆），这两个思路可以增强我们的中书省审议系统。

#### 5. Config Protection Hook (配置保护)
**来源**: `hooks/hooks.json` 中的 `pre:config-protection`
**核心思路**: 拦截对 linter/formatter 配置文件的修改。Agent 倾向于通过放宽规则来"修复"lint 错误，这个 hook 强制 agent 去修代码而不是改配置。
**与 Orchestrator 的关系**: 我们的 Gate Functions 覆盖了 delete/reset/config 修改，但没有专门拦截"放宽 lint 规则"这种隐蔽行为。这是一个精准的 hook 值得偷。

#### 6. Session Save/Resume Protocol (会话存档协议)
**来源**: `commands/save-session.md`、`commands/resume-session.md`
**核心思路**: 结构化的会话存档格式，包含 8 个必填节：在做什么、什么有效（附证据）、什么失败了（附原因）、什么没试过、文件状态表、决策记录、阻塞项、下一步。关键洞察：**"什么失败了"是最重要的节**——没有它，下一个 session 会盲目重试已失败的方案。
**与 Orchestrator 的关系**: 我们的 /remember skill 只保存 key-value 记忆。ECC 的会话存档是完整的**决策现场快照**，这个格式可以直接用于我们的 session handoff。

### P1 — 有价值待适配

#### 7. DevFleet Multi-Agent Orchestration (多 Agent 编队)
**来源**: `commands/devfleet.md`
**核心思路**: 通过 MCP server 管理并行 Agent。`plan_project()` 把自然语言拆成 DAG 任务图，每个 mission 在隔离的 git worktree 中执行，完成后自动 merge。支持依赖链、自动调度、并发限制。
**与 Orchestrator 的关系**: 我们有 worktree agent 和三省六部派单，但缺少 **DAG 任务依赖图** 和 **自动 merge 后触发下游** 的能力。DevFleet 的 `depends_on` + `auto_dispatch` 模式值得参考。

#### 8. PRP (Prompt-Ready Plan) Pipeline
**来源**: `commands/prp-plan.md`、`commands/prp-implement.md`、`commands/prp-prd.md`、`commands/prp-commit.md`、`commands/prp-pr.md`
**核心思路**: 完整的 PRD → Plan → Implement → Commit → PR 五阶段管道。Plan 阶段做 8 类代码搜索 + 5 条追踪分析，产出包含"必读文件"、"要镜像的模式"、"不构建的清单"的自包含计划文档。关键铁律：**如果实现时还需要搜索代码库，说明计划不够完整**。
**与 Orchestrator 的关系**: 我们有 plan_template.md，但 PRP 的"Mandatory Reading Table" + "Patterns to Mirror" + "No Prior Knowledge Test" 这三个检查点比我们更严格。特别是"Patterns to Mirror"——要求从代码库中提取实际代码片段作为模式参考，而不是抽象描述。

#### 9. Prompt Optimizer (/prompt-optimize)
**来源**: `commands/prompt-optimize.md`
**核心思路**: 6 阶段分析管道（项目检测 → 意图分类 → 复杂度评估 → ECC 组件匹配 → 缺失上下文检测 → 工作流推荐），把用户的粗糙 prompt 优化为带 ECC 组件推荐的精准 prompt。**只做分析不执行**，输出 Full Version + Quick Version。
**与 Orchestrator 的关系**: 我们没有 prompt 优化层。这个可以适配为三省六部的"中书省翻译层"——用户说"加个验证"，翻译层输出包含具体 skill/agent/command 推荐的完整 prompt。

#### 10. Cross-Harness Surface Adapter (跨 IDE 适配层)
**来源**: `.cursor/`、`.codex/`、`.opencode/`、`.kiro/`、`.trae/`、`.agents/`、`.codebuddy/`
**核心思路**: 同一套知识（skills、agents、rules）通过不同的目录结构和配置格式适配到 6 个 IDE。根目录是 source of truth，各 surface 是投影。agent.yaml 作为统一的 gitagent manifest 描述所有 skill。
**与 Orchestrator 的关系**: 我们目前只跑在 Claude Code 上。如果未来要支持 Codex/Cursor/Kiro，这套适配层的架构可以参考。暂时 P1 因为不是当前优先级。

#### 11. ecc2 Rust Control Plane (Rust 控制面)
**来源**: `ecc2/src/`（main.rs、session/manager.rs、tui/、worktree/、observability/）
**核心思路**: 用 Rust + tokio + ratatui 写的 CLI 控制面。Session manager 管理多个 agent 进程（create/start/stop/resume），每个 session 可分配独立 worktree，SQLite 存状态，TUI dashboard 实时显示。支持 cost/token budget 上限。
**与 Orchestrator 的关系**: 我们用 Docker + Node.js dashboard。ECC 的 Rust 控制面更轻量，但我们的 Docker 方案更隔离。值得偷的是 **session resume**（失败的 session 可以重启而不丢状态）和 **cost_budget_usd / token_budget** 配置。

#### 12. Selective Install Profiles (选择性安装配置)
**来源**: `manifests/install-profiles.json`、`manifests/install-modules.json`
**核心思路**: 5 个安装档位（core → developer → security → research → full），每个档位包含不同的模块组合。模块之间有依赖图（workflow-pack 依赖 runtime-core）。用户按需选择，避免全量加载 135 个 skill。
**与 Orchestrator 的关系**: 我们的 boot.md 是全量加载。如果 skill 数量继续增长，需要类似的分级加载策略。Trigger-Table Lazy Loading（关键词触发按需加载 skill）更适合我们当前体量。

### P2 — 参考级

#### 13. Homunculus Instinct Inheritance (本能继承链)
**来源**: `.claude/homunculus/instincts/inherited/`
**核心思路**: 本能分 personal（自动学习）和 inherited（从其他仓库导入）。`/instinct-import` 可以导入别人的本能库，/instinct-export 可以导出。团队可以共享学到的模式。
**与 Orchestrator 的关系**: 相当于 experiences.jsonl 的可分享版本。目前我们是单用户，但如果要做团队版本，这个 import/export 机制有参考价值。

#### 14. MCP Health Check Hook
**来源**: `hooks/hooks.json` 中的 `pre:mcp-health-check` 和 `PostToolUseFailure`
**核心思路**: 在每次 MCP 工具调用前检查 server 健康状态，失败后标记不健康并尝试重连。用 `PostToolUseFailure` hook 追踪失败的 MCP 调用。
**与 Orchestrator 的关系**: 我们用多个 MCP server（Chrome DevTools、Context7 等），但没有健康检查。当 MCP server 挂掉时，agent 会盲目重试。这个 hook 可以避免无效调用。

#### 15. Desktop Notification Hook
**来源**: `hooks/hooks.json` 中的 `stop:desktop-notify`
**核心思路**: Claude 回复完成后发送桌面通知（macOS/WSL），包含任务摘要。
**与 Orchestrator 的关系**: 我们有 Telegram 通知但没有桌面通知。对于长时间运行的任务，桌面通知是更即时的反馈通道。

#### 16. Cost Tracker Hook
**来源**: `hooks/hooks.json` 中的 `stop:cost-tracker` 和 `post:bash:cost`
**核心思路**: 每个 response 结束时记录 token 使用量和成本。session manager 中也有 `cost_budget_usd` 和 `token_budget` 字段。
**与 Orchestrator 的关系**: 我们在 MEMORY 中记录了 token 优化发现，但没有自动化的成本追踪。可以给我们的 audit.sh 加上。

#### 17. Post-Edit Accumulator (编辑累积器)
**来源**: `hooks/hooks.json` 中的 `post:edit:accumulate` 和 `stop:format-typecheck`
**核心思路**: 每次 Edit/Write 后记录被修改的文件路径，但不立即运行 format/typecheck。等到 Stop 时批量运行一次。避免了每次编辑后都跑 linter 的开销。
**与 Orchestrator 的关系**: 好的性能优化思路。我们的 hook 如果要做 format/lint 检查，应该用这种"累积-批处理"模式而不是逐次触发。

---

## 结构性发现

### 1. 知识的分层架构
ECC 的知识组织是三层：**Rules（永远遵守）→ Skills（按需激活）→ Commands（用户触发）**。这比我们的"CLAUDE.md 里塞所有规则"更清晰。Rules 是 always-on 的，skill 是 context-dependent 的，command 是 user-initiated 的。

### 2. 语言维度的规则矩阵
`rules/` 目录按 `{language}/{dimension}` 组织（如 `python/security.md`、`golang/testing.md`）。13 种语言 x 5 个维度（coding-style、hooks、patterns、security、testing）= 65 个规则文件。这个矩阵化的组织方式让规则查找极其精准。

### 3. 插件化的分发模型
`.claude-plugin/plugin.json` 定义了标准的插件清单格式（agents 列表、skills 路径、commands 路径）。这意味着整套系统可以作为一个 npm 包安装到任何项目。这是 Orchestrator 目前没有的分发能力。

### 4. Observation → Instinct → Evolution 的学习闭环
这是 ECC 最独特的架构设计。hook 层是"眼睛"（100% 观察），分析层是"大脑"（后台 Haiku 提取模式），instinct 层是"肌肉记忆"（原子行为+置信度），evolution 层是"成长"（聚类→技能/命令/Agent）。整个闭环是自动的。

### 5. 跨 IDE 的 Source-of-Truth 模型
根目录是 canonical，各 IDE surface 是 projection。变更先在根目录做，然后显式同步到各 surface。instincts YAML 里甚至有 `source_repo` 字段追踪来源。

---

## 建议实施路径

### Phase 1（本周可做）
1. **Config Protection Hook** — 最小改动，在 guard.sh 中加入对 `.eslintrc`、`.prettierrc`、`ruff.toml` 等配置文件的修改拦截
2. **Session Save Format** — 把 ECC 的 8 节会话存档格式适配到我们的 /remember skill，作为 session handoff 模板
3. **Strategic Compact 决策表** — 加入到 compact template 中，告诉用户什么时候该/不该压缩

### Phase 2（本月可做）
4. **Run-With-Flags Hook Runner** — 给 guard.sh/audit.sh 加入 flag 分级（minimal/standard/strict），通过环境变量控制
5. **Santa Loop 跨模型审查** — 增强中书省审议系统，加入 GPT/Gemini 作为"异见审查者"
6. **Post-Edit Accumulator** — 把 format/lint 检查改为累积-批处理模式

### Phase 3（下月规划）
7. **Instinct-Based Learning** — 最大的偷师项目：hook 自动捕获 → observations.jsonl → 后台分析 → 置信度本能 → 进化管道
8. **PRP Pipeline 中的 Mandatory Reading + Patterns to Mirror** — 强化 plan_template.md，要求列出必读文件和要镜像的代码模式
9. **MCP Health Check** — 给 MCP server 加健康检查，失败后标记不健康避免盲目重试

---

## 关键差异总结

| 维度 | Orchestrator | ECC | 偷师方向 |
|------|-------------|-----|---------|
| 身份系统 | SOUL 灵魂（深度人设） | identity.json（浅层配置） | 我们更深，保持 |
| 学习机制 | 手动记忆 | 自动本能+进化 | 偷 ECC 的自动化 |
| Hook 系统 | guard.sh/audit.sh | 20+ 个分级 hook | 偷分级控制 |
| 审查系统 | 中书省单模型 | Santa Loop 跨模型 | 偷跨模型审查 |
| 计划模板 | plan_template.md | PRP 6 阶段 | 偷 Mandatory Reading + Patterns to Mirror |
| 部署方式 | Docker 容器 | npm 插件 | 各有所长 |
| IDE 支持 | Claude Code only | 6 个 IDE | 暂不需要 |
| 控制面 | Node.js dashboard | Rust TUI | 偷 session resume + cost budget |
| 压缩策略 | 9-section template | 战略性压缩决策表 | 偷决策引导 |
| 配置保护 | Gate Functions | Config Protection Hook | 偷精准拦截 |
