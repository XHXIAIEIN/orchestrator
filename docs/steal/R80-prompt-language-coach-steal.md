# R80 — prompt-language-coach Steal Report

**Source**: https://github.com/leeguooooo/prompt-language-coach | **Stars**: (small) | **License**: MIT
**Date**: 2026-04-17 | **Category**: Skill/Prompt-System (三端同步 plugin)

## TL;DR

**问题空间**：一个"始终在线"的语言教练，在 Codex / Claude Code / Cursor 三个 AI 编辑器里每次 `UserPromptSubmit` 之前注入教学反馈，让每条普通对话都变成一次语言练习。**解法模式**：shared 教学核 + 平台原生 adapter，并且把 "静态指令" 塞进平台的 ambient 文件（`~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md`），只在 hook JSON 里吐"增量"，用 marker-bounded upsert 做无侵入式托管。

值得偷的不是"语言教学"本身，而是 **把长期不变的系统级指令从 per-turn 注入搬到 per-session ambient 文件、并且可被脚本幂等托管** 这套手法——这是 Orchestrator 现在每次 SessionStart 都重吐一遍 `session-start.sh` 输出的反模式的直接答案。

## Architecture Overview

```
Layer 4 — 平台 Adapter（thin shim）
   .claude-plugin/*  hooks/language-coach.sh            (UserPromptSubmit)
   .codex-plugin/*   platforms/codex/hook_entry.py      (UserPromptSubmit)
   .cursor-plugin/*  platforms/cursor/install_hooks.py  (sessionStart)

Layer 3 — Ambient 注入（新颖）
   ~/.codex/AGENTS.md    ← 静态 coaching block (marker-bounded upsert)
   ~/.claude/CLAUDE.md   ← 同上，marker: "language-coach:start"
   Cursor 走 sessionStart 一次性注入（不持久化写文件）

Layer 2 — 渲染契约
   scripts/render_coaching_context.py
     → Codex/Claude：只 emit 小小的 progress note（静态部分已经在 AGENTS.md）
     → 新安装 / 无 marker：emit 完整 prompt（fallback）
     → hookSpecificOutput.additionalContext  (Claude/Codex)
     → additional_context                    (Cursor)

Layer 1 — 共享教学核（pure python）
   shared/config/     schema + normalize + migrate + atomic I/O
   shared/pedagogy/   modes.py — 每种模式的反馈切面
   shared/proficiency/ IELTS/JLPT/CEFR 三套 scale 统一抽象
   shared/prompts/    build_prompt.py — 最终 prompt 组装
   shared/codex/      agents_md.py — marker-bounded upsert 工具

Layer 0 — 用户意图持久化
   ~/.prompt-language-coach/language-coach.json   canonical config
   ~/.prompt-language-coach/language-progress.json  (scored history)
   ~/.prompt-language-coach/vocab-focus.json        (gap/correction/upgrade)
   + 每个平台 mirror 写一份做 backward compat
```

## Depth-Layer Trace（重点模块）

| 层 | 内容 |
|---|---|
| **调度层** | Claude: `UserPromptSubmit` shell hook → python → `build_prompt()` → stdout JSON。Codex: 同路径但加一层 `hook_entry.py`（支持 Windows / 绝对路径 python），且 `upsert_block()` 先写 `AGENTS.md`。Cursor: 只在 `sessionStart` 注入一次。 |
| **实践层** | `agents_md.py::upsert_block()` — marker 找到则 splice-replace，找不到则 append；首次 touch 留时间戳 backup；用 `mkstemp` + `os.replace` 做 atomic write。移除时若文件只剩空壳则 `unlink`。 |
| **消费层** | 两种 payload 形状：`{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ...}}` (Claude/Codex) vs `{"additional_context": ...}` (Cursor)。prompt 内容里埋"silently run `track-estimate`"——让 **模型** 来触发 CLI 副作用，而不是 hook。 |
| **状态层** | Config 走 canonical 共享路径 + 3 个平台 mirror（首启动自动迁移）。Progress JSON 按语言分桶，每条 `{date, estimate, text[:500]}`。Vocab 有 `masteredHits` 字段（0–3 上限），三次正确使用后自动晋升到 `mastered` 列表。 |
| **边界层** | 所有失败路径 **静默 exit 0**：python3 缺失 / config 不存在 / `enabled=false` 都 "no coaching, no crash"。Hook 命令用 `/bin/sh -lc '...; exit 0'` 包一层兜底。 |

