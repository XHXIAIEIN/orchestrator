---
title: "R78 — memto 偷师：session-as-expert 协议"
date: 2026-04-17
source: https://github.com/shizhigu/memto
clone: D:/Agent/.steal/memto/
branch: steal/memto
license: MIT
type: specific-module
dimensions:
  deep: [Memory/Learning, Execution/Orchestration]
  brief: [Quality/Review, Failure/Recovery]
  skip: [Security/Governance, Context/Budget]
---

# R78 — memto 偷师报告

**Source**: https://github.com/shizhigu/memto | **Stars**: n/a（新项目）| **License**: MIT
**Date**: 2026-04-17 | **Category**: Specific-Module（session layer / memory protocol）

## TL;DR

memto 把「记忆」重新定义成**休眠的协作者**，而不是被蒸馏的事实。过往 Claude Code / Codex / Hermes / OpenClaw session 不是数据库，是可以 `--fork-session` 唤醒提问的专家。核心偷点：**non-destructive fork-resume 协议**——每种 runtime 一种 fork 策略，原 session 永不变动，提问完自动清理。

---

## Architecture Overview

```
packages/
  session-core/
    src/
      types.ts             ← NormalizedSession 契约（4 runtime 共享 schema）
      derive.ts            ← isSystemPrompt + 7 种采样策略 + 内容提取
      jsonl.ts             ← 流式 JSONL 读取（skip-malformed）
      resume.ts            ← ask() 分发 4 种 fork 策略
      adapters/
        claude-code.ts     ← ~/.claude/projects/ → scan jsonl
        codex.ts           ← ~/.codex/sessions/  → scan + session_index.jsonl
        hermes.ts          ← ~/.hermes/state.db  → SQLite + FTS5
        openclaw.ts        ← ~/.openclaw/agents/ → scan jsonl
  cli/
    src/index.ts           ← memto list / ask（带 --json）
skills/
  memto.md                 ← 放进 ~/.claude/skills/ 教 Claude Code 何时调用
```

四个 runtime 映射到同一个 `NormalizedSession` shape；四种 fork 策略映射到同一个 `ask()` 调用：

| Runtime | 存储 | 原生 fork? | memto 策略 |
|---|---|---|---|
| Claude Code | `.jsonl` 文件 | ✅ `--fork-session` | native + 扫目录 diff 清理 fork 产物 |
| Codex | `.jsonl` 文件 | 仅交互模式 | `cp` + patch `session_meta.payload.id` |
| Hermes | SQLite + FTS5 | ❌ | `INSERT … SELECT` 复制 sessions + messages 行 |
| OpenClaw | `.jsonl` 文件 | ❌ | `cp` + patch line-0 `id` |

---

## 六维扫描

### Memory/Learning（深挖）

**持久化**：不做——session 已经在文件系统里了，memto 只扫不写。这是核心反直觉：**记忆的单位是整个原始 session，不是提取出来的 facts**。

**入场 gate**：无——所有 session 都是候选。过滤发生在查询阶段（`memto ask <keyword>` 对 title + first_prompt + cwd 做子串匹配）。

**去重**：无显式去重——同一问题问多个 session 被视为 feature，不是 bug（"比较不同 session 的答复差异是有价值的信号"）。

**时间加权压缩**：无——不压缩。依赖 runtime 自己的 session 自然老化。

**质量评分**：无——每个 session 都平等可查询，信号靠 `last_active_at` 和 cwd/keyword 匹配。

### Execution/Orchestration（深挖）

**Agent pipeline**：`listAllSessions()` → keyword filter → `Promise.all(chosen.map(ask))` → 合并输出。完全无状态，每次 fresh 扫全盘。

**Checkpoint/restart**：N/A——单次调用结束即完整，没有长时任务。

**协作模式**：**fork-resume = 无需同步的并行协作**。同一问题并行问 N 个 session，各自在副本里运行，互不干扰。

