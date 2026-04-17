# R79 — TLOTP (The Lord of the Prompt) Steal Report

**Source**: https://github.com/joseguillermomoreu-gif/tlotp | **Stars**: low-digit (solo dev, v3.5.0) | **License**: TBD
**Date**: 2026-04-17 | **Category**: Skill/prompt system

## TL;DR

TLOTP 把一个大 prompt 当 monorepo 来管：用 Claude Code 原生的 `@import` 把 super-prompt 拆成几十个 `<300` 行的模块，加一个 bash 编译器把它们扁平化到 `dist/`，加一个 DFS 循环检测器防止 @import 成环，再用 CI 做 markdown lint + 内外部链接检查 + 编译验证。问题空间=「如何把超过 3000 行的交互 prompt 做成可维护、可协作、可发版的产品」，解决模式=「prompt monorepo + compile toolchain + 原生 @import composition」。对我们最有用的不是它的 LOTR 主题或者 skill 商店集成，而是这套 prompt 工程基础设施——我们 `SOUL/public/prompts/` 25 个文件是扁平的、没有 @import、没有 lint、没有版本号，TLOTP 展示了系统化做法。

## Architecture Overview

```
Layer 0 — User Entry (Claude Code会话)
  └─ @prompts/tlotp-main.md                    # 入口 prompt
     ├─ Banner + OS detect (PASO 0.5)
     ├─ Permission mode check (PASO 0.6, non-blocking)
     └─ Paginated menu 3+1 → route to épica

Layer 1 — Épica Orchestrators
  ├─ prompts/palantir/palantir-main.md         # 配置 CRUD
  ├─ prompts/bardo/bardo-main.md               # MCP/plugin 市场
  ├─ prompts/celebrimbor/celebrimbor-main.md   # skill 市场
  ├─ prompts/ents/ents-main.md                 # CI/CD 助手
  ├─ prompts/aragorn/aragorn-main.md           # agent 市场
  └─ prompts/gandalf/gandalf-main.md           # Spec-driven dev

Layer 2 — Section modules (concern separation)
  └─ prompts/<epic>/sections/NN-concern.md     # 每个 <250 行
     ├─ 00-menu-principal.md                    # 分页菜单逻辑
     ├─ 01-mini-guide.md                        # lore
     └─ NN-module-<feature>.md                  # 具体功能

Layer 3 — Shared + Meta
  ├─ prompts/VERSION.md                        # 版本 SSOT
  ├─ prompts/docs-sources.md                   # 官方文档 URL 索引
  └─ prompts/shared/orquestacion.md            # 通用编排模式

Layer 4 — Build toolchain (scripts/)
  ├─ compile.sh          # @import → dist/*.md + dist/*.html
  ├─ verify-compile.sh   # 8 点编译断言
  ├─ import-lint.sh      # DFS 循环检测
  └─ update-version.sh   # 版本传播

Layer 5 — CI (.github/workflows/)
  ├─ ci.yml              # markdown-lint + link-check + cycle-lint + compile-check
  ├─ deploy.yml          # dist/ → josemoreupeso.es/tlotp
  └─ release-prep.yml    # semver + tag
```

**关键结构观察**: prompt 本身是源代码，`dist/` 是产物，CI 是质量门。这不是「一个大 prompt 文件」，而是「prompt 工程化项目」。

## Path Dependency Analysis