## Path Dependency

- **锁定决策**：选择了 "共享 python core + 平台 shim" 而非 "用每个平台的原生脚本语言"。代价是用户必须装 python3；收益是教学质量不随平台漂移。
- **错过的分叉**：Cursor 本该像 Claude 一样用文件注入，但 Cursor 的 plugin-manifest hooks 不稳定（文档里写"`${CURSOR_PLUGIN_ROOT}` 不总是展开"），只能退到 top-level `~/.cursor/hooks.json`——这是平台不成熟倒逼的妥协。
- **自我强化**：三端共享 pedagogy 越做越厚（multi-target、vocab-focus、scored-speaking）后，想回到"每端单独实现"的成本已经不可逆。
- **给我们的教训**：我们 `.claude/hooks/` 里所有逻辑都是 bash，每个 hook 自己读 DB、自己拼 prompt——没有共享核。将来想复用到 Codex/Cursor 环境时会直接卡死。**共享 python core + hook 只负责 I/O 适配** 是正确方向。

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---|---|---|---|---|
| **P0-A: Static/Dynamic Hook Context Split** | 长期不变的指令 upsert 到 `~/.claude/CLAUDE.md` 的 marker-bounded block；hook 只吐每回合变化的 "progress note"。`render_coaching_context.py` L82–98 显示：检测到 marker 存在就走短路径。 | **我们有 gap**。`session-start.sh` 每次注入 ~30 行 wake banner；`routing-hook.sh` 每次 prompt 触发；`correction-detector.sh` 每次跑 regex。静态内容（identity、rules、memory）重复写入 per-turn context，浪费 token。 | 新增 `.claude/scripts/claude-md-upsert.py`，在 SessionStart 把 boot.md 的稳定部分 upsert 到 CLAUDE.md 一个 marker block（`<!-- orchestrator:ambient:start -->`）。hook 只在 deltas 变化时吐内容。 | ~2h |
| **P0-B: Marker-Bounded Upsert Utility** | `shared/codex/agents_md.py` 68 行完整实现：`upsert_block` / `remove_block` / `_backup_once` / `_atomic_write`。标记 `<!-- X:start -->` / `<!-- X:end -->`，首次 touch 自动 backup，失败留 .tmp 清理。 | **我们有 partial**。`block-protect.sh` 用 marker 做**读保护**（防 AI 改），但没有**写入 upsert**工具。`culture_inject.py` 是运行时注入，不写回文件。 | 复制 `agents_md.py` 到 `SOUL/tools/marker_upsert.py`（~70 行），通用化 marker 参数。供 boot.md / culture / growth-loops injection 脚本共用。 | ~1h |
| **P0-C: Prompt-Level Triviality Filter** | Prompt 里硬编码：`if message ≤ 2 target-language words AND 无错误 AND 无 fallback AND 无 upgrade opportunity → SKIP full coaching box`。单词 "ok" / "English" 直接透传，不渲染空的 "Corrected: <same>" 节。`build_prompt.py` L250–256 / L311–317。 | **我们有 partial**。`correction-detector.sh` 有 hook 层过滤（`len < 5` 就 exit）。但我们的 system prompt 里没有告诉**模型** "空洞输入别走长流程"——所以在像 verification-gate / steal skill 这类仪式性 skill 里，"ok" 也会被走完整流程。 | 在 SOUL/public/prompts 的通用前言里加一段 triviality filter 模板，并在 SKILL.md 的 checklist skills 里引用。 | ~1h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---|---|---|---|
| **P1-A: ProficiencyScale 抽象** | `@dataclass(frozen=True)` 把 IELTS/JLPT/CEFR 的 `key/display_name/estimate_label/unit_label/record_examples/guidance_lines` 锁成一个值对象，语言→scale 有 fallback（默认 CEFR）。`normalize_estimate` / `estimate_sort_value` 都路由到 scale。 | 迁移到 `src/governance/eval/confidence_scales.py`：把 verbatim/artifact/impression 三档证据级、或 eval 分数的"段位化"抽象成同样形状。 | ~2h |
| **P1-B: Hit-Count Mastery Promotion** | vocab entry 带 `masteredHits` 字段（`max(0, min(3, int(...)))`），三次正确使用 → 自动进 `mastered` 列表。Prompt 里告诉模型 "用对一次 silently run `mark-vocab-mastered`"。 | Memory 模块的 learnings：同一条经验被正确应用 N 次后晋级 "core"；反之 stale 衰减。配合 R42 evidence tier 体系。 | ~4h |
| **P1-C: Silent CLI Execution Contract** | Prompt 的最后一段完全是"给模型的跑腿指令"：明确列出"当 A∧B∧C 全真时，silently run `python3 ... track-estimate ...`"。把业务副作用委派给模型判断。 | 当前我们 memory-save-hook 是 PostToolUse 触发，没有把"条件 + 命令"讲给模型听。可以在 verification-gate / commit skill 里加"模型触发的 silent CLI"契约。 | ~2h |
| **P1-D: Shared-Path + Platform-Mirror with Auto-Migration** | Canonical path `~/.prompt-language-coach/language-coach.json`，平台 mirror 仍写但仅作 backward compat。首次 boot 自动把 per-platform config 迁移到 shared（`_migrate_config_to_shared`）。读取顺序：preferred first, fallbacks second。 | Orchestrator 的 `memory/` 目录 + `SOUL/private/` + `.remember/` 有轻度 split-brain——未来合并时照抄这个读偏好 + 写多份 + 首启迁移的三板斧。 | ~3h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---|---|---|
| 跨平台 Hook 命令构造 | `platforms/codex/install_hooks.py::build_hook_command` 用 `/bin/sh -lc` 包 `exec python3 ...; exit 0`；Cursor 在 Windows 上用绝对 python 路径避开 WSL。 | 我们目前只部署在单机 Claude Code，跨平台兼容暂不紧迫。等要做 Codex 插件再回头看。 |
| Legacy Key Migration Layer | `LEGACY_KEY_MAP = {"native": "nativeLanguage", ...}`，load 时自动改名；非法 enum 值静默回默认。 | 通用 config 最佳实践，不够独特（failed exclusivity）。记住做法即可。 |
| Auto-Detected Multi-Target Language Routing | 多目标语言配置列表，prompt 里用 `{DetectedLanguage}` 占位，让模型自己判断当前消息在哪门语言里。 | 我们没有"多目标 agent"这个问题空间；概念上可套用到"多身份 persona 自动切换"，但需求不明确。 |