**Task handoff**：通过 skill（`skills/memto.md`）告诉调用它的 agent 什么时候该 `memto list` 什么时候该 `memto ask`。Skill 是 markdown，不是代码。

### 深度层追踪

| 层 | memto 实现 |
|---|---|
| **调度层** | `ask()` 用 switch 按 runtime 分发到 4 个实现。`Promise.all` 并行问多 session，不做限流（默认 top=3）。 |
| **实践层** | 每个 fork 实现 20-50 行核心算法：diff snapshot / `cp` + JSON patch / `INSERT…SELECT`。算法就是"复制就绪状态 + 改一个 id"。 |
| **消费层** | CLI 输出支持 `--json`（agent 消费）和 pretty（人消费）。JSON shape 对外契约完整。`extractHermesAnswer` / `extractCodexAnswer` / `extractOpenClawAnswer` 各自剥离 CLI chrome 回归纯答复文本。 |
| **状态层** | 无——每次调用扫全盘，fork 产物临时文件，进程结束前 `unlink`。 |
| **边界层** | `isAvailable()` 前置检查（runtime 没装就跳过）。`bun:sqlite` 在 node 环境下 stub 抛错 → catch 后返回 false，不崩 CLI。spawn 子进程用 SIGKILL 超时机制。malformed jsonl 行静默跳过。 |

### 路径依赖速查

- **Locking decisions**: 选了 bun runtime + bun:sqlite → 在 plain node 下需要 fallback 处理（`isAvailable()` catch 分支）；选了 subprocess spawn 而不是 API 调用 → 绑死 4 个 CLI 的输出格式（每次升级都要改 extractor）。
- **Missed forks**: 可以选择走 API（claude SDK / codex SDK）而不是 spawn CLI，但那样就无法复用已安装的 agent binary。选 CLI 是为了"用户已经装了"的现实。
- **Self-reinforcement**: 每加一个 runtime 就多一个 `adapter.ts` + 一个 fork 实现 + 一个 extractor，每加一个放大 CLI 契约锁定。
- **Lesson for us**: 主动选择的路径值得偷——**fork-resume 范式**应该拷贝。路径锁定的代价（CLI 契约脆弱）提醒我们若要做跨 runtime，优先走 API/SDK 层，不走 stdout parse。

---

## Steal Sheet

### P0 — Must Steal（1 个）

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---|---|---|---|---|
| **Non-destructive fork-resume 协议** | 原 session 永不变；fork 出副本在副本里提问；退出时清理副本 | **We don't have it**（gap）。我们 `.remember/` 和 `experiences.jsonl` 都是蒸馏后的 fact，原 session 只当垃圾扔了 | 最低成本直接采纳：`npm i -g memto` + 把 `skills/memto.md` 拷进我们的 `.claude/skills/`。让我们自己的 orchestrator 能查询 `~/.claude/projects/` 下 141 个历史 session | ~0.5h |

**三重验证**（3/3 通过，置信 P0）：

- **跨域复现**：git 分支是 fork-resume、DB snapshot 是 fork-resume、OS COW（copy-on-write）也是。memto 把这个模式搬到 agent session，是跨 3 个无关域的独立再发明。
- **生成力**：给定新场景「需要从过往对话提取决策」，这个模式告诉我们：不要蒸馏，fork 出副本直接问原 session。能预测行为。
- **排他性**：不是"加个缓存"这种通用最佳实践。有结构性选择——keep-original + fork-on-read + auto-cleanup，而不是 extract-and-store。

**知识不可替代性**（4/6 类别命中，高价值 P0）：

- 踩坑经验：in-place resume 会污染原 session；memto 用 fork 避开。
- 判断直觉：「`--question` vs 蒸馏」—— session 本身比蒸馏的 fact 信息密度更高，直接问。
- 隐性上下文：Claude Code 的 `--fork-session` 会在 project dir 留孤儿 jsonl，需要 before/after diff 清理。
- 故障记忆：Hermes `-Q` 还是会泄漏多种 chrome，必须写 regex 数组剥。

