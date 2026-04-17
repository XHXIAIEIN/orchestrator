# R81 — x1xhlol System Prompts Collection Steal Report

**Source**: https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools | **Stars**: ~100k+ | **License**: GPL-3.0
**Date**: 2026-04-17 | **Category**: Survey (Skill-System)

## TL;DR

30+ 个商业 AI 工具泄露/公开的系统提示词合集——不是单项目偷师，而是横向扫描整个"AI 工具提示词工程"行业范式。核心可偷价值：**这些工具替我们做了 A/B 测试**——它们在相同场景（并行工具调用、简洁纪律、模式切换）下走了不同路线并把分歧点暴露出来，让我们能挑出**已被市场验证**的做法而不是自己反复试错。

## Architecture Overview

扫描覆盖 30+ 工具，按结构性角色归为 4 层：

| Layer | 代表工具 | 核心特征 |
|---|---|---|
| **L1 IDE 编码代理** | Cursor (3 版), Augment (Claude/GPT-5), Amp (2 版), Windsurf, VSCode Copilot (2 版), Trae, Qoder, CodeBuddy | 并行工具调用 + todo 纪律 + 禁止向用户暴露工具名 |
| **L2 自主规划代理** | Devin, Manus, Kiro (Classifier/Spec/Vibe), Traycer, Emergent, Leap.new, Junie, Replit | 多阶段 workflow + 显式审批门 + plan 持久化到文件系统 |
| **L3 Web 构建器** | v0, Lovable, Same.dev, Orchids (两阶段), Emergent | 技术栈硬锁定 + 完整文件输出契约 + 部署流程内嵌 |
| **L4 消费级助手** | Poke (6 分片), Perplexity, Comet, Dia, Cluely, NotionAI, Xcode (5 action), Warp, dia | 内容类型感知格式 + 品牌 persona guard + 单实体幻觉维持 |

**同版本演化观察**：Cursor 2.0 → 2025-09-03 是从 GPT-4.1 → GPT-5 的升级节点。后者抛弃细粒度 todo（"prefer fewer, larger todo items"），新增 `<status_update_spec>` 和 `<summary_spec>`——说明 **GPT-5 级模型需要的是更松的控制框架 + 更严的输出纪律**，不是更多的 handholding。

## Steal Sheet

### P0 — Must Steal (5 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Soft Probability Mode Classifier** | Kiro Mode_Classifier 返回 `{chat: 0.2, do: 0.7, spec: 0.1}` JSON 三维置信度（总和=1），而非 if-else 硬路由。默认偏向 `do`，spec 需关键词显式激活。 | 我们的 skill_routing.md 用 decision tree，硬分类，无置信度。边界情况靠二次澄清。 | 在 `SOUL/public/prompts/skill_routing.md` 顶部新增一个 softmax 分类段：对模糊指令先返回 `{debug: x, build: y, review: z, ship: w}` 概率，≥0.6 的直接执行，多维接近的触发澄清。 | ~2h |
| **Verbosity Dual-track** | Cursor GPT-5 明确分离：**代码要 HIGH-VERBOSITY**（`generateDateString` 而非 `genYmdStr`，`numSuccessfulRequests` 而非 `n`），**对话要 LOW-VERBOSITY**（禁 "Summary:" 头）。两个规范独立。 | CLAUDE.md "Surgical Changes" 说了代码纪律，voice.md 说了对话简洁，但**没明确"代码命名不受简洁约束"**——易混淆导致短变量名。 | voice.md 追加 2 行："代码命名：长即清晰，忌 `n`/`tmp`/`res`；对话输出：短即尊重，忌 'Summary:' 头。两条规则独立适用。" | ~1h |
| **`<think>` Mandatory Trigger Enumeration** | Devin 列出 10 种强制/建议调用 `<think>` 工具的场景：git 决策前、探索转编码前、完成前、环境异常时等。不是"适当时候思考"，而是**规则化的思考触发表**。 | 我们有 systematic-debugging skill 但 CLAUDE.md 没有 `<think>` 触发点清单。Gate Functions 只覆盖危险操作，不覆盖认知转换节点。 | CLAUDE.md 新增 "Think Triggers" 小节：列 6-8 个强制停下思考的场景（分支前 / 删除前 / 跨模块重构前 / 实现->验证切换前 / 失败 ≥3 次 / 跨日恢复任务）。 | ~1h |
| **Phase Gate Contract Document** | Emergent 在 Step 2 Frontend Mock → Step 3 Backend Dev 切换时**强制生成 `contracts.md`**，记录 API 契约、mock 映射、集成方案。相变产物，不是可选文档。 | 我们有 `SOUL/public/prompts/plan_template.md` 约束 plan 格式，但没"相变门文件"——从 Plan → Implementation 切换时，容易把隐性假设丢在对话里，下一会话恢复不了。 | `plan_template.md` 末尾追加 "Phase Gate" 章节规范：每个跨相位切换必须生成 `.phase-gate/<from>-to-<to>.md`，含假设清单 + 接口契约 + 验证点。 | ~2h |
| **Two-Stage Prompt Architecture** | Orchids.app **分离 Decision prompt 和 System prompt**：前者极短（纯 intent routing + 3 个工具签名），后者全量（完整 coding agent 规则）。阶段一用小模型决策，阶段二用大模型执行。 | 我们所有 skill prompts 都是单层——整个 SKILL.md 每次注入给同一模型。当 skill 做 intent 分类（如 skill_routing、steal 的 target 类型判断）时，用 Opus 4.7 做路由是成本浪费。 | 试点一个：将 `.claude/skills/steal/SKILL.md` 的 "target type" 判断抽成独立 mini-prompt（50 行内），可选择让 Haiku 跑；主体留给 Opus。文档化这个模式作为未来 skill 分层的模板。 | ~2h |