- **Locking decisions**: 选择纯 prompt（零安装）作为分发手段，让项目有独特的传播力（copy-paste 到 Claude Code 就用）。但代价是所有功能必须能用 Claude Code 原生 tool（Bash / Read / Write / WebFetch / AskUserQuestion）实现——任何需要后台 daemon、持久状态、跨会话的功能都做不了。
- **Missed forks**: 可以做一个 Python/Node CLI 包装 Claude Code SDK，把 prompt 模板化 + 数据本地化，但作者刻意不走这条路——他的前一个项目 claude-code-auto-skills 就是 bash script 路线，被 TLOTP 取代了。
- **Self-reinforcement**: 一旦全是 @imports，每加一个新功能必须适配这套模式；LOTR 主题形成社区品牌壁垒（贡献者愿意用 Rohirrim/Rivendel 命名 agents，模仿者不会）；`docs-sources.md` 的「永远 WebFetch 不 hardcode」规则让项目天然不腐化。
- **Lesson for us**: 偷 @import 管线（主动选择，值得抄）；**不要偷**零安装纯粹主义（我们有 `src/`、有 daemon、有 DB，走 prompt-only 是倒退）；LOTR 主题仅作品牌参考，我们有自己的「损友/管家」人设。

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Prompt @import Composition + Compile Pipeline** | 每个大 prompt 拆成 `main.md` + `sections/NN-concern.md`，用 `@prompts/...` 行引用，compile.sh 递归展开成单文件 `dist/tlotp-full.md` | 我们 25 个 `SOUL/public/prompts/*.md` 扁平无引用，`.claude/skills/steal/SKILL.md` 354 行无法拆分 | 把 >250 行的 SKILL.md（steal, doctor, adversarial-dev）拆成 `SKILL.md` + `sections/`，用 `@` 组合；写 `scripts/compile-prompts.sh` 展开到 `.compiled/` 供验证 | ~3h |
| **@import Cycle Detection (DFS)** | `import-lint.sh` 用 visiting/visited 两表做 DFS，检测 `A → B → A` 式循环引用，在 fenced code 外才扫 @ 行 | 无。如果我们引入 @import，必须同步引入，否则 autocompact 会炸 | 抄 `scripts/import-lint.sh` 整个文件，改路径到 `SOUL/public/prompts/` + `.claude/skills/`，加到 `.github/workflows/` 里 | ~1h |
| **Paginated Menu 3+1 Pattern (ADR-01)** | AskUserQuestion 限 4 options，约定「3 内容 + 1 导航（Ver más/Volver/Salir）」，两页覆盖 6 选项 | 我们没有统一处理，有的 skill 硬塞 4 选项，有的文字菜单绕过。Orchestrator 的 chat skill 需要 >4 的路由 | 写进 `SOUL/public/prompts/clarification.md`：`pagination_guide.md` 段落。应用到 `chat`、`collect` skill 的选择菜单 | ~1h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Single-source-of-truth VERSION + 传播脚本** | `VERSION.md` 一处定义，`update-version.sh <epic> <ver>` 用 sed 在该 epic 所有 .md 里替换 `v1.2.3` 和 `v1.2` 两种格式 | 我们 skill/prompt 完全没有版本号。加 `SOUL/public/prompts/VERSION.md` + 一个 ~30 行的 `update-version.sh`，版本号写在 SKILL.md frontmatter 里 | ~2h |
| **docs-sources.md 索引 + 「永不 hardcode」规则** | 所有外部 URL 集中在 `prompts/docs-sources.md`，每个 skill WebFetch 时 from 索引，加 fallback「如果 fetch 失败告诉用户，给手动链接」 | 我们 skill 里零散写了 URL（`https://code.claude.com/...`），新版 Claude Code 文档搬家会集体失效。做一个 `SOUL/public/prompts/docs-sources.md`，列出 Anthropic/GitHub/内部文档 URL，每个 skill 引用这个索引 | ~2h |
| **Per-Skill Memory Interaction Contract** | Palantír 是 inspection 工具，所以在其 `main.md` 里写死「本会话期间禁止写 MEMORY.md / 禁止创建 topic files」。其他 epic 不受此限制 | 我们 CLAUDE.md 有 R42 的 evidence tier，但没有「某 skill 禁止写某内存」的 skill-级开关。Palantír 的思路：每个 skill 声明 `memory_policy: read-only / read-write / no-trace`。加到 skill frontmatter，让 guard-rules hook 验证 | ~3h |
| **Informative (non-blocking) Permission Gate** | PASO 0.6 告诉用户「用 `--dangerously-skip-permissions` 最爽，不用也能跑，响应可能被打断」，AskUserQuestion 只是记录，不阻塞 | 我们 skill 假设或报错。可以给 `doctor` / `steal` / `run` 这类重 tool 的 skill 加一个开头「你现在是 `ask`/`plan`/`bypass` 哪个模式？」的信息 block | ~1h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **LOTR 主题 lore 层** | 每个 epic 一个角色（Palantír=piedra vidente），menu 用角色台词；gamification/MILESTONES 把开发路线图映射为三部曲 | 我们自己有「损友 AI 管家」人设 + Orchestrator 命名体系，换主题是冲突不是增强。可作为「narrative-as-onboarding」思路记档 |
| **Verify-compile 8 点断言表** | 编译后检查：6 个 epic 都存在 / 无残留 @import（fenced 外）/ 无 HTML wrapper 泄漏 / 每 epic 有 index.html / 无反引号字面量 `\`@prompts/` | 除非我们真的走 compile 路线，否则不需要。P0-1 落地后再回来抄这个 |
| **LOTR-themed agent lore 命名** (Aragorn 的 team builder) | Agent Team 里实 agent 叫 `php-pro`，但系统以 `php-pro (Frodo Bolsón)` 呈现给用户 | 装饰性，跟我们的 persona skill 重叠，可选 |
| **Pre-load obligatoria 规则** | main.md 顶部写「在渲染任何内容前必须解析所有 @imports，用户必须一次看到完整 prompt 不带增量加载」 | 我们的 skill 单文件无 @import 时不存在这个问题；做了 P0-1 之后自动遗传需要 |

