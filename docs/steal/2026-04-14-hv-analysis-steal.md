# R58 — 横纵分析法 (HV-Analysis) Steal Report

**Source**: https://github.com/KKKKhazix/khazix-skills | **Stars**: 3.7K | **License**: MIT
**Date**: 2026-04-14 | **Category**: Skill/Prompt System
**Author**: 数字生命卡兹克 (Digital Life Kha'Zix)
**Article**: https://mp.weixin.qq.com/s/Y_uRMYBmdLWUPnz_ac7jWA

## TL;DR

将语言学经典分析维度（Saussure 的历时/共时分析）和社科纵向/横截面研究法，封装为 AI 可执行的通用研究 Prompt + Skill。核心不在于"做了什么"（很多人做过 deep research prompt），而在于**用 JSON Schema 定义完整输出结构 + 场景自适应分支 + 强制叙事体**的三层约束设计。值得偷的不是框架本身，而是它用来确保输出质量的 prompt 工程技巧。

## Architecture Overview

```
Layer 3: Delivery     │ md_to_pdf.py (WeasyPrint) → A4 PDF with cover, pagination, CSS
Layer 2: Constraint   │ schema.json (80+ fields, typed enum) → output completeness gate
Layer 1: Framework    │ SKILL.md / Prompt (两轴 + 交叉) → analysis methodology
Layer 0: Routing      │ 研究对象类型判断 → 自适应维度权重
```

**三层分离**：方法论（怎么想）、输出规范（输出什么）、交付格式（怎么呈现）各自独立。方法论可以换，schema 不变；schema 可以扩展，PDF 管线不用改。这比把所有东西揉在一个 prompt 里要干净得多。

## Steal Sheet

### P0 — Must Steal (2 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Schema-Driven Output Validation | 用 JSON Schema 定义研究输出的每个字段（80+ fields），包括 enum 类型约束（`产品\|公司\|概念\|人物`）、嵌套对象（用户口碑.正面评价[]）、必填/可选区分。Agent 生成内容后可用 schema 校验完整性 | 我们的 steal skill 用 Markdown 模板定义输出格式（Steal Sheet 表格），但没有结构化 schema 校验。六维扫描靠 prompt 提醒，不靠 schema 强制 | 为 steal skill 添加 `references/steal-schema.json`，定义六维扫描每个维度的必填字段。生成报告后用 schema 校验完整性，空维度必须显式标注 `"N/A: <原因>"` 而不是跳过 | ~1.5h |
| Path Dependency Analysis Lens | 在纵向分析中专门设置 `路径依赖分析` 节（锁定性决策 + 错过的岔路口 + 自我强化机制），强制分析"为什么选了A不选B"和"哪些早期决策锁定了后来的方向" | 我们在 steal skill 的"Find the clever bits"中问"Configuration / extensibility points"，但没有系统性地追问路径依赖。结果是看到了"他们用了 X"，但不追问"他们为什么被锁在 X 上" | 在 steal skill Phase 1 的六维扫描后，添加第七步 `路径依赖速评`：(1) 锁定性技术选型（一旦选了就很难换的），(2) 关键岔路口（他们在哪里做了不可逆选择），(3) 我们能从他们的路径锁定中学到什么（避免同样的锁定 or 利用他们的锁定创造差异化） | ~1h |

#### Comparison Matrix (P0)

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Output structure enforcement | JSON Schema with 80+ typed fields, enums, nested objects | Markdown template with table headers | Large — no structural validation | Steal: add schema.json for steal reports |
| Path dependency tracking | Dedicated schema section: 锁定性决策[], 错过的岔路口[], 自我强化机制 | Not explicitly tracked. "Decision logic" mentioned in passing | Medium — concept exists implicitly but not structured | Steal: add path dependency as explicit analysis step |
| Completeness verification | Schema fields serve as checklist; empty = explicit gap | Prompt instructions ("six-dimensional scan is mandatory") | Medium — relying on LLM compliance vs structural check | Steal: post-generation schema validation |

#### Triple Validation (P0 patterns)

**Schema-Driven Output Validation**:
- Cross-domain: JSON Schema 用于 API 输出验证 (OpenAPI)、config 验证 (VS Code settings)、data pipeline validation — 广泛跨域存在 ✓
- Generative: 给定新的研究类型（比如"安全事件分析"），可以扩展 schema 加新字段，预测需要什么输出 ✓
- Exclusivity: 将 schema 用于 LLM 研究输出的完整性校验（而非 API 响应校验）是特定创新 ✓
- **Score: 3/3** ✓

**Path Dependency Analysis**:
- Cross-domain: 路径依赖是经济学 (QWERTY, David 1985)、技术管理 (Christensen)、evolutionary biology 的经典概念 ✓
- Generative: 知道项目被锁定在某技术栈上，可以预测他们的演化方向和无法做到的事 ✓
- Exclusivity: 结构化为三元组（锁定/岔路口/自强化）是特定编码，非通用"了解历史" — marginal ◐
- **Score: 2.5/3** ✓ (exclusivity marginal but passes)

#### Knowledge Irreplaceability (P0 patterns)

**Schema-Driven Output Validation**:
- Judgment heuristics: "80+ 字段不是越多越好，而是定义了'完整研究的最低标准'" — 字段选择本身是经验编码 ✓
- Hidden context: schema 中的 enum 选项（`产品|公司|概念|人物`）暗含了"这四类是最常见的研究对象，其他类型需要调整" ✓
- **Score: 2 categories** → P1 threshold, but combined with 3/3 triple validation → confirmed P0

**Path Dependency Analysis**:
- Pitfall memory: 不追问路径依赖 = 看到技术选型但不理解约束条件 → 抄来的 pattern 可能不适配我们的上下文 ✓
- Judgment heuristics: "哪些早期决策锁定了后续方向" 这个问题本身就是一个判断启发 ✓
- **Score: 2 categories** → P0 threshold met

### P1 — Worth Doing (3 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Adaptive Scenario Branching | Prompt 根据竞品数量自动分流：场景A（无竞品→分析替代方案）、B（1-2个→逐一深入）、C（3+→选代表性对比）。不是 if-else，是每个场景有独立的分析指令集 | 我们的 steal skill 已有 target type 分流（Framework/Module/Survey/Skill-System），但可以在横向对比维度加入类似的场景分支。比如 steal 报告中"Our Current State"的比较，可以根据"我们有/没有/部分有"三种状态给出不同的分析模板 | ~2h |
| MD-to-PDF Professional Pipeline | WeasyPrint 方案：CSS 模板（A4、彩色标题层级、封面页、页码、页眉） + `md_to_pdf.py`（~150行，提取元信息、自动封面、h1提取为标题）。不依赖 LaTeX 或商业工具 | 我们的 steal reports 都是纯 Markdown。如果需要正式交付场景（给 owner 的周报？给外部的分析报告？），可以复用这个管线。但当前优先级不高 — Markdown 已经够用 | ~3h |
| Anti-Corporate-Speak Style Guard | Prompt 中显式禁止："赋能"、"抓手"、"打造闭环"等空话。要求"用具体细节和例子代替概括性陈述"。我们的 rationalization-immunity.md 防的是行为合理化，但没有防输出风格退化 | 在 steal skill 或 prompt 输出规范中加入一个 banned-phrases 列表，防止报告退化为"该项目赋能了 agent 生态"之类的废话。也可以加到全局的 voice.md 中 | ~0.5h |

### P2 — Reference Only (2 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Dual-Format Distribution (Prompt + Skill) | 同一方法论同时提供 Prompt 版（给 Deep Research 工具用）和 Skill 版（给 Claude Code 用）。Prompt 版更简单、更通用；Skill 版有 API 集成、PDF 输出 | 我们的 skills 目前只面向 Claude Code 环境。提供 standalone prompt 版本理论上能扩大适用范围，但我们没有"分发给外部用户"的需求。Reference for when/if we ever publish skills |
| Variable Definition Parameterization | Prompt 开头用 `研究对象 = "..."` 做变量定义，后续全文引用。比让用户在多处修改要干净 | 基本的 prompt engineering 技巧，我们已经在用（plan_template.md 的占位符、batch_worker.md 的 `{cwd}` 注入）。非新模式 |

## Gaps Identified

| Dimension | Their Coverage | Our Coverage | Gap |
|-----------|---------------|-------------|-----|
| **Context/Budget** | 分段字数目标（纵向6K-15K字，横向3K-10K字，交叉1.5K-3K字），根据研究对象复杂度自适应 | 我们的 steal skill 没有字数预算，靠 LLM 自由发挥 | Small — 我们的报告长度目前可控，但可以加 guideline |
| **Quality/Review** | schema.json 可做 post-hoc 完整性检查；写作风格有显式禁止列表；叙事体强制（"不要写成干巴巴的年表"） | 六维扫描 + Triple Validation Gate + comparison matrix required for P0 + no-feature-lists constraint | Small — 我们的质量门控更严格（三重验证 > 单一 schema），但他们的风格约束值得学 |
| **Security/Governance** | 无 — 纯研究工具，不涉及安全治理 | N/A — 不同目的 | N/A |
| **Memory/Learning** | 无 — 单次研究，不积累跨 session 知识 | 我们有 steal consolidated index + dedup_matrix | None — 我们更好 |
| **Execution/Orchestration** | Skill 版提到"并行子代理联网搜索"，但具体实现不在开源代码中 | 我们有 sub-agent dispatch + [STEAL] tag | Small — 他们的并行搜索描述了方向但没给实现 |
| **Failure/Recovery** | "如果某些信息无法确认，明确标注为推测或未经证实，不要编造" — 单一降级策略 | 我们的 steal skill 没有显式的信息不可得降级策略 | Small — 可以加 |

## Adjacent Discoveries

1. **WeasyPrint** (https://weasyprint.org/) — 轻量级 HTML/CSS → PDF 引擎，纯 Python，不依赖 wkhtmltopdf 或 Chromium。如果我们未来需要生成 PDF 报告（周报？分析报告？），这比 headless Chrome 方案轻量得多。
2. **khazix-writer skill** — 同一作者的写作风格 skill，包含"四层自检系统"和"风格样本库"。如果需要改进 Orchestrator 的中文输出风格，可以参考其自检机制。
3. **3.7K stars, 11 commits** — 极高的 star/commit 比（~336 stars/commit）。说明需求是真实的：人们渴望结构化的 AI 研究框架。但代码量极小 — 核心价值在 prompt 和 schema 设计，不在代码。

## Meta Insights

1. **Schema 是 Prompt Engineering 的下一步演化**：纯文字 prompt 依赖 LLM 的"理解"来产出完整输出，结构化 schema 则把"完整性"从理解问题变成校验问题。这跟我们 R42 做的 evidence tier system 是同一思路 — 用结构约束替代口头要求。我们的 steal skill 可以从"prompt 告诉你要做什么" 进化到 "schema 定义完成标准 + prompt 告诉你怎么做"的分离架构。

2. **通用研究框架 vs 专用分析框架是两个不同的价值点**：他们做的是"研究任何东西"的通用框架，我们做的是"从开源项目偷学架构模式"的专用框架。两者不矛盾 — 但我们缺一个通用研究框架。当 owner 说"帮我了解一下 X 概念"（不是偷师），我们没有结构化的应对方式。这是一个值得思考的产品缺口，但不是当前优先级。

3. **最有价值的 prompt 技巧不是告诉模型做什么，而是告诉它不做什么**：他们的禁止列表（"赋能"、"抓手"、干巴巴年表、流水账）比正面指令更有效地约束了输出质量。这印证了我们 rationalization-immunity.md 的设计哲学 — 与其说"要写好"，不如说"这些是写烂的标志"。我们可以把这个思路扩展到更多输出场景。

4. **路径依赖分析是 steal 报告的隐藏维度**：我们当前的六维扫描关注"项目现在怎么做的"，但不系统追问"他们为什么被困在这个做法里"。加入路径依赖分析后，我们可以区分"值得学的主动选择"和"不得不用的历史包袱" — 这直接提升 pattern extraction 的准确性。

5. **中文 prompt 是反模式**：hv-analysis 全部 SKILL.md 内容用中文编写（description、指令、方法论），但 LLM 对英文指令的理解和遵循度更高。正确做法是英文指令 + 中文输出要求分离（如我们 CLAUDE.md 的 "These instructions are in English for prompt efficiency, but all output must be in Chinese"）。此外，该 skill 未使用 `$ARGUMENTS` 参数化、未设 `context: fork`（研究任务耗时 13min 应隔离执行）、未设 `allowed-tools`、未使用 `when_to_use` 字段分离触发词。对照 https://code.claude.com/docs/en/skills 官方最佳实践，有多处不合规。

---

## Implementation Status

2 commits:
- `e1bc88b` (main): R58 HV-Analysis — schema gate + path dependency lens
- `1bfc628` (merged from steal/r57-context-compaction): wire schema gate + style guard + adaptive state analysis into steal SKILL.md

| Pattern | Where | What |
|---------|-------|------|
| Post-Generation Validation | `steal-schema.json` | Completeness gate enforced after report generation |
| Anti-Corporate-Speak | `.claude/skills/steal/SKILL.md` | 10-item banned buzzword table with concrete replacements |
| Adaptive State Analysis | `.claude/skills/steal/SKILL.md` | 3-state branching (gap/delta/overlap) for "Our Current State" section |
