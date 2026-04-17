# R79 — Zubayer Multi-Agent Research System Skill Steal Report

**Source**: https://github.com/zubayer0077/Claude-Multi-Agent-Research-System-Skill | **Stars**: unknown (~single-digit) | **License**: Apache-2.0
**Date**: 2026-04-17 | **Category**: Skill-System

## TL;DR

两套 Claude Code Skill（`multi-agent-researcher` + `spec-workflow-orchestrator`）用 **allowed-tools 排除 Write** 做物理级架构护栏，强迫 orchestrator 必须 delegate 给 report-writer agent，而不是靠提示词"请 delegate"。加上一个 **keyword+regex+compound-detection** 三段式 UserPromptSubmit hook，在用户输入进入模型之前就路由到正确 skill。值得偷的不是多 agent 研究流程本身（我们已有），而是"提示词指令从软变硬"的落地手法，和"Research vs Plan 复合意图辨析"的正则矩阵。

## Architecture Overview

四层结构：

| Layer | Components | 作用 |
|-------|-----------|------|
| **Layer 1 — Skill Definition (物理护栏层)** | `SKILL.md` frontmatter `allowed-tools: Task, Read, Glob, TodoWrite`（排除 Write）| 硬约束：orchestrator 本身没有 Write 工具 → 合成阶段不得不 spawn report-writer agent |
| **Layer 2 — Agent Definition (分工层)** | `researcher.md`、`spec-analyst.md`、`spec-architect.md`、`spec-planner.md`、`report-writer.md` | 每个 agent 独立 `tools:` 白名单 + 独立模型指定（`model: sonnet`）+ 输出契约（固定 Markdown 模板） |
| **Layer 3 — Routing & Guardrail (Hook 层)** | `hooks/user-prompt-submit.py` + `skills/skill-rules.json` | UserPromptSubmit 时跑 regex + keyword + compound 检测 → 注入 `<system-reminder>` 强制激活 skill；PostToolUse 跟踪 Write 路径、校验质量门 |
| **Layer 4 — State & Utils (编排层)** | `utils/workflow_state.sh` (shell JSON state)、`utils/state_manager.py` (skill tracking)、`utils/archive_project.sh`、`utils/detect_next_version.sh` | 小文件 state (`current.json` 只存当前态) + 历史 session 分文件，避免 state 膨胀 |

## Six-Dimensional Scan

### Security / Governance — **Novel**

- **工具权限即护栏（Physical Enforcement）**：`multi-agent-researcher` 的 frontmatter `allowed-tools: Task, Read, Glob, TodoWrite` 明确不包含 Write。SKILL.md 里写"⚠️ YOU DO NOT HAVE WRITE TOOL ACCESS"并不是提示词吓唬，是 Claude Code runtime 真的不会给它 Write 权限。这是把"请务必 delegate 给 report-writer"从**软 prompt 约束**升级成**硬工具约束**的干净范例。
- **PostToolUse 违规检测 + 审计日志**：如果运行时真绕过了（比如 orchestrator 通过某种方式写了 report），`post-tool-use-track-research.py` 会检测文件路径归属 → 记录为"工作流违规"并写入 state。
- **UserPromptSubmit 预审**：settings.json `permissions.allow` 只白名单了 4 个域名的 WebFetch，其余默认 ask/block。

### Memory / Learning — **Covered**

- 只有 workflow state（project_slug / mode / user_input / timestamp）和 session_logger。没有跨会话知识沉淀、没有去重、没有时间加权压缩。
- skill tracking (`state_manager.py`) 用 `currentSkill / invocationNumber / endTime / trigger` 记录技能调用序列，但只追踪"谁在跑"，没有质量/效果评估。

### Execution / Orchestration — **Novel (部分)**