## Comparison Matrix (P0 patterns)

### P0-1: Prompt @import Composition + Compile Pipeline

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 拆分大 prompt | `main.md` + `sections/NN-*.md`，每个 <250 行 | 扁平单文件，`steal/SKILL.md` 354 行、`doctor/SKILL.md` 178 行 | Large | Steal |
| 引用语法 | `@prompts/x/sections/01.md` 独立成行（fenced 外） | 无。纯 Markdown 标题分章节 | Large | Steal |
| 编译产物 | `dist/tlotp-full.md` 扁平版 + 每 epic 的 `epic-main.md` clean 版 + `.html` 给浏览器 | 无编译步骤，Claude Code 直接吃源文件 | Medium | Partial steal (只做 `.compiled/` 验证用，不做 `.html`) |
| 验证门 | `verify-compile.sh` + CI `compile-check` job | 无 | Large | Steal（简化版） |

**Triple Validation**:
- Cross-domain: ✅ Jekyll `{% include %}` / Hugo `partial` / LaTeX `\input` / C preprocessor 都是同构
- Generative: ✅ 可预测地告诉你「SKILL 超 300 行 → 拆」
- Exclusivity: ✅ Claude Code 原生 `@import` + 独立 lint/compile 组合是该项目特有
- **Score: 3/3**

**Knowledge Irreplaceability**:
- Pitfall memory ✓（作者踩过 500 行单文件的坑才拆）
- Judgment heuristics ✓（<250 行 / >300 行拆的阈值）
- Hidden context ✓（fenced code 里的 @prompts/ 不算 import 这种细节只有实现过才知道）
- **Categories hit: 3 → 架构级**