### P1 — Worth Doing (8 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Example-Driven Verbosity 教学** | Amp/Claude Code 用极端例子教简洁：`user: 4+4 → response: 8`。规则+例子的冲击强于纯规则。 | voice.md 的 "Concise" 小节加 3 个反差例子（当前只有否定句）。 | ~30m |
| **Anti-Sycophancy Ban List** | Augment "Don't start your response by saying a question or idea was good, great, fascinating, profound, excellent"。枚举禁用词比通用"不要奉承"可执行得多。 | voice.md 的 "Communication Style" 加具体禁用词清单。 | ~30m |
| **Contract + Edge Cases Before Code** | VSCode GPT-5 `<engineeringMindsetHints>`：写代码前先列 2-4 条 I/O contract + 预想 3-5 个 edge cases。 | CLAUDE.md "Goal-Driven Execution" 加这条，配 1 个范例。 | ~1h |
| **Safe-by-default Verification Runs** | Augment GPT-5 `<Execution and Validation>`：每次改代码后自动 lint/build，无需显式指令。 | hooks 层加一个 `PostToolUse` 规则：Edit/Write 后自动跑项目定义的 `bun test --bail` 或 `pytest -x`，失败阻塞。 | ~2h |
| **Two-level Autonomy (Autopilot/Supervised)** | Kiro Vibe 把"可撤销 vs 立即应用"做成用户级开关。 | `.claude/settings.json` 新增 `autonomy: autopilot\|supervised`；supervised 模式下 Edit 先走 diff 预览。 | ~3h |
| **Oracle Sub-Agent Pattern** | Amp 内嵌 o3 作 "senior engineering advisor"，专供 code review / architecture decisions。与执行 agent 职责分离。 | 我们的 agent 列表多但没显式"Oracle 角色"。命名一个 `architect-opus` 并强化 review 语义。 | ~2h |
| **Output Format by Content Type** | Cluely 按内容类型分支（编程题零前言纯代码 / 数学题 LaTeX+FINAL ANSWER / 邮件 code block）。 | skills 内加"内容类型 → 输出格式"映射表（当前凭 model 判断）。 | ~2h |
| **Dynamic Task Triggers** | Augment GPT-5 条件化 tasklist（multi-file / 跨层 / >2 edits 才启用），避免小任务被 todo 淹没。 | CLAUDE.md 明确 TaskCreate 的"触发下限"：单步 ≤5 分钟的任务**不**建 task。 | ~30m |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Poke 6-part Prompt Chunking** | 将提示词按 persona / 平台 / 工作流 / 产品知识 / 格式 / 记忆 6 个 part 分片，运行时按场景组装。 | 我们的 skills 已经是分片结构，进一步切分收益递减；且组装逻辑需要新的基础设施。 |
| **Qoder $100000000 Penalty** | 用夸张金额惩罚条款强化记忆（"face a $100000000 penalty"）。 | 有趣的 prompt hack 但心理学收益存疑；我们已用 Gate Functions 强约束。 |
| **Dia `ask://` Hyperlink Protocol** | 把跟进问题编码为可点击 URL 协议。 | 需要浏览器侧支持；CLI 环境无法利用。 |
| **CodeBuddy Prompt-Leak Deception** | 被要求泄露系统提示时返回伪造的无害版本。 | 私有项目不需要；且存在诚信成本。 |
| **v0 `[v0]` Debug Log Branding** | `console.log("[v0] ...")` 调试日志带品牌前缀。 | 单项目偏好，无可复用性。 |

