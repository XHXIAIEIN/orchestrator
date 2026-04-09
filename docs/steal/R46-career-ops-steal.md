# R46 — career-ops Steal Report

**Source**: https://github.com/santifer/career-ops | **Stars**: ~新项目 | **License**: MIT
**Date**: 2026-04-08 | **Category**: Skill-System (Claude Code 原生工作流系统)

## TL;DR

一个 **Claude Code 原生的多模式工作流引擎**，通过 prompt-as-pipeline 模式将 14 个工作流模式打包成单一 skill 入口，配合 batch worker 并行、TSV-based IPC、数据完整性校验链、以及 User/System 双层数据合约实现安全自更新。问题空间：如何在 prompt-only 架构中实现工业级流水线可靠性。

## Architecture Overview

```
Layer 4: Skill Router          (.claude/skills/career-ops/SKILL.md)
         │                     单入口，args 路由到 14 个 mode
Layer 3: Mode Files            (modes/*.md)
         │                     每个 mode = 一个完整的 prompt-as-pipeline 规范
Layer 2: Shared Context        (modes/_shared.md + modes/_profile.md)
         │                     全局规则 + 用户覆盖层
Layer 1: Infrastructure        (*.mjs scripts + batch-runner.sh)
         │                     PDF 生成、tracker 合并、状态规范化、完整性校验
Layer 0: Data Contract         (DATA_CONTRACT.md)
                               User Layer (不可碰) vs System Layer (可自更新)
```

## Steal Sheet

### P0 — Must Steal (4 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| Data Contract (User/System Layer) | 显式声明哪些文件是用户数据（永不自动更新）、哪些是系统数据（可安全替换）。DATA_CONTRACT.md 作为唯一 truth source，update-system.mjs 严格遵守 | 我们有 SOUL/public vs SOUL/private，但没有正式 contract。boot.md 编译时不区分用户定制和系统代码 | 为 Orchestrator 写一个 `DATA_CONTRACT.md`：明确 SOUL/private/（用户数据）、.claude/hooks/（用户定制）vs SOUL/public/prompts/（系统可更新）、src/（系统代码）。所有自动化脚本（编译器、更新器）必须读这个 contract | ~1h |
| TSV-based IPC for Parallel Workers | 每个 batch worker 写一个独立 TSV 文件到 `batch/tracker-additions/`，完成后 `merge-tracker.mjs` 统一合并到主 tracker。避免并发写同一文件的竞态问题。merge 时做 3 层去重（report number / entry number / company+role fuzzy match）+ 列顺序自动检测 + 状态别名规范化 | 我们的 sub-agent 通过 Agent SDK 返回结果，没有文件级 IPC。如果 agent 失败，结果丢失 | 当 sub-agent 执行长任务时（偷师、采集、分析），写中间结果到 `tmp/agent-output/{task-id}.json`，主进程做合并。这比纯内存传递更健壮 — agent 崩溃不丢数据 | ~2h |
| Pipeline Integrity Chain | 5 个脚本组成完整性校验链：`merge-tracker.mjs`（合并）→ `dedup-tracker.mjs`（去重）→ `normalize-statuses.mjs`（状态规范化）→ `verify-pipeline.mjs`（健康检查）→ `cv-sync-check.mjs`（配置一致性）。每次 batch 结束自动运行 | 我们的 `/doctor` skill 做运行时检查，但没有数据层完整性链。PATTERNS.md 手工维护，偷师索引靠记忆维护 | 为偷师系统建一个 `verify-steal.mjs`：检查 docs/steal/ 里的报告编号连续性、consolidated index 与实际文件一致性、P0 pattern 是否有对应实施 commit。可以扩展到其他 markdown-as-database 场景 | ~2h |
| Archetype → Adaptive Pipeline | 输入分类为 6 个 archetype，archetype 决定整个 pipeline 行为：优先哪些 proof points、如何 reframe 叙事、准备哪些 STAR stories、PDF 如何调整。不是 if/else 分支，而是贯穿所有 6 个 block 的 context shift | 我们的 skill routing (`skill_routing.md`) 按任务类型路由到不同 skill，但 skill 内部不根据输入分类调整行为。偷师 skill 对所有目标用同一套分析维度 | 偷师 skill 已有 target type 表（framework/self-evolving/module/survey/skill-system），但目前只影响 "analysis focus" 描述，不影响实际执行。应该让 target type 真正改变行为：framework → 侧重架构层对比，module → 侧重单点深度，skill-system → 侧重 prompt 工程 | ~1.5h |