---

### P1 — Worth Doing（4 个）

| Pattern | Mechanism | Adaptation | Effort |
|---|---|---|---|
| **`isSystemPrompt()` chrome 过滤** | 9 行 function 白名单式识别 `<environment_context>` / `Sender (untrusted metadata)` / `<command-message>` / `<system-reminder>` / `# AGENTS.md instructions` | 我们的 `SOUL/tools/indexer.py` 只挡 `<system-reminder>`，漏 Codex 的 `<environment_context>` 和 OpenClaw 的 `Sender (untrusted metadata)`。把 memto 的 5 条规则合并进来 | ~0.5h |
| **Auto-scaled timeout（120s + 1s/MB）** | `Math.max(120_000, 120_000 + mb * 1_000)` | 我们任何 spawn `claude -p` 的场景（subagent、Agent tool 调用）都没做大 session 超时缩放。大 session reload 真的要几分钟 | ~0.5h |
| **7-strategy prompt sampling** | `evenly-spaced` / `first-n` / `last-n` / `head-and-tail` / `every-nth` / `all` / `none`，首尾锁定 | 我们 `.remember/recent.md` 7 天压缩、subagent 派发时挑典型 prompt、compact 模板选样——都能用这个。尤其 `head-and-tail`（前 2 后 2）很适合 long session 摘要 | ~1h |
| **Streaming JSONL + skip-malformed** | 256KB chunk，按 `\n` 切，`JSON.parse` 失败静默跳过 | 我们 `indexer.py` / `scorer.py` 按行读，没处理被 kill 的进程遗留的半行。加 try/except 一圈即可 | ~0.5h |

---

### P2 — Reference Only（3 个）

| Pattern | Mechanism | Why ref-only |
|---|---|---|
| **NormalizedSession 统一 schema** | 4 runtime → 同一 TS interface（id / started_at / cwd / first_user_prompt / sampled_user_prompts / raw_path） | 我们现在只面对 Claude Code，跨 runtime 需求 =0。等要做跨 agent 观测板时再回来看 |
| **fs snapshot diff 清理 fork 产物** | `snapshotJsonlIds(dir)` 在 spawn 前后各拍一次，diff 出新生成的 jsonl 删除 | CLI 不暴露 fork id 时的 workaround，聪明但 Claude Code 专属。我们不写 CLI，用不上 |
| **Hermes 输出 noise extractor** | 7 条 regex 白名单剥离 `↻ Resumed`、`╭─ ⚕ Hermes`、`session_id:` 等 chrome | 我们不接 Hermes，ref 如何写 noise filter 就够了 |

---

## Comparison Matrix（P0 详细 diff）

| 能力 | memto | Orchestrator 当前 | Gap | Action |
|---|---|---|---|---|
| 查询历史 session | `memto list` 4 runtime | 无——只能翻 `.remember/today-*.md` | Large | **Steal**（直接装） |
| 非破坏性唤醒 session | `ask()` fork + 清理 | 无——我们只能 resume 原 session（污染） | Large | **Steal** |
| 跨 session 并行问同一问题 | `Promise.all([...])` + disagreement surfacing | 无——Agent tool 能并行 dispatch subagent 但它们是新 session 不是唤醒旧的 | Large | **Steal** |
| Session chrome 过滤 | `isSystemPrompt()` 5 条规则 | `indexer.py` 1 条规则（`<system-reminder>`） | Small | **Enhance**（合并 4 条新规则） |
| Prompt 采样多策略 | 7 策略 | 1 策略（硬编码 first+last） | Medium | **Enhance** |
| 大 session 超时缩放 | `120s + 1s/MB` | 固定 120s 或看场景硬编码 | Small | **Steal** |

---

## Gaps Identified