### P0-2: Import Cycle Detection (DFS)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| 循环检测 | `import-lint.sh` 110 行 bash，visiting/visited 两临时文件，DFS 递归 | 无。如果 @import 成环会导致 context 爆炸 | Large (if we adopt P0-1) | Steal |
| fenced code 忽略 | 显式检测 ` ``` ` 切换 `in_fenced` 状态 | N/A | - | 同时 steal |
| CI 集成 | `ci.yml` 里 `lint-imports` job 调用 | 无 | Large | Steal |

**Triple Validation**:
- Cross-domain: ✅ webpack circular-dep 插件 / TypeScript `--noCircularDeps` / madge / Cargo
- Generative: ✅ DFS 模板可套任何有向图问题
- Exclusivity: ⚠️ 实现是通用 CS，但「在 Claude Code prompt 管线里做这事」的组合是独特的
- **Score: 2/3** (通用技术但 Claude Code prompt 语境独特)

### P0-3: Paginated Menu 3+1

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| >4 选项处理 | 固定 3 content + 1 nav (`➕ Ver más...`) | 无统一模式，有的 skill 硬塞 4 option 合并、有的切文字菜单 | Medium | Steal |
| 「Volver」语义 | `🔙 Volver a página 1` 明确返回，`🚪 Salir` 明确退出 | 散乱（有的叫「返回」「取消」「主菜单」） | Small | Steal（统一导航词汇） |
| ADR 化 | `ARCHITECTURE.md` ADR-01 写明规则 | 无 ADR 文化 | Medium | Adapt（加到 `SOUL/public/prompts/clarification.md`） |

**Triple Validation**:
- Cross-domain: ✅ CLI 工具的 `More...`、手机菜单分页、游戏 dialog
- Generative: ✅ 给你任意 N > 4 的菜单，告诉你怎么分
- Exclusivity: ✅ 「3+1 固定，不要 4+0 或 2+2」的具体选择是有品味的决策
- **Score: 3/3**

## Gaps Identified

| Dimension | What they handle | What we don't | Priority |
|-----------|-----------------|--------------|----------|
| Security/Governance | Per-skill memory contracts（Palantír 禁写 MEMORY） | 我们 CLAUDE.md 有 R42 evidence tier，但没有 skill 级的 memory-interaction 声明 | P1 |
| Memory/Learning | VERSION.md SSOT + propagation script | 我们 skill/prompt 没有版本号，老 prompt 堆在 `SOUL/public/prompts/`，不知道哪个被废弃 | P1 |
| Execution/Orchestration | @import composition + modular sections | 我们 skill 单文件，无法进一步拆分，354 行的 steal SKILL.md 是明证 | P0 |
| Context/Budget | Pre-load obligatoria + 分页菜单 | 我们没有针对 AskUserQuestion 4-option 限制的统一模式 | P0 |
| Failure/Recovery | DFS cycle check + compile verify + 内外链检查 | 我们有 verification-gate 但没有 prompt/skill 层面的静态验证 | P0 |
| Quality/Review | markdownlint + lychee 外链检查 + compile check 4 job CI | 我们 `.github/workflows/` 没有 prompt/skill lint job | P1 |

## Adjacent Discoveries

- **fenced-code 切换状态机**: `import-lint.sh` 用单变量 `in_fenced=true/false` 在 bash 里做词法分析，避免把代码块里的 `@prompts/` 当真 import。这是任何「扫描 markdown 但忽略代码块」任务的模板（我们 guard-rules、`.claude/hooks/` 可能用得上）。
- **lychee-action 外链检查**: `.github/workflows/ci.yml` 用 `lycheeverse/lychee-action` 做外部 URL 活性检查，支持 exclude 模式。我们 `docs/` 目录已经有几十个外链，腐化了都不知道。
- **Dependabot 配置**: `.github/dependabot.yml` 维护 GitHub Actions 版本。我们 `.github/workflows/` 的 action 版本 pin 在 SHA 但没自动更新机制。
- **Pin action to SHA 实践**: CI 里所有第三方 action pin 到 SHA（`actions/checkout@de0fac2e...`）而不是版本 tag，防供应链攻击。我们 check 下是否一致。
- **临时文件 + trap 清理**: `VISITING=$(mktemp); trap 'rm -f "$VISITING"' EXIT` 的 bash 惯用法，比我们散落的 `rm -rf /tmp/foo*` 优雅。

## Meta Insights

1. **「超大 prompt 是源代码，不是字符串」**: TLOTP 把 3000+ 行 prompt 当软件项目管——有 src/、dist/、CI、linter、semver。我们的 `SOUL/public/prompts/` 25 个 prompt 加起来几千行，但是被当成文档而不是源代码。这个心智转变比任何具体脚本都重要：**prompt = code, therefore needs compile/lint/test/version**。

2. **原生机制 > 自造轮子**: TLOTP 用的 `@imports` 是 Claude Code 官方语法（memory 文档里写着），而不是自己发明的 include 格式。这让他们的 prompt 既能被 Claude Code 直接吃（开发时），也能被 compile.sh 静态扁平化（发版时），一套代码两种生命周期。启示：我们定自定义组合语法前先查 Claude Code 官方文档有没有。

3. **「Compile 产物 + 源码 + 验证」三件套是 prompt 工程化的最小完备集**: 没有 compile 产物，每个用户加载 N 次 @import（慢）；没有源码拆分，无法协作（大文件 diff 地狱）；没有验证，两者会漂移。三者缺一不可。

4. **菜单分页体现「硬约束 > 软约束」哲学**: AskUserQuestion 的 4 选项限制是物理约束（Claude Code 本身的限制），他们没有抱怨或绕过，而是设计了 3+1 范式吸收这个限制。对比我们有些 skill 会尝试「5 个 option 合并成 4 个描述带/分隔」这种软妥协，TLOTP 的做法更干净。原则：**遇到平台硬约束，做设计不做妥协**。

5. **零安装 vs 有基建的取舍**: TLOTP 选零安装（纯 prompt），所以任何持久状态、后台 daemon、跨会话学习都做不了——他们的 memory 文档最多是 `~/.claude/CLAUDE.md` 手写。我们有 `src/`、有 PostgreSQL、有 collectors，走完全相反的路。不要羡慕他们的「干净」，也不要让他们的设计约束偷偷影响我们（比如「让 skill 完全无状态」是他们的不得已，不是我们的目标）。

6. **LOTR 主题是杠杆不是装饰**: 他们用 Aragorn/Palantír/Gandalf 命名 epic，看起来是美化，实际上是让贡献者一听「加 Bardo 的 MCP 模块」就知道是 MCP 市场的 epic，不用看代码。这种「命名即文档」只有在有连贯世界观时才生效（单纯改叫 `module-a`/`module-b` 反而伤害）。我们「损友管家」人设有类似杠杆，要有意识地用，不是到处堆梗。

## Recommended Next Steps

1. **立刻做** (P0-1 + P0-2 + P0-3 组合，共 ~5h)：
   - 写 `scripts/prompt-compile.sh`（参考 `tlotp/scripts/compile.sh` 精简版，只做 .md 扁平化）
   - 写 `scripts/prompt-lint-cycles.sh`（直接抄 `tlotp/scripts/import-lint.sh`，改路径）
   - 把 `steal/SKILL.md` 354 行拆成 `SKILL.md` + `sections/01-preflight.md` + `02-deep-dive.md` + `03-extraction.md` + `04-output.md` + `05-index-update.md`
   - CI 里加 `prompt-lint` job
   - 在 `SOUL/public/prompts/clarification.md` 里加「AskUserQuestion 3+1 分页规范」段落

2. **下一轮**（P1 batch，共 ~8h）：
   - `SOUL/public/prompts/VERSION.md` + `update-version.sh`
   - `SOUL/public/prompts/docs-sources.md`
   - skill frontmatter 加 `memory_policy: read-only / read-write / no-trace` 字段，guard-rules hook 验证

3. **可选**：参考 GAMIFICACION.md 的叙事模式，评估我们是否需要给新贡献者/新 owner 做一个「角色入门文档」。不紧急。

---

**Report status**: Complete. All 6 dimensions scanned, path dependency assessed, 3 P0 / 4 P1 / 4 P2 extracted, Triple Validation Gate passed for P0 patterns, comparison matrices present.
**Next**: Commit, update steal index, draft P0 plan.