**Comparison Matrix (P0)**:

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Data layer separation | DATA_CONTRACT.md + update-system.mjs 严格执行 | SOUL/public vs private 目录约定，无强制执行 | Large | Steal: 写 contract + 编译器读 contract |
| Parallel worker IPC | TSV files + merge script + 3-layer dedup | Agent SDK 内存返回 | Medium | Steal: 文件级中间结果 |
| Data integrity chain | 5 scripts, auto-run post-batch | /doctor 只检查运行时 | Large | Steal: 建数据层校验链 |
| Archetype-adaptive pipeline | 6 archetypes × 6 blocks = 36 行为变体 | target type 表存在但不影响执行 | Medium | Enhance: 让 target type 真正驱动行为 |

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Self-Contained Batch Prompt | `batch-prompt.md` 是一个 **完全自包含** 的 prompt，包含所有规则、模板占位符、输出格式。worker 不需要读其他文件就能工作。占位符 `{{URL}}` `{{REPORT_NUM}}` 由 orchestrator sed 替换 | 我们的 agent dispatch 依赖 boot.md + skill 加载。应为关键 sub-agent 任务写 self-contained prompt templates，减少 context 依赖 | ~3h |
| Onboarding Detection Flow | 每次 session 启动静默检查 4 个前置条件（cv.md / profile.yml / _profile.md / portals.yml），缺失则自动进入 onboarding 引导 | `/doctor` skill 做类似检查但需手动触发。可以在 SessionStart hook 里做类似的静默检查：SOUL/private 关键文件是否存在、.env 是否配置 | ~2h |
| Story Bank Accumulation | 每次评估产生 STAR+R stories，自动追加到 `interview-prep/story-bank.md`。跨 session 积累，形成可复用知识库 | 类似我们的 memory 系统，但更结构化。可以为偷师系统建一个 "pattern bank" — 跨轮次最有价值的 patterns 自动提炼到一个 master list | ~2h |
| Safe Auto-Update System | `update-system.mjs` 检查远程版本、下载更新、只替换 System Layer 文件、支持 rollback。dismiss 机制避免反复提示 | Orchestrator 用 git pull，但 SOUL/private 不在 .gitignore 里全部覆盖。可以参考这个模式建一个 skill/prompt 层自更新机制 | ~4h |
| Lock File + State Resume | `batch-runner.sh` 用 PID lock file 防重复执行，`batch-state.tsv` 记录每个 task 的状态（pending/processing/completed/failed），支持 `--retry-failed` 断点续跑 | 我们的 agent dispatch 没有 resume 能力。agent 失败了只能重跑整个任务。可以在 agent dispatch 层加 state file | ~4h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| ATS Unicode Normalization | `normalizeTextForATS()` 将 em-dash、smart quotes、zero-width chars 替换为 ASCII。mask 掉 style/script 标签只处理 body text | 领域特定（ATS 解析器兼容），我们没有 PDF 生成需求 |
| Canva MCP Integration | 可选的 Canva API 集成：duplicate design → read structure → find_and_replace → reflow layout → export。带字符预算约束 | 有趣的 MCP 集成案例，但我们目前不需要 |
| Multi-Language Mode Dirs | `modes/de/`、`modes/fr/`、`modes/pt/` 平行目录结构，profile.yml 里 `language.modes_dir` 切换 | 简单的 i18n 策略，我们的 prompt 已经用英文写+中文输出 |
| Go TUI Dashboard | Bubble Tea + Lipgloss + Catppuccin Mocha 主题的终端 UI，lazy-loaded report previews，inline status picker | 有趣但我们已有 web dashboard，不需要 TUI |