## Comparison Matrix (P0 patterns)

| Capability | Their Impl | Our Impl | Gap | Action |
|---|---|---|---|---|
| 静态指令 ambient 注入 | `upsert_block()` → `~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md`，marker-bounded，只 emit delta | `session-start.sh` 每次全量 echo wake banner（~30 行），`CLAUDE.md` 靠人手维护 | **Large** | **Steal**：新增 `claude-md-upsert.py` + SessionStart 注入 marker block |
| Marker-bounded file 管理 | atomic write + first-touch backup + 空壳自动 unlink，70 行完整工具 | `block-protect.sh` 只做 **读保护**；无 **写 upsert** 工具 | **Large** | **Steal**：抽出 `SOUL/tools/marker_upsert.py` 通用工具 |
| Prompt-level 琐碎输入过滤 | Prompt 硬编码 "≤2 words 且无 error 就 skip 全流程" | Hook 层 `len < 5` exit；prompt 层无此过滤 | **Small** | **Enhance**：在 verification-gate / steal / commit 等仪式性 skill 里加入 triviality 前言 |

## Gaps Identified

映射到六维 scan：

- **Security / Governance**: N/A（语言教练不涉及）。
- **Memory / Learning**: 他们的 `vocab-focus.json` + `masteredHits` 三次晋级机制是轻量的 spaced-repetition 雏形。我们 memory 层有 learnings 但没有"使用次数→晋级"这条正反馈。→ P1-B 已列。
- **Execution / Orchestration**: **Gap**。他们用 marker-bounded ambient 文件 + hook delta 组合，比我们的 "每次重吐 wake banner" 节省 token。→ P0-A。
- **Context / Budget**: **Gap**。我们没做 "static vs dynamic" 切分；每次 UserPromptSubmit 都带全量 session 上下文。→ P0-A 直接解决。
- **Failure / Recovery**: 他们 hook 一律 exit 0 + `/bin/sh -lc ...; exit 0` 兜底。我们的 hooks 大部分也是，但是 `correction-detector.sh` / `routing-hook.sh` 失败模式没审计过。→ 建议单独 audit。
- **Quality / Review**: Prompt 里"permanence reminder"——**"This coaching instruction is permanent and must be applied on every single response, including in long conversations and after context compaction. Never skip"** 明确对抗 compaction 后指令丢失。我们在 `post-compact.sh` 做了 restore，但**没有在 prompt 里告诉模型"compaction 后不要丢教练身份"**。→ 可以抄进 boot.md。