- **Sequential Planning Pipeline**：`spec-analyst → spec-architect → spec-planner`，每步输出固定路径的 Markdown，下一步必须读上一步的产物。**非并行**（刻意的，因为依赖链清晰）。
- **Parallel Research Pipeline**：`multi-agent-researcher` 则强制"同一条消息里 spawn 所有 researcher"（非序列）。
- **AskUserQuestion 三态分叉（已有项目处理）**：检测到 `docs/projects/{slug}/` 已存在 → 弹 AskUserQuestion 四选项（Refine / Archive + Fresh / Create v2 / Cancel），每个分支走不同的 shell 脚本。这是 Skill 把"已有数据冲突"这个常见尴尬点显式化的好例子。
- **版本号自动探测**：`detect_next_version.sh` 遍历 v2..v99 找第一个空位，到 v99 就报错提示用户改用 Archive。

### Context / Budget — **N/A**

- 没有 token 预算分配、没有中间产物瘦身、没有 artifact externalization。研究笔记 800-1500 行、架构文档 600-1000 行全走 Markdown 堆。
- **na_reason**: 项目明确瞄准"描述型 workflow 编排"，不在上下文预算层面做文章。

### Failure / Recovery — **Novel (部分)**

- **Quality Gate 迭代回环（最多 3 轮）**：打分 < 85% → 分析失败归因（哪个分项丢分最多） → **定点 respawn 对应 agent**（spec-analyst 丢分 → 只重跑 analyst，不全盘重来）+ 把失败反馈作为新 prompt 的一部分。3 轮仍不过 → 升级用户决策。
- **Archive 流程的事务性**：`archive_project.sh` 先 `cp` → 校验文件数一致 → 才 `rm -rf` 原件；`cp` 失败会 `rm -rf "$ARCHIVE_DIR"` 回滚。Shell 脚本里罕见地讲原子性。
- Doom loop 检测、级联错误分类学没有。

### Quality / Review — **Novel (部分)**

- **4-Criteria Weighted Scoring (100pt, 85% 通过)**：Requirements 30pt / Architecture 30pt / Tasks 25pt / Risk 15pt，每条再细分为 5-10pt 的子项（"NFR 必须带定量指标"之类）。这是我们现在靠 verification-gate 自然语言检查的量化版。
- **Architectural Enforcement 反套路**：合成阶段的质量门不是"检查输出好不好"，而是"检查**谁**输出的"——synthesisPhase.agent 必须 === 'report-writer'，否则视为违规，哪怕内容再好。这个"who did it" 门在我们的审计体系里没见过。

## Path Dependency

- **locking_decisions**：
  - 选了 `allowed-tools` 作为护栏机制 → 整个项目的"质量保证"从此绑死在 Claude Code 的权限模型上；换平台（Codex、Cursor）就失效。
  - `skill-rules.json` 用正则关键词列表（30+ 条 keywords、20+ 条 intentPatterns），维护成本随新场景线性增长，不具可扩展性。
- **missed_forks**：
  - 本可以用 LLM classifier（轻量模型判断 intent）代替正则；作者选了正则，速度快但维护地狱。
  - 本可以把 workflow_state 存进 SQLite / 单个 JSON 加锁；选了每步重写整个文件的 shell 脚本，并发会冲突。