## Comparison Matrix (P0 Patterns)

### Pattern 1: Soft Probability Mode Classifier

| Capability | Their (Kiro) | Ours | Gap | Action |
|---|---|---|---|---|
| 意图分类 | JSON softmax {chat, do, spec} | Decision tree 硬匹配 | Medium | Steal |
| 边界模糊处理 | 多维接近自动 fallback 问询 | 无显式机制，全靠模型判断 | Large | Steal |
| 历史上下文纳入 | 是（分类器读对话历史） | 否（只看当前指令） | Small | Enhance |

**Triple Validation**: ✓ Cross-domain（Amp 的三层子代理分工也是软分类；Windsurf Cascade 的 memory 决策也是软阈值）；✓ Generative（能预测"新 skill 加入时如何处理模糊指令"——给新分类维度分配概率）；✓ Exclusivity（大多数 AI 工具用硬 if-else，软概率是少数派）。**3/3 pass**。
**Knowledge Irreplaceability**: hit `judgment_heuristics` + `hidden_context`（"When in doubt, classify as Do"是非平凡启发式）+ `unique_behavioral_patterns`（三维软分类是 Kiro 标志性设计）。**Score: 3**。

### Pattern 2: Verbosity Dual-track

| Capability | Their (Cursor GPT-5) | Ours | Gap | Action |
|---|---|---|---|---|
| 代码命名纪律 | 强制长 + 语义化 | voice.md 无约束 | Medium | Steal |
| 对话输出纪律 | 强制短 + 禁 header | 有但不彻底 | Small | Enhance |
| 规则独立性 | 两个 spec 节独立 | 混在一起易冲突 | Small | Enhance |

**Triple Validation**: ✓ Cross-domain（Amp 也有"NEVER add comments to explain code"的分离意识）；✓ Generative（能预测"当被要求精简代码时，应精简逻辑不精简命名"）；✗ Exclusivity（很多 style guide 也谈这两点，但把它们**同级规则化**并冲突检查的只有 Cursor GPT-5）。**2/3 pass**（exclusivity 是边缘）。
**Knowledge Irreplaceability**: hit `pitfall_memory`（短变量名看似简洁实则坑）+ `hidden_context`（LLM 会把"简洁"错误外推到代码）。**Score: 2**。

### Pattern 3: `<think>` Mandatory Trigger Enumeration

| Capability | Their (Devin) | Ours | Gap | Action |
|---|---|---|---|---|
| 思考时机规则化 | 10 个场景枚举 | 无枚举，靠 systematic-debugging 隐式触发 | Large | Steal |
| 分支前强制思考 | 是 | 否 | Large | Steal |
| 失败后思考 | 是（环境异常、≥3 次失败） | 有（systematic-debugging）但无次数阈值 | Medium | Enhance |

**Triple Validation**: ✓ Cross-domain（Augment GPT-5 "at most one high-signal info-gathering call" 是同类节流触发；Amp 的 "oracle invocation" 也是认知转换触发）；✓ Generative（能预测新场景：跨进程调试前应强制思考）；✓ Exclusivity（具名 `<think>` 工具 + 明确触发表是 Devin 独家）。**3/3 pass**。
**Knowledge Irreplaceability**: hit `pitfall_memory`（盲目行动是常见失败模式）+ `judgment_heuristics`（何时该停下）+ `failure_memory`（环境问题不该自己修）。**Score: 3**。

