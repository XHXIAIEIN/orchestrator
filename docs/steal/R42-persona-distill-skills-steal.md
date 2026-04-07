# R42 — awesome-persona-distill-skills Steal Report

**Source**: https://github.com/xixu-me/awesome-persona-distill-skills | **Stars**: ~新项目 | **License**: CC0-1.0
**Date**: 2026-04-07 | **Category**: Skill-System (Awesome-List + 深入7个链接仓库)

## TL;DR

一个 awesome-list 索引 + 22 个独立 skill 仓库的生态系统，围绕"人格蒸馏"这一垂直场景。问题空间：如何从数字痕迹/对话/作品中提取人的思维框架、表达风格、决策模式，并封装为可运行的 Agent Skill。**核心价值不在索引本身，而在于链接仓库中几个工程化极深的项目展示了 skill 设计的最佳实践。**

深入分析了 7 个仓库：
- **anti-distill** — 内容分类与清洗流水线（SAFE/DILUTE/REMOVE/MASK 四级标签）
- **nuwa-skill (女娲)** — 最完整的 skill 生成元框架（6 Agent 并行采集 → 三重验证提炼 → 质量门 → 双 Agent 精炼）
- **digital-life (数字人生)** — 5 工具套件 + Layer 0 硬规则 + profile contract（JSON schema 约束产出物结构）
- **immortal-skill (永生)** — 7 角色模板 × 12 平台采集器 × 4 维度蒸馏 + 证据分级合并策略
- **reunion-skill (重逢)** — 纪念型 AI，渐进式回忆机制 + 心理安全护栏
- **yourself-skill (自己)** — 自我蒸馏，多源解析器（微信/QQ/社交媒体/照片 EXIF）
- **feynman-skill (费曼)** — 公众人物蒸馏的高质量产出物样本

## Architecture Overview

整个生态分三层：

```
┌─────────────────────────────────────────────────────────┐
│ Layer 3: awesome-list 索引                               │
│  README.md → 22 个链接，按关系类型分类                      │
├─────────────────────────────────────────────────────────┤
│ Layer 2: 元工具/生成器                                    │
│  nuwa-skill — 从0生成人物skill的完整流水线                  │
│  immortal-skill — 通用数字永生框架（7角色模板）              │
│  anti-distill — 反向工具：清洗skill内容                    │
│  digital-life — 5个自我考古工具套件                        │
├─────────────────────────────────────────────────────────┤
│ Layer 1: 具体产出物                                       │
│  feynman-skill, munger-skill, etc. — 生成好的可运行skill   │
│  reunion-skill — 纪念型AI（特殊用途）                      │
│  yourself-skill — 自我蒸馏产出物                           │
└─────────────────────────────────────────────────────────┘
```

## Steal Sheet