- **self_reinforcement**：作者 HONEST_REVIEW.md 自己承认 "Implementation 2/10，只有文档没有实现"——一旦架构蓝图够详细，后续 PR 只要"补一个脚本"就显得合理，但整体抽象成本已经锁死。
- **lesson_for_us**：**偷"allowed-tools 做护栏"这个 chosen path**；**避开"正则+关键词大列表"这个 lock-in trap**——我们要做 intent 路由应该走 prompt → classifier → tool 的结构，而不是堆 regex。

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **1. allowed-tools 作为物理级护栏** | SKILL.md frontmatter 明确排除某些工具（Write/Edit/Bash），Claude Code runtime 物理阻断；SKILL.md 里只需写一条"你没有 X 工具"即可代替 N 段"请务必 delegate"。源码见 `.claude/skills/multi-agent-researcher/SKILL.md:1-6`。 | 我们所有 skill 都用全量工具，没有一个带 `allowed-tools:`（grep 验证：`No files found`）。所以所有"请 delegate"约束都只是 prompt 软约束，随时可被"rationalization immunity"列出的借口绕过。 | 先给 3 个高风险 skill 加 allowed-tools：①`steal` 合成阶段限 Task+Read+Write（不给 Edit，防止边偷边改主仓）；②`verification-gate` 限 Read+Bash+Glob（不给 Write/Edit，强制"只读审计"这个定位）；③`adversarial-dev` 限 Task+Read（不给 Write/Edit/Bash，强制走子代理执行）。每个 skill 约 10 分钟。 | ~1h |
| **2. Quality Gate 量化 4-weight 阈值 + 归因 respawn** | 100 分 = 30/30/25/15 四维打分；不过线（<85%）时不是"重跑所有 agent"，而是**定位哪一维丢分 → 只 respawn 负责该维的 agent + 把失败条目作为反馈注入 prompt**。最多 3 轮，再不过升级用户。源码见 `.claude/skills/spec-workflow-orchestrator/SKILL.md:515-585`。 | 我们的 verification-gate 是"五步证据链"自然语言判断，没有权重、没有归因、没有 respawn 策略。plan_template.md 要求 atomic steps 但没要求量化每步验证。 | 改 `SOUL/public/prompts/plan_template.md` 增加 "Quality Weights" 字段（默认四维：correctness 40 / style 20 / scope 25 / evidence 15，可项目覆盖）；给 verification-gate skill 加一节 "Failure Attribution"：失败时必须指出哪一维<阈值、对应哪个文件/步骤、respawn 谁。 | ~2h |
| **3. UserPromptSubmit hook 做意图路由 + 复合检测** | 三层决策：①**否定检测**（"don't research"、"skip planning"）→ 屏蔽对应 skill；②**复合名词**（"build a search tool"）→ 判为单一 planning action，而非 research+build；③**真复合**（"research X then build Y"）→ 触发 AskUserQuestion 让用户二选一。源码见 `.claude/hooks/user-prompt-submit.py:31-120, 323-481`。 | 我们只有 `dispatch-gate.sh` 做 STEAL 分支防护。skill 路由靠 `SOUL/public/prompts/skill_routing.md`（软引导），没有 prompt-level hook 强制。且从没区分过"build a research tool"是 research 还是 build。 | 写一个轻量 `.claude/hooks/intent-router.py`：不学这个项目的 30+ 关键词正则（lock-in trap），而是用小的 prompt 调一个 haiku-4.5 做 intent 分类，输出 `{primary_skill, is_compound, confidence}`；compound 时用 AskUserQuestion 让用户澄清。不替代 skill_routing.md，做它的前置筛网。 | ~4h（含 haiku 调用成本测试） |