## Gaps Identified

| Dimension | Their coverage | Our gap |
|-----------|---------------|---------|
| **Security / Governance** | Data Contract 明确边界 + "NEVER submit without review" 规则 + Ethical Use 章节 | 我们有 Gate Functions 但没有数据层 contract |
| **Memory / Learning** | Story Bank 跨 session 积累 + profile.yml 随时更新 + "After every evaluation, learn" | 我们的 memory 系统更成熟，但缺少结构化知识积累（如 pattern bank） |
| **Execution / Orchestration** | batch-runner.sh 并行 + state tracking + resume + lock | 我们的 agent dispatch 缺少 state persistence 和 resume |
| **Context / Budget** | Self-contained batch prompt 减少 context 依赖 | 我们的 sub-agent prompt 依赖链较长（boot.md → skill → context） |
| **Failure / Recovery** | `--retry-failed` + max retries + state file + merge 后 verify | 缺少 agent 级别的 retry 和断点续跑 |
| **Quality / Review** | verify-pipeline + cv-sync-check + normalize-statuses | 数据层校验不足 |

## Adjacent Discoveries

1. **Playwright 作为 verification 层**：career-ops 用 Playwright 验证 WebSearch 结果的 liveness（是否过期），不是用来 scrape 而是用来 validate。这个模式可以用在我们的采集器中 — 用 browser 验证 API 返回的数据是否真实。

2. **`claude -p` + `--append-system-prompt-file` 的 batch 模式**：headless Claude worker 的实战用法。`--dangerously-skip-permissions` 允许无人值守批处理。我们的 Agent SDK 已经是更好的方案，但 batch-runner.sh 的 state management 模式值得学习。

3. **OpenCode 兼容层**：`.opencode/commands/` 目录提供了 OpenCode（另一个 AI CLI）的 slash command 映射，说明 skill 系统可以跨平台适配。值得关注 OpenCode 生态。

4. **Markdown-as-Database 的完整性工具链**：当 markdown table 作为数据存储时（我们的 PATTERNS.md、偷师索引也是），需要一套工具来维护完整性。merge、dedup、normalize、verify — 这是一个完整的 pattern。

## Meta Insights

1. **Prompt-as-Pipeline 是一种架构模式**：career-ops 证明了一个反直觉的事实 — 你不需要代码来建工作流引擎。14 个 `.md` 文件就是 14 个 pipeline 规范，Claude 就是 runtime。真正的工程量在 infra 层（合并、校验、并行）而不在 logic 层。这和我们的 Orchestrator 理念一致，但他们在 infra 层做得更扎实。

2. **Data Contract 是 prompt 系统的 schema migration**：传统软件有数据库 migration，prompt 系统的等价物是 Data Contract — 明确哪些文件是 schema（可升级）、哪些是 data（不可碰）。没有这个 contract，任何 "自更新" 都是赌博。

3. **Self-Contained Prompt 是 batch 并行的前提**：worker 不能依赖 session state 或共享 context。career-ops 的 batch-prompt.md 把所有需要的信息打包成一个文件，这是它能 N 个 worker 并行的关键。我们的 sub-agent dispatch 也应该追求 prompt 自包含。

4. **Markdown-as-Database 需要 RDBMS 级别的维护工具**：一旦你用 markdown table 存数据（applications.md、scan-history.tsv），你就需要 merge、dedup、normalize、verify。career-ops 花了 5 个脚本来维护数据完整性，这不是 over-engineering — 是必要成本。我们的偷师索引和 PATTERNS.md 也需要类似投入。

5. **740+ offers → 1 role 的筛选漏斗是 agent 系统的典型模式**：大量输入 → 结构化评估 → 过滤 → 少量高质量输出。这和我们的数据采集 → 分析 → 总结流程同构。他们的 A-F 评估体系（6 个 block × 10 维度 × 6 archetype）是结构化评估的范本。