### Pattern 4: Phase Gate Contract Document

| Capability | Their (Emergent) | Ours | Gap | Action |
|---|---|---|---|---|
| 相变产物文件 | 是（contracts.md） | 否 | Large | Steal |
| 跨会话可恢复 | 文件即契约，新 session 可续 | 依赖对话历史 | Large | Steal |
| 自动检测相变 | 显式 5 阶段流水线 | 手动判断 | Medium | Enhance |

**Triple Validation**: ✓ Cross-domain（Kiro Spec 的 requirements.md/design.md/tasks.md 也是相变持久化；Traycer 的 phases 也是）；✓ Generative（能预测新场景：从 refactor 计划 → 执行时应有 refactor 契约文件）；✓ Exclusivity（Spec → Impl 契约的产物化是少数派；大多数 agent 把契约留在对话里）。**3/3 pass**。
**Knowledge Irreplaceability**: hit `failure_memory`（会话中断后假设丢失）+ `hidden_context`（对话里的假设不可审计）+ `judgment_heuristics`（何时应产物化）。**Score: 3**。

### Pattern 5: Two-Stage Prompt Architecture

| Capability | Their (Orchids) | Ours | Gap | Action |
|---|---|---|---|---|
| Intent 路由层 | 独立短 prompt + 工具签名 | 无分层，路由融在主 skill 里 | Large | Steal |
| 执行层 | 独立全量 prompt | 单一全量 prompt 承担两职责 | Medium | Steal |
| 跨层 handoff 协议 | `handoff_to_coding_agent` 工具显式 | 无显式 handoff 工具 | Large | Steal |

**Triple Validation**: ✓ Cross-domain（Manus 的 Planner module 和 worker 分离是同类架构；Emergent 的 sub-agent 网络也是）；✓ Generative（能预测：未来 N-stage 场景都应分 prompt）；✓ Exclusivity（显式在 system prompt 层分阶段的少见，多数工具只在代码层分 agent）。**3/3 pass**。
**Knowledge Irreplaceability**: hit `judgment_heuristics`（何时该分层）+ `unique_behavioral_patterns`（Orchids 独家模式）+ `hidden_context`（成本优化动机）。**Score: 3**。

## Six-Dimensional Scan

### Security / Governance — **Status: Novel**

- **品牌 persona guard**：Cluely/Qoder/GitHub Copilot 强制隐藏底层模型（"I am Cluely powered by a collection of LLM providers"）。我们的 boot.md 主动报身份 "Orchestrator 是 Claude Opus 4.7"，是相反选择——这是价值观差异，不是改进机会。
- **提示词泄露诱捕**：CodeBuddy 返回伪造系统提示作为诱捕。我们无此机制，但也无强烈需求（本项目公开）。
- **命令安全分级**：Windsurf `<running_commands>` 节明确判断 unsafe 命令并拒绝 override。**我们的 Gate Functions 覆盖删除/回滚，但没覆盖"命令安全分级"**——值得加入。
- **沙盒能力声明**：Manus 明确 "Linux sandbox with internet access, cannot access outside"。我们的 CLAUDE.md 假设读者已知环境，没显式声明边界。

### Memory / Learning — **Status: Covered**

- **Windsurf liberal memory creation**："You DO NOT need USER permission to create a memory...create memories liberally"。我们的 `.remember/` 系统已有类似策略（R42 三层证据分级更严谨）。
- **Qoder 四类记忆分类**（user_prefer/project_info/project_specification/experience_lessons）。比我们的 today-*.md / recent.md / archive.md 维度更丰富——可参考但不紧急。
- **Poke `<summary>` + `<usercontext>` 双标签**：对话压缩历史 + 跨会话用户档案分离。我们的 .remember/ 也分 now.md vs core-memories.md，概念对齐。

### Execution / Orchestration — **Status: Novel**