### P1 — Worth Doing (3 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **AskUserQuestion 三态分叉（已有数据处理）** | 检测到目标目录已存在时，用 AskUserQuestion 弹 Refine/Archive/NewVersion/Cancel 四选项，每分支独立脚本。比"自动覆盖"和"直接报错停住"都体面。 | 给 `steal` skill 加一段：写 `docs/steal/<date>-<topic>-steal.md` 前若已存在 → 弹 AskUserQuestion：①合并到现有报告 ②归档到 `.trash/` 新建 ③重命名为 -v2 ④取消。**但用户已有 dedup_matrix.md 管这事，只在冲突时复用它。** | ~1.5h |
| **Archive 脚本的事务性写法** | `cp → 校验文件数 → rm 原件`，中间失败就 `rm -rf ARCHIVE_DIR` 回滚。Shell 脚本里把事务性做得干净。源码 `.claude/utils/archive_project.sh:48-118`。 | 把这个模式抄进 `.trash/` 迁移流程——当 steal/verification 产物要移到 `.trash/` 时，先 cp 校验 → 再 rm，中途失败回滚。改 `SOUL/public/prompts/plan_template.md` 的 "Deletion = Move to .trash/" 段落，加一行"使用 mv 之前先 cp 校验，或用 git 暂存兜底"。 | ~1h |
| **Current-vs-History state 分离** | `current.json` 只存当前态（极小、永不膨胀），历史数据按 session 分文件（`session_*_state.json`）。读 current 是 O(1)，历史数据按需加载。源码 `.claude/utils/state_manager.py:20-90`。 | 我们 `.remember/` 是 `now.md`（buffer）+ `today-*.md`（按天）+ `recent.md`（7d）+ `archive.md`——**已经是这个模式**。但我们的 context pack 编译（learnings.md 37938 chars）是一次性全读的，可以借鉴 "current 极小 / 历史分片按需" 给 context pack 瘦身。 | ~3h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Keyword + IntentPatterns 正则路由表** | skill-rules.json 列 30+ keywords、20+ intentPatterns 做路由判断 | 维护成本随场景数线性增长，作者自己 lock-in 了；我们走 LLM classifier 更合适（见 P0 pattern 3） |
| **Placeholder Substitution 流程（Step 1.6）** | 显式说明 `[PROJECT_NAME]` / `[ADDITIONAL_REQUIREMENTS_FROM_USER]` 在 spawn agent 前替换 | 我们 agent prompt 已经是模板字符串 + Python f-string 动态拼接，没这个问题 |
| **quality-gates.ts（TypeScript 验证器）** | 一个 TS 模块做 existsSync 校验 + GateResult 返回结构 | 孤儿文件——hook 是 Python，这 TS 文件没任何 import，作者自己 HONEST_REVIEW 也没提它被谁调用。是 aspirational code，偷不来 |

## Triple Validation & Knowledge Irreplaceability (P0 patterns)

### P0-1: allowed-tools 物理护栏

| Check | Pass | Evidence |
|-------|------|----------|
| Cross-domain reproduction | ✅ | Claudeception（R20+ 偷过）也用 `tools:` 白名单做分工边界；Codex CLI 的 `--approval-mode` 是同类思想的 CLI 版本；我们自己的 hooks/block-protect 也是"物理阻断优于提示"的独立再发明 |
| Generative power | ✅ | 新场景："希望某 agent 只读审计不写文件" → 立刻知道该用 allowed-tools 排除 Write/Edit，不必再写 N 段 prompt |
| Exclusivity | ✅ | 不是通用 best practice——绝大多数 Claude Code skill（翻了我们 15 个 skill 0 个用）都没用这招 |
| **Score** | **3/3** | 高置信 P0 |

**Knowledge irreplaceability**: hidden_context（SKILL.md frontmatter `allowed-tools` 这个机制很多文档没强调，属于"知道的人才知道"的部落知识）+ judgment_heuristics（"prompt 约束 vs 工具权限约束"的决策直觉）+ unique_behavioral_patterns（用工具白名单代替 delegate prompt 的反套路）→ **3 categories，P0 confirmed**

### P0-2: 量化 Quality Gate

| Check | Pass | Evidence |
|-------|------|----------|
| Cross-domain reproduction | ✅ | Pytest coverage 阈值、Codex 的 max-iters、DeerFlow 的 quality_score 都是同类思想；DevFlow 项目被本项目 `quality-gates.ts` 显式引用为灵感源 |
| Generative power | ✅ | 新任务："重构复杂度降 30%" → 直接 30/30/25/15 权重分给 correctness / tests / readability / scope，失败时按权重归因 |
| Exclusivity | ⚠️ | 量化打分本身是 generic，但"归因 + 定点 respawn"这个组合有 specific twist（迭代上限 3 是 threshold choice） |
| **Score** | **2/3** | P0 with caveat——打分机制本身可能被视为通用；归因 respawn 才是独有 |