### P0 — Must Steal (4 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| 证据分级标注 (Evidence Grading) | 三级证据：`verbatim`(原话) > `artifact`(公开作品) > `impression`(主观印象)，每条数据必须标注来源可信度，合并时高级覆盖低级 | 我们的 memory 系统无证据分级，所有记忆平等对待 | 在 auto-memory 系统中加入 evidence tier 标注，影响 memory 召回权重 | ~1.5h |
| 内容四级分类器 (Content Classifier) | SAFE/DILUTE/REMOVE/MASK 四标签 + 六大高价值类别识别（踩坑经验、判断直觉、人际网络、隐性上下文、故障记忆、独特行为模式）| 我们偷师时没有系统化的知识价值分级 | 偷师报告中对提取的 pattern 增加"知识不可替代性"评分维度 | ~1h |
| 三重验证心智模型 (Triple Validation) | 跨域复现 × 生成力 × 排他性 三重验证，决定一个观点是"心智模型"还是"随口一说" | 我们的偷师 pattern 提取缺少系统性验证机制 | 在 P0 pattern 评估中增加：(1)是否跨模块复现 (2)是否能推断新场景 (3)是否有排他性 | ~0.5h |
| Layer 0 硬规则 (Hard Rules per Skill) | 每个 skill 有独立的不可违背行为准则文件，物理隔离在 `layer0/` 目录，优先级高于所有其他规则 | 我们的 Gate Functions 是全局的，没有 per-skill 的硬规则隔离 | 考虑在 skill 目录结构中增加 `constraints/` 或 `layer0/` 目录，存放该 skill 的硬性约束 | ~1h |

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| 渐进式回忆 (Progressive Memory Surfacing) | 不一次性暴露所有相关记忆，模拟人类"突然想起"的自然涌现，用"说到这个…""记得吗…"等触发语 | Orchestrator 的 memory 召回可以借鉴此机制，按相关度渐进释放而非全量倾倒 | ~3h |
| Profile Contract (JSON Schema 约束) | 用 `skill-contract.json` 定义每个 skill 产出物的必需字段、路径约定、验证规则 | skill 产出物结构化验证，用 schema 约束而非纯 prompt 约束 | ~2h |
| 矛盾保留而非调和 (Conflict Preservation) | 时间性矛盾、领域性矛盾、本质性张力分类保留，写入 `conflicts.md`，拒绝和稀泥 | 偷师报告中对发现的矛盾模式分类保留而非选边 | ~1h |
| 角色模板 × 维度矩阵 (Role-Dimension Matrix) | 7 种角色 × 4 个维度（procedure/interaction/memory/personality），每个角色只激活相关维度 | 我们的 agent/skill 系统可以借鉴此设计，不同场景只加载必要的上下文维度 | ~4h |
| 双 Agent 精炼 (Dual Agent Refinement) | 生成后用两个不同视角的 Agent 审查：一个看结构质量，一个看触发条件和可操作性 | 对偷师报告或 plan 的 review 可以用双视角 agent 审查 | ~2h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| 多平台采集器 (12+ Platform Collectors) | BaseCollector ABC → authenticate/scan/collect 三方法，统一 Message dataclass | immortal-skill 已有完整实现，但我们的采集器架构不同（已有 collector 层），结构可参考但不需要迁移 |
| 告别仪式 (Archive Ritual) | `/archive` 命令：生成告别信 → 打包加密 → 移除调用入口 | 情感计算场景特有，当前 Orchestrator 无此需求 |
| 心理安全护栏 (Safety Guard) | 检测高风险情绪关键词 → 触发紧急干预 → 提供心理援助热线 | reunion-skill 特有需求，但检测 → 干预 → 升级的三段式结构值得记住 |
| 信息源黑名单 (Source Blacklist) | 永远排除知乎/微信公众号/百度百科，只接受权威媒体 | 有趣的策略选择，但与我们的偷师场景无直接关联 |

## Comparison Matrix (P0 Patterns)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 证据分级 | `verbatim > artifact > impression` 三级，每条数据标注，合并时自动优先 | memory 无分级，auto-memory 仅按 type 分（user/feedback/project/reference） | **Large** | Steal: 在 memory frontmatter 加 `evidence: verbatim\|artifact\|impression` |
| 内容分类器 | SAFE/DILUTE/REMOVE/MASK + 六大类别 + 三档强度 + 保留率计算 | 偷师有 P0/P1/P2 但无知识可替代性维度 | **Medium** | Enhance: P0 criteria 中加"不可替代性"判断 |
| 三重验证 | 跨域复现 × 生成力 × 排他性，0 过 = 丢弃，1-2 过 = 降级 | 偷师 pattern 靠直觉评估，无系统化验证 | **Large** | Steal: 写入 steal skill 的 pattern extraction phase |
| Layer 0 硬规则 | 每个 skill 独立 `layer0/*.md`，优先级最高 | Gate Functions 全局，skill 无独立约束 | **Medium** | Steal: skill 目录结构增加约束文件支持 |

## Gaps Identified