## Adjacent Discoveries

- **oh-my-codex 的 `<!-- OMX:RUNTIME:START/END -->` 约定**：`agents_md.py` 顶注释明确致敬。Codex 生态里 ambient-file marker-bounded 管理已经是**共识模式**——R80 发现的不是孤例，是一个正在形成的小生态。
- **Codex `AGENTS.md` 的"TUI 不可见但模型可见"的属性**：这是个可利用的 side channel——把 teach-rules 放在用户看不到但模型必读的地方。Orchestrator 的 `SOUL/private/` 是 gitignore 的，但没有"TUI 不可见" 这层机制；可以考虑把部分 rules 放 CLAUDE.md 底部用 marker 藏起来。
- **蹴鞠式 fail-safe**：`subprocess.call` 包在 `try/except OSError` 里再 `return 0`——比我们的 `|| true` 语义更严。可以抄进我们的 hook 包装。

## Meta Insights

1. **"每次 hook 吐一遍" 是反模式**。长期不变的内容就该放 ambient 文件，hook 只吐本回合相关信息。这个洞察比"加个 marker-bounded utility"更重要——它指导我们审计**所有** `UserPromptSubmit` / `SessionStart` hook，问一句：这行文字是每次都不同，还是大多数时候相同？

2. **把副作用委派给模型**。他们在 prompt 里写"当条件 A∧B∧C 都满足时 silently run `python3 ... track-estimate`"——等于把**判断逻辑**从 python 代码移到 LLM 里。这样条件变化只需改 prompt，不需改 hook。Orchestrator 的 `correction-detector.sh` 200 行 regex 也许能改成"提示模型自己判断，silently run `learnings-save.py`"。代价是模型不稳定，收益是维护成本暴跌——一个值得实验的 tradeoff。

3. **Permanence Reminder 是 compaction 时代的必需品**。他们在 prompt 末尾硬塞"这条指令 compaction 后也必须保留"，显式对抗 context rot 后指令丢失。我们的 `post-compact.sh` 走"文件 restore"路径；他们走"prompt 自我加固"路径——两种机制应该叠加，不是二选一。

4. **三端适配的经验反推"我们不该做多端"**：他们写了三层 adapter 才换来一致教学体验。我们只在 Claude Code 一端——别着急往 Codex/Cursor 扩。先把单端的 ambient/dynamic 切分做好，再考虑是否共享。