**Knowledge irreplaceability**: pitfall_memory（全量 respawn 是常见错误，本项目走过才给出定点 respawn）+ judgment_heuristics（权重分配比例 30/30/25/15 是 calibrated choice，不是从零推导）→ **2 categories，P0** （边界）

### P0-3: Intent Router Hook

| Check | Pass | Evidence |
|-------|------|----------|
| Cross-domain reproduction | ✅ | Claude-Flow / claude-agent-sdk-demos 都用类似 UserPromptSubmit hook；我们 dispatch-gate 是独立的同类实现 |
| Generative power | ✅ | 可预测："如果用户说 'debug X'" → intent-router 判为 systematic-debugging skill，自动注入 reminder；复合意图触发 AskUserQuestion |
| Exclusivity | ✅ | 特别之处是 **compound detection 的三类正则矩阵**（TRUE / FALSE / NOUN），不是简单的 keyword 匹配——在 Claude Code 生态里罕见 |
| **Score** | **3/3** | 高置信 P0（但偷 pattern 时替换实现：用 LLM classifier 代替 regex） |

**Knowledge irreplaceability**: hidden_context（UserPromptSubmit hook 能在模型看到之前改提示，很多人不知道）+ pitfall_memory（作者明显踩过"build a search tool → 误判为 research+build 复合"的坑，才有 COMPOUND_NOUN_PATTERNS 专门分支）+ judgment_heuristics（Strong+Strong 才问用户、Strong+Weak 直接选 Strong）→ **3 categories，P0 confirmed**

## Comparison Matrix (P0 patterns)

### P0-1: allowed-tools 物理护栏

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| SKILL.md 声明工具白名单 | `allowed-tools: Task, Read, Glob, TodoWrite` frontmatter | 无任何 skill 使用 allowed-tools | Large | Steal |
| Runtime 阻断 Write | Claude Code 按 frontmatter 拒绝工具调用 | 全工具开放 | Large | Steal |
| Prompt 说明"你没有 X 工具" | SKILL.md 明写 "YOU DO NOT HAVE WRITE TOOL ACCESS" | 无 | Medium | Steal (配合硬约束) |
| 违规后的 PostToolUse 审计 | `post-tool-use-track-research.py` 路径归属 + 工作流违规日志 | dispatch-gate.sh 有 branch gate 但无 per-skill tool audit | Medium | Enhance |

### P0-2: 量化 Quality Gate

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 维度权重声明 | Requirements 30 / Architecture 30 / Tasks 25 / Risk 15 | plan_template.md 列验证步骤但无权重 | Large | Steal |
| 子项明细拆分 | 每个大项拆 3-4 个子 check（每 5-10pt） | 自然语言描述 | Medium | Steal |
| 失败归因 → 定点 respawn | 把 <85% 细分到哪一维丢分最多 → 只重跑对应 agent + 注入 diff | verification-gate 只报告失败，不触发 respawn | Large | Steal |
| 迭代上限 | max 3 iterations，满了升级用户 | 无上限（靠 loop-detector hook 兜底） | Small | Enhance |

### P0-3: Intent Router Hook

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| Prompt 级 skill 路由 | UserPromptSubmit hook 注入 `<system-reminder>` 强制 | 无 hook，靠 skill_routing.md 被动读 | Large | Steal (但用 LLM 不用 regex) |
| 否定意图过滤 | NEGATION_PATTERNS 正则 | 无 | Medium | Skip（LLM classifier 原生支持） |
| 复合意图辨析 | TRUE_COMPOUND / FALSE_COMPOUND / COMPOUND_NOUN 三类正则 | 无 | Large | Steal（LLM classifier 输出 is_compound 字段即可） |
| Compound 触发 AskUserQuestion | build_compound_clarification_message 构建选项 | 无 | Medium | Steal |