| 维度 | 他们有 | 我们缺 |
|------|--------|--------|
| Memory / Learning | 证据分级 + 增量合并 + 冲突保留 + 版本快照 | memory 无分级、无冲突检测、无版本管理 |
| Quality / Review | 三重验证 + 双 Agent 精炼 + 产出物 schema 校验 | 依赖人工判断，无系统化质量门 |
| Security / Governance | Layer 0 per-skill 硬规则 + 伦理基线 per 角色 | Gate Functions 全局，无 per-skill 约束 |
| Execution | 6 Agent 并行采集 + Review 检查点暂停 | 偷师已有并行 agent，但缺少中间检查点 |
| Failure / Recovery | 信息不足时降级（心智模型减至 2-3 个 + 增加诚实边界）| 偷师遇到信息不足时无系统性降级策略 |

## Adjacent Discoveries

1. **Agent Skills 生态 (agentskills.io)**: 一个新兴的 skill 分发平台，值得关注是否形成标准
2. **OpenClaw / clawhub**: skill 包管理工具（`clawhub install colleague-skill`），类似 npm 但专用于 agent skill
3. **Trace2Skill**: 被 immortal-skill 引用的"无冲突层次化合并"方法论，待深入
4. **表达 DNA 量化方法**: nuwa-skill 的句式指纹统计（平均句长、疑问句比例、类比密度等 6 维），可迁移到 Orchestrator 的 voice calibration
5. **反蒸馏 (Anti-Distill)**: 一个有趣的反向工具 — 不是提取知识，而是系统性地抽掉核心知识保留外壳。其分类器的"六大高价值类别"（踩坑经验、判断直觉、人际网络、隐性上下文、故障记忆、独特行为模式）是对"什么知识真正有价值"的极好反向定义

## Meta Insights

### 1. 反向定义揭示本质

anti-distill 的 classifier 通过定义"什么值得被抽掉"来反向定义"什么是真正有价值的知识"。六大高价值类别（踩坑经验、判断直觉、人际网络、隐性上下文、故障记忆、独特行为模式）是对隐性知识的最好分类法。

**对 Orchestrator 的启示**: 我们的 memory 系统应该优先保存这六类知识，因为它们恰恰是"不可从代码/文档推导"的部分。当前 auto-memory 的 "what NOT to save" 清单可以用这个框架重新审视。

### 2. 矛盾是特征不是缺陷

nuwa-skill 的矛盾处理原则（时间性/领域性/本质性张力）和 immortal-skill 的 `conflicts.md` 设计，体现了一个深刻洞察：**试图消除矛盾是在消除深度**。一个没有内在张力的人物/系统模型一定是虚假的。

**对 Orchestrator 的启示**: 我们的 memory 和偷师系统倾向于"统一"矛盾信息。应该改为分类保留矛盾，矛盾本身是高信息量信号。

### 3. 证据分级是 memory 系统的基础设施

三个项目（nuwa、immortal、digital-life）都独立发展出了证据分级体系。这不是巧合 — 当你需要从多源信息中合成判断时，**知道每条信息"有多可信"是合并的前提**。`verbatim > artifact > impression` 是最小可用的三级模型。

**对 Orchestrator 的启示**: auto-memory 的下一个进化方向不是存更多，而是标注得更好。每条 memory 应该有 evidence level。

### 4. Skill 质量 = 诚实边界的质量

feynman-skill 的诚实边界写了 6 条具体局限（性别问题、自我神话化、领域偏见、计算者 vs 思想家、历史人物、不能预测）。nuwa 的核心原则之一是"宁可生成一个诚实标注了局限的 60 分 Skill，也不要生成一个看起来完美但实际上在编造的 90 分 Skill"。

**对 Orchestrator 的启示**: 我们在偷师报告和 plan 中也应该更系统地标注"不确定"和"推测"的部分。承认局限 > 假装完美。

### 5. "蒸馏"是 prompt engineering 的终极形态

这些项目本质上在做的事情是：从非结构化的人类行为数据中提取可运行的规则集（心智模型 + 决策启发式 + 表达 DNA + 硬约束），然后封装为 SKILL.md。这和我们写 system prompt / boot.md / CLAUDE.md 是同一件事 — 只不过蒸馏对象从"人"变成了"系统行为"。

nuwa-skill 的提取框架（三重验证 + 表达 DNA 量化 + 矛盾保留 + 诚实边界）可以直接用于审计 Orchestrator 自身的 prompt 质量。