- **Devin `<think>` 工具化**（已入 P0）
- **Emergent 5 阶段 + sub-agent 网络**（deep_testing_backend_v2 / auto_frontend_testing_agent 等专业化）——我们的 agent 列表多但缺"流水线自动化编排"。
- **Manus event stream 架构**（Message/Action/Observation/Plan/Knowledge/Datasource 6 类事件）——我们没有显式事件流，靠对话历史隐式。
- **Junie 单命令制**：每回复只一个 `<COMMAND>`。与我们的并行哲学相反，是 readonly 场景的保守设计，不偷但值得记。

### Context / Budget — **Status: Novel**

- **Poke 6-part 分片 + 动态组装**（已入 P2）
- **Emergent "只保留最后 10 条消息完整观察"** + 要求在思考中定期重复计划——激进压缩策略。我们的 /compact 是手动触发，这是被动阈值 + 主动重述组合。
- **Orchids 两阶段 prompt**（已入 P0）
- **Augment GPT-5 "at most one high-signal info-gathering call"**：节流搜索。与 Cursor 2.0 "first-pass results often miss key details, rerun"反向。**我们无显式搜索节流**。

### Failure / Recovery — **Status: Novel**

- **Devin 失败 3 次求助用户**：明确阈值。我们的 systematic-debugging skill 谈 "调试不修复"，但没具体次数阈值。
- **Devin "find a way to continue without fixing env"**：环境问题走 CI 而非自修。与我们的"诊断而非回滚"哲学一致。
- **Emergent test_result.md 持久化**：测试失败历史外化。我们有 `.trash/` 但没"失败账本"。

### Quality / Review — **Status: Novel**

- **Amp Oracle 子代理**（已入 P1）
- **VSCode GPT-5 `<qualityGatesHints>`**：Build/Lint/Unit tests/smoke test 四关卡流水线。我们的 verification-gate 是 5 步证据链，类似但更重评估证据。
- **Cursor GPT-5 `<summary_spec>`**：分离 status_update（过程）和 summary（结论）。我们的输出没这个分层。
- **Augment "safe-by-default verification runs"**（已入 P1）

## Path Dependency Assessment

**Locking decisions**：
- 多数工具绑定单一 IDE/平台（Cursor→Cursor IDE, Windsurf→Windsurf IDE, v0→Next.js, Lovable→React/Vite/Supabase）。锁定技术栈后提示词可以硬编码大量偏好，降低决策成本，但也失去跨平台弹性。
- Devin/Manus 选择"完整沙盒 + Linux 环境"路线，结果 prompt 要承担"声明环境边界、用 -y 避免交互式"的负担——换来代价是高度自主。
- Cursor 选择"多版本共存"（2.0/2025-09-03/CLI 并行维护），每个模型一套 prompt。证据：同一 Cursor 产品有 5+ 个 prompt 文件。说明**"为每个模型量身 prompt"** 是这家的核心资产。

**Missed forks**：
- 大多数工具**没选 Two-Stage Prompt**，全量装载单层 prompt。Orchids 是少数例外——意味着业内低估了 prompt 分层的价值（或评估后觉得复杂度不值得）。
- 大多数工具**没选软概率意图分类**。Kiro Mode_Classifier 是少数例外。硬 if-else 更易调试但对新场景外推弱。

**Self-reinforcement**：
- 品牌锁定（`NEVER say the name of model you use`）一旦写入，后续更新只会强化。这限制了工具向"更诚实透明"演化的能力。
- 技术栈锁定（v0/Lovable）让生态越深，迁出成本越高。这是商业护城河但也是创新枷锁。

**Lesson for us**：Orchestrator 没有"商业锁定"负担（自用项目），可以**自由借鉴 Kiro 的软分类、Orchids 的分层、Emergent 的相变契约**。同时**避免重蹈"为每个模型维护独立 prompt"的碎片化**（Cursor 问题）——我们的 SKILL.md 应保持模型无关。

## Gaps Identified