## Gaps Identified

| Dimension | Their coverage | Our coverage | Gap size |
|-----------|---------------|--------------|----------|
| Security/Governance | 物理工具护栏 + 路径归属审计 | 分支防护 + 3-state config 保护 + guard-redflags | Medium（他们有 skill-level tool gate，我们没有） |
| Memory/Learning | 仅 session state，无跨会话学习 | .remember/ 五层结构 + evidence tier + core-memories | None（我们明显更深） |
| Execution/Orchestration | 3 分工 agent + 85% gate + respawn | 多 skill + subagent 模式 + plan_template.md | Small（我们缺的是"量化 gate + 归因 respawn"，其他更强） |
| Context/Budget | 无 | context pack 编译 + 5 分钟缓存感知 | None |
| Failure/Recovery | Archive 事务 + 3-iter upper bound | loop-detector + systematic-debugging | Small（Archive 事务范式可偷） |
| Quality/Review | 4-weight 量化 + "who did it" gate | verification-gate 五步证据链 | Medium（量化维度缺，定位者维度缺） |

## Adjacent Discoveries

- **"Agent 自行写审查反而质量更低"的架构论证**：SKILL.md 第 96-109 行明示 "YOU DO NOT HAVE WRITE TOOL ACCESS"，逻辑是"orchestrator 的职责是协调不是执行，让它写 report 会导致 **plan dissolution**（计划消解，orchestrator 一边协调一边执行会丢失两边的专业性）"。这个概念和我们 R42 "editable vs fixed zones" 有共鸣——**agent 的自我修改边界**和**agent 的自我执行边界**是一回事。
- **"Tools as Contract"**：把 agent 的 `tools:` 和 skill 的 `allowed-tools:` 当成 API 契约来用，而不是能力开关。Claudeception 偷师（R20+）里 "meta-agent 自己编辑 tool list" 是同类思想的进阶版。
- **`AskUserQuestion` 作为第一公民**：这个项目把 AskUserQuestion 用在三态分叉和 compound clarification 两处——都是"默认行为会犯错，让用户做选择"的标准用法。我们 AskUserQuestion 用得很少（主要靠 brutal honesty + 直接执行），但在这两个场景确实该用。

## Meta Insights

1. **护栏从软到硬的三阶演进**：`prompt 里写"请务必 X"` → `hook 在外层拦截` → `runtime 从工具白名单物理阻断`。这个项目把第三阶做出来了（`allowed-tools`），但我们连第二阶的 hook 覆盖都还不完整。核心洞察是：**只要允许模型自己决定是否调工具，就别指望 prompt 说服它不调**。
2. **"设计蓝图 vs 可执行实现"的诚实度可以是项目优点**：作者写的 HONEST_REVIEW.md 给自己打 "Implementation 2/10"，明确说"这是设计文档不是生产代码"。偷师对象能自我审查反而让偷起来更精准——知道什么能偷（架构决策）、什么不能偷（TypeScript 孤儿文件、复杂 regex lock-in）。我们的 steal report 也该保留这种"评估目标诚实度"的判断（不是所有 stars 高的项目都值得深挖）。
3. **量化 gate 的真正价值是"归因 respawn"，不是打分**：打个 68/100 的数字谁都能做，关键是"丢分集中在 Requirements 下的 NFR 指标那 5 分 → 所以只重跑 spec-analyst 并在 prompt 里明说'上次 NFR 缺定量指标'"。我们的 verification-gate 现在给的反馈是"这里不对，修一下"，缺的正是"精确定位 + 定点 respawn"这环。
4. **正则路由是 lock-in trap，该早期就设 budget**：30+ keywords 现在管用，到 100+ 就是维护地狱，到 300+ 开始互相矛盾。偷这个模式时应该直接跳过正则表，用 LLM classifier。"早期技术决策锁死晚期可扩展性"是 R58 HV 分析的典型案例。