- **Memory/Learning**：我们是"蒸馏流派"——所有有价值的信息靠 `memory_synthesizer.py` / `experiences.jsonl` 写回提炼版本。memto 证明了另一条路：**原始 session 本身就是最高保真度的记忆**，不需要蒸馏。我们缺这条路径（没法问"R38 那次辩论 AutoAgent 到底推理到什么程度"——只能读蒸馏后的 `archive.md`）。
- **Execution/Orchestration**：我们的多 agent 并行只在同会话内派 subagent（Agent tool 内调度）。memto 让你并行询问**过去的我**，这是正交的维度。
- **Quality/Review**：我们的 `isSystemPrompt()` 弱，导致 `.remember/today-*.md` 可能存入的 "first user prompt" 实际是 slash-command header，训练信号失真。
- **Failure/Recovery**：N/A——memto 这方面就是 try/catch + SIGKILL，没新东西。
- **Security/Governance**：N/A（扫描本地文件，无 auth 面）。
- **Context/Budget**：N/A（不做 token 预算）。

---

## Adjacent Discoveries

- **Skill-as-protocol**：`skills/memto.md` 是 markdown 不是代码，作者把「什么时候该用我」的决策放 skill 里，让调用方的 agent（Claude Code / Cursor）自己判断。这是**前端协议而不是后端集成**。我们的 `.claude/skills/*/SKILL.md` 已经在这条路上，但 memto 展示了更干净的例子——skill 只描述 triggers + 几个 CLI 命令模板。
- **文件系统即接口**：memto 把 `~/.claude/projects/` / `~/.codex/sessions/` 当成公共 API——每个 CLI 写什么 jsonl format 都是可逆向的契约。如果 Anthropic 改了 jsonl 格式 memto 就炸。**结构转移给我们**：我们也在消费 `~/.claude/projects/*.jsonl`（`SOUL/tools/indexer.py`），该格式绑死风险同样存在，需要加 version guard。
- **Bun 生态选型**：memto 用 `bun:sqlite`（Hermes adapter），但代码里显式 catch bun API 在 plain node 下抛错的情况——这是**跨运行时兼容的一种 defensive pattern**。我们未来若做 TS/JS 工具可以偷这个模式。

---

## Meta Insights

1. **「记忆」不一定是蒸馏出的结构化数据**。memto 主张：如果你的原始数据本来就是完整的对话记录（LLM 已经替你把世界建模进 context 了），再从里面抽"facts"就是信息损失。"Memory is the original agent, woken up"——把 session 当成休眠的协作者而不是存档。这个立场值得写进我们 identity 的记忆观里重新辩论。
2. **跨 runtime 统一 schema 成本低得惊人**。session-core 总共 ~1500 LOC，4 个 runtime 适配，每个 adapter ~200 行。关键是 `NormalizedSession` 只暴露**元数据 + 预览**，不试图统一消息内容 schema——那个留给消费者自己处理。**最小公倍数原则**：跨 adapter 时只暴露"人看就能决策"的字段。
3. **在现实里 fork 比蒸馏便宜**。memto 的 Hermes fork 是 2 条 INSERT…SELECT（~20 行 SQL），Claude Code 的 fork 是个官方 CLI flag。蒸馏一个 session 要 LLM 调用 + 存储层设计 + 质量评分 + 去重。**如果 runtime 已经帮你做了 checkpoint，继续蒸馏是在跟轮子竞速**。
4. **CLI 契约锁定是隐性债务**。memto 4 个 extractor 各自剥离 chrome，每个 CLI 升级都可能挂。Skill 模式虽然优雅但依赖底层 CLI 输出稳定——这是走 subprocess 不走 SDK 的代价。给我们的警示：我们自己的 `SOUL/tools/` 调用 `claude -p` 的地方也有同类风险。
5. **「fleet of dormant coworkers」心智模型很强**。不是一个大脑在长期记忆里翻档案，是一群睡着的同事可以被戳醒问问题。这个 metaphor 改变了你设计 memory 层的方式——从"怎么存得好"变成"怎么唤醒得好"。