| Dimension | Their Coverage | Our Coverage | Gap |
|---|---|---|---|
| **意图分类层** | Kiro/Orchids/Warp 有独立分类 prompt | skill_routing.md 是硬规则表 | Large |
| **相变产物文件** | Emergent/Kiro Spec 有契约 .md | 无（plan → impl 假设靠对话） | Large |
| **思考触发枚举** | Devin 有 10 场景清单 | Gate Functions 只覆盖危险操作 | Large |
| **命令安全分级** | Windsurf 有 unsafe 判断 | 无（permission 是 hook 层而非 prompt 层） | Medium |
| **多模型 prompt 变体** | Cursor/Augment 有版本分化 | 单 prompt 跑 Opus/Sonnet/Haiku | Small（有意的跨模型一致性）|
| **搜索节流** | Augment GPT-5 严格限 | 无明确上限 | Small |

## Adjacent Discoveries

1. **`userInput` 工具 + reason 字符串做审批可观测性**（Kiro Spec 用 `spec-requirements-review` 等 reason）——Orchestrator 若做多阶段流水线，可复用这一模式做**分阶段阻塞点追踪**。
2. **Encore.ts 类型安全服务间调用**（Leap.new）——一个 TypeScript 微服务框架，`~encore/clients` 和 `~backend/client` 自动类型安全。我们的 orchestrator-channels 包的跨包调用可参考这个类型 layout。
3. **EARS 格式需求表达**（Kiro Spec）：Easy Approach to Requirements Syntax，强结构化需求。若我们做 spec 模式，值得作为需求模板。
4. **MCP 集成模式**（Poke p3）：`<block>` 标签 + MCP 工具错误处理。我们有 chrome-devtools/playwright MCP 但没统一错误包装模式。
5. **Mermaid 的"禁色 + 双引号 label"规则**（Devin DeepWiki）：避免特殊字符导致的渲染失败。我们写 Mermaid 时可沿用。

## Meta Insights

1. **GPT-5 级模型需要"更松的控制框架 + 更严的输出纪律"**。Cursor 2.0 (GPT-4.1) → 2025-09-03 (GPT-5) 的演化显示：todo 从细粒度变粗粒度、引入 HIGH-VERBOSITY 代码 / LOW-VERBOSITY 对话分离。这意味着 Orchestrator 切 Opus 4.7 时**不应该加更多规则，应该减规则+加纪律**。

2. **"商业护城河"和"技术先进"是不同曲线**。Windsurf 的"world's first agentic coding assistant"是营销语，其 prompt 的技术含量（liberal memory creation、unsafe command gate）确实扎实；但 Lovable 的"PERFECT ARCHITECTURE: Spaghetti code is your enemy"是营销混入提示词，对实际执行帮助有限。**我们的 voice.md 应警惕这种污染**。

3. **提示词分片是 context-budget 工程的下一站**。Poke 6-part、Xcode 5-action、Orchids 两阶段——三种不同切法都在做"按需装载"。我们的 SKILL.md 是单体 skill，单个 skill 跨模型一致是优点，但也失去了"按场景激活子集"的能力。下一步可能需要探索 **skill 内部分段 + 触发条件注入**。

4. **模式切换是 AI 工具产品化的分水岭**。纯执行 agent（Devin）vs 分模式 agent（Kiro Chat/Do/Spec, CodeBuddy Chat/Craft, Cursor Chat/Agent）代表两种哲学。Orchestrator 默认是单模式（执行优先），但我们其实已有"状态"（chat vs skill 调用）——**显式化 mode 可以提升可观测性**，这是 P0-1（软概率分类器）的深层动机。

5. **用户显式审批门是自主代理的"刹车片"**。Kiro Spec 的三相审批、Emergent 的 5 阶段确认、Devin 的环境异常求助——成熟自主代理都**主动让用户回到决策环**。Orchestrator 的 CLAUDE.md 强调"执行优先，少问"是正确的**对执行者的约束**，但应补充**"何时必须停下问"的触发点**（这其实就是 Pattern 3 `<think>` trigger 的用户侧投影）。

6. **今天偷师的最大收获不是哪条模式，而是"行业共识 vs 分歧"的信号**。并行工具调用、todo 实时打勾、禁暴露工具名——这些已是行业共识，我们 100% 命中；但软概率分类、相变契约、两阶段架构——这些是少数派选择，**正因为少见，偷到即差异化资产**。

---

**Round**: R81 | **Status**: Complete | **Next**: 基于 P0-1(软分类) 或 P0-4(相变契约) 起草实施计划
