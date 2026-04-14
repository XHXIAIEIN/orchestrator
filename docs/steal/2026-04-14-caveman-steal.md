# R50 — Caveman Steal Report

**Source**: https://github.com/JuliusBrussee/caveman | **Stars**: 26,461 | **License**: MIT
**Date**: 2026-04-14 | **Category**: Token Efficiency / Skill System / Hook Infrastructure

---

## TL;DR

Caveman 是一个让 AI coding agent 说话像穴居人的 Claude Code 插件，**10 天内 26K stars**。核心是：系统提示压缩 → 65-75% output token 节省。但真正值得偷的不是"说话像穴居人"的 gimmick，而是它隐含的三套工程模式：**1) 基于 flag 文件的跨 hook 状态共享**、**2) Compress-Validate-Retry 三段式 LLM 输出质量保障**、**3) 单一源头 + CI 自动同步的多平台分发架构**。这三套都可以直接移植到 Orchestrator 的 hook 系统和 CLAUDE.md 压缩工具链。

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Caveman Distribution Layer                  │
│  Claude Code Plugin  │  Codex Plugin  │  Cursor/Windsurf Rules  │
│  Cline Rules         │  Copilot       │  Gemini Extension       │
└──────────────┬───────┴────────────────┴─────────────────────────┘
               │ CI sync from single source
               ▼
┌─────────────────────────────────────────────────────────────────┐
│              skills/caveman/SKILL.md  (single source of truth)  │
└──────────────┬──────────────────────────────────────────────────┘
               │
       ┌───────┴────────────────────────┐
       │  Hook System (Claude Code)      │
       │                                │
       │  SessionStart hook             │
       │    → writes ~/.claude/.caveman-active
       │    → emits SKILL.md content as system context
       │    → checks statusline config  │
       │                                │
       │  UserPromptSubmit hook         │
       │    → reads /caveman <level>    │
       │    → updates flag file         │
       │                                │
       │  StatusLine command            │
       │    → reads flag file           │
       │    → outputs [CAVEMAN:ULTRA]   │
       └────────────────────────────────┘

       ┌────────────────────────────────┐
       │  caveman-compress pipeline     │
       │  detect.py → should_compress   │
       │  compress.py → call_claude     │
       │  validate.py → check URLs,     │
       │    headings, code blocks       │
       │  retry loop (MAX=2)            │
       │  → build_fix_prompt (surgical) │
       └────────────────────────────────┘

       ┌────────────────────────────────┐
       │  Eval Harness (3-arm)          │
       │  __baseline__ / __terse__ /    │
       │  <skill> arm                   │
       │  Honest delta = skill vs terse │
       └────────────────────────────────┘
```

**核心循环**：session 开始 → SessionStart hook 写入 flag 文件 + 向 Claude 注入完整 SKILL.md 规则 → 用户输入 `/caveman ultra` → UserPromptSubmit hook 更新 flag → statusline 读 flag 渲染徽章。三个 hook 通过一个 flag 文件 (`~/.claude/.caveman-active`) 解耦通信，互不依赖。

---

## Steal Sheet

### P0 — 必抢，有直接 ROI

| ID | 模式 | 来源文件 | Orchestrator 缺口 |
|----|------|----------|-------------------|
| P0-1 | Flag 文件跨 hook 状态共享 | `hooks/caveman-activate.js`, `caveman-mode-tracker.js`, `caveman-statusline.sh` | Orchestrator hook 之间没有持久状态通道 |
| P0-2 | Compress-Validate-Retry 三段式管道 | `compress.py`, `validate.py` | CLAUDE.md 压缩没有 structural validation |
| P0-3 | Honest eval: skill vs terse 控制臂 | `evals/llm_run.py`, `measure.py` | Orchestrator steal eval 没有控制臂，baseline 比较不诚实 |

### P1 — 值得偷，需要适配

| ID | 模式 | 来源文件 | 适配成本 |
|----|------|----------|----------|
| P1-1 | Auto-Clarity 规则（危险操作自动切换详细模式）| `skills/caveman/SKILL.md` §Auto-Clarity | 低，直接加到 CLAUDE.md 的声音校准 |
| P1-2 | 单源头 + CI 自动同步到多平台 | `.github/workflows/sync-skill.yml` | 中，Orchestrator 还不需要多平台但迟早需要 |
| P1-3 | 内容检测 + 跳过逻辑（detect.py）| `caveman-compress/scripts/detect.py` | 低，任何 LLM 处理管道都需要这层 |
| P1-4 | 强度级别 + wenyan 模式设计 | `skills/caveman/SKILL.md` | 低，Orchestrator 可以加 lite/ultra 语气档位 |

### P2 — 留意，未来可能有用

| ID | 模式 | 备注 |
|----|------|------|
| P2-1 | XDG + AppData + env var 三层配置解析 | `caveman-config.js` — Orchestrator 未来公开发布时参考 |
| P2-2 | 多语言 eval arm（caveman-cn / caveman-es）| `evals/snapshots/results.json` — 证明 caveman 风格可以本地化 |
| P2-3 | `.caveman-active` flag 被 statusline 消费的异步解耦模式 | 适用于任何 「写入方不知道消费方是谁」 的场景 |
| P2-4 | `strip_llm_wrapper` 去除 LLM 包装 fence 的正则 | `compress.py:20-25` — 通用型小工具 |

---

## Comparison Matrix

| 维度 | Caveman | Orchestrator | 差距 |
|------|---------|--------------|------|
| Hook 间通信 | flag 文件 (`~/.claude/.caveman-active`) | 无持久状态 | Orchestrator hook 目前用 stdout 单向通信 |
| LLM 输出验证 | structural validate (headings/URLs/code blocks/bullets) + retry | 无 | CLAUDE.md 压缩缺 validation 层 |
| Eval 诚实性 | 三臂（baseline/terse/skill），delta = skill vs terse | 无 | steal eval 只有主观评估 |
| SKILL.md 动态注入 | SessionStart hook 读 SKILL.md 文件，内容注入系统上下文 | 静态 CLAUDE.md | Orchestrator 的 skill 内容是静态的 |
| 多平台分发 | CI 自动同步到 8+ agent 格式 | 单平台 | 暂时不需要但模式可借鉴 |
| 配置解析 | env var > config file > default，三层优先级 | 无结构化配置 | Orchestrator hook 行为不可用户配置 |
| 压缩内容检测 | 扩展名 + 内容双重检测，YAML heuristic | 无 | 任何文件处理都需要这层 |
| 声音一致性 | Auto-Clarity 规则（危险操作自动降级） | CLAUDE.md 中有类似描述但 hook 无执行 | 规则需要 hook 层配合才可靠 |

---

## P0 深度分析

### P0-1: Flag 文件跨 Hook 状态共享

**问题**：三个 hook（SessionStart / UserPromptSubmit / statusline）需要共享同一个状态（当前 caveman 模式），但 Claude Code hook 之间没有直接通信机制。

**解法**：用文件系统当 IPC。`~/.claude/.caveman-active` 存储当前模式字符串（`full` / `ultra` / `wenyan`）。

```javascript
// caveman-activate.js (SessionStart hook)
const flagPath = path.join(os.homedir(), '.claude', '.caveman-active');
const mode = getDefaultMode();

// 1. 写入 flag
fs.writeFileSync(flagPath, mode);

// 2. 读 SKILL.md，过滤出当前强度级别的规则，注入为系统上下文
let skillContent = fs.readFileSync(
  path.join(__dirname, '..', 'skills', 'caveman', 'SKILL.md'), 'utf8'
);
// 过滤强度表：只保留 active level 那一行
const filtered = body.split('\n').reduce((acc, line) => {
  const tableRowMatch = line.match(/^\|\s*\*\*(\S+?)\*\*\s*\|/);
  if (tableRowMatch && tableRowMatch[1] !== modeLabel) return acc;  // 跳过其他级别
  acc.push(line);
  return acc;
}, []);
process.stdout.write('CAVEMAN MODE ACTIVE — level: ' + modeLabel + '\n\n' + filtered.join('\n'));
```

```bash
# caveman-statusline.sh (读 flag 渲染徽章)
FLAG="$HOME/.claude/.caveman-active"
[ ! -f "$FLAG" ] && exit 0
MODE=$(cat "$FLAG" 2>/dev/null)
if [ "$MODE" = "full" ] || [ -z "$MODE" ]; then
  printf '\033[38;5;172m[CAVEMAN]\033[0m'
else
  SUFFIX=$(echo "$MODE" | tr '[:lower:]' '[:upper:]')
  printf '\033[38;5;172m[CAVEMAN:%s]\033[0m' "$SUFFIX"
fi
```

**Orchestrator 适配方案**：
- 创建 `~/.claude/.orchestrator-context` flag 文件，存储当前 agent 模式或激活的 steal 轮次
- SessionStart hook 写入，StopHook 清除，statusline 读取渲染 `[ORC:STEAL/R50]` 徽章
- UserPromptSubmit hook 解析 `/mode stealth` 等命令更新 flag

**文件改动**：`src/channels/wake.py` 或新建 `hooks/orchestrator-activate.js`

---

### P0-2: Compress-Validate-Retry 三段式 LLM 输出管道

**问题**：让 LLM 压缩/转换文档时，输出可能丢失 URL、打乱标题、删除 code block。普通的"压缩后检查"没有明确错误分类和定向修复。

**解法**：三段式管道 + surgical fix prompt（只修错，不重压缩）。

```python
# compress.py — 核心流程
def compress_file(filepath: Path) -> bool:
    original_text = filepath.read_text(errors="ignore")
    backup_path = filepath.with_name(filepath.stem + ".original.md")

    # 防止重复压缩：backup 存在则 abort
    if backup_path.exists():
        print("Backup exists, aborting to prevent data loss.")
        return False

    # Step 1: 压缩
    compressed = call_claude(build_compress_prompt(original_text))
    backup_path.write_text(original_text)
    filepath.write_text(compressed)

    # Step 2: Validate + Retry (max 2 次)
    for attempt in range(MAX_RETRIES):
        result = validate(backup_path, filepath)
        if result.is_valid:
            break
        if attempt == MAX_RETRIES - 1:
            filepath.write_text(original_text)  # 还原
            backup_path.unlink(missing_ok=True)
            return False
        # Surgical fix: 只修错误，不重压缩
        compressed = call_claude(build_fix_prompt(original_text, compressed, result.errors))
        filepath.write_text(compressed)
    return True
```

```python
# validate.py — structural validation
def validate(original_path: Path, compressed_path: Path) -> ValidationResult:
    result = ValidationResult()
    orig = read_file(original_path)
    comp = read_file(compressed_path)

    validate_headings(orig, comp, result)    # 标题数量 + 文本必须完全一致
    validate_code_blocks(orig, comp, result) # code block 必须逐字保留
    validate_urls(orig, comp, result)        # URL 集合不能有丢失
    validate_paths(orig, comp, result)       # 路径警告（非 error）
    validate_bullets(orig, comp, result)     # bullet 变化不超过 15%

    return result
```

**关键设计**：`build_fix_prompt` 的 CRITICAL RULES 是精华 —— 它明确告诉 LLM "只修错误列表里的东西，其他一个字不动"，避免 LLM 在修复时重新压缩导致循环。

**Orchestrator 适配方案**：
- 用于 CLAUDE.md 压缩（`/caveman:compress` 等效命令）
- 用于任何 steal 报告生成后的 structural 验证（heading 数量、链接完整性）
- 直接复用 `detect.py` 的文件类型检测逻辑

---

### P0-3: 三臂 Eval 设计（Honest Delta）

**问题**：只比较 skill vs baseline 是不诚实的 —— 任何 "be terse" 的系统提示都会让 LLM 更简洁，skill 的真实贡献被夸大。

**解法**：加 `__terse__` 控制臂（`Answer concisely.`），真实 delta = skill vs terse，不是 skill vs baseline。

```python
# llm_run.py — 三臂结构
snapshot["arms"]["__baseline__"] = [run_claude(p) for p in prompts]
snapshot["arms"]["__terse__"] = [
    run_claude(p, system=TERSE_PREFIX) for p in prompts  # "Answer concisely."
]
for skill in skills:
    skill_md = (SKILLS / skill / "SKILL.md").read_text()
    system = f"{TERSE_PREFIX}\n\n{skill_md}"  # terse + skill
    snapshot["arms"][skill] = [run_claude(p, system=system) for p in prompts]
```

```python
# measure.py — savings 计算
savings = [
    1 - (s / t) if t else 0.0
    for s, t in zip(skill_tokens, terse_tokens)  # vs terse，不是 vs baseline
]
```

实测结果（evals/snapshots/results.json，claude-opus-4-6，10 prompts）：
- baseline → terse 约节省 20-30%
- terse → caveman 再节省约 40-50%
- 总节省 ~65%（报告宣传数字）

**Orchestrator 适配方案**：
- Steal round eval 加控制臂：baseline / terse / skill
- 目前的 steal 评估纯主观，引入这套 harness 后可以量化每个 steal 对 prompt 效率的实际贡献
- `evals/` 目录结构可以直接复制到 `src/governance/eval/`

---

## Gaps Identified

1. **Orchestrator 的 hook 间没有状态共享机制**：每个 hook 都是孤立的 stdout → Claude，无法传递上下文给 statusline 或其他 hook。caveman 的 flag 文件模式解决了这个问题。

2. **CLAUDE.md 和 memory 文件没有压缩质量门**：如果引入 CLAUDE.md 压缩，缺少 structural validation 会导致 URL 丢失、heading 乱序等静默错误。

3. **Steal eval 不诚实**：目前偷师报告评估主要是主观的"能用吗"，没有量化 skill 真实贡献的能力。

4. **Auto-Clarity 规则没有 hook 层执行**：CLAUDE.md 有类似的声音校准规则，但没有 hook 在检测到危险操作关键词时自动在系统上下文层面切换模式。

---

## Adjacent Discoveries

1. **Wenyan 模式的工程价值**：文言文压缩不只是噱头 —— evals 数据显示 `caveman-cn`（普通中文 caveman）与 `caveman-es`（西班牙语）在同等压缩率下成立，说明 caveman 风格在任何语言里都可以工程化。Orchestrator 的中文回复可以有对应的压缩档位。

2. **`strip_llm_wrapper` 正则**：`re.compile(r"\A\s*(`{3,}|~{3,})[^\n]*\n(.*)\n\1\s*\Z", re.DOTALL)` 用于剥离 LLM 包在整个输出外层的 ` ```markdown ``` ` fence。这个问题比想象中常见，每次让 LLM 处理 markdown 都会遇到。值得提取为 util。

3. **Multi-agent 分发不需要 plugin 系统**：CI workflow 通过简单的 `cp` + `sed` + `zip` 就把一个 SKILL.md 分发到 8 个平台格式。不需要 monorepo，不需要 npm publish，CI bot 直接 commit 回 main。极简分发模型。

4. **`CAVEMAN_DEFAULT_MODE=off` 设计**：提供 escape hatch 让用户完全禁用 auto-activation，但用户仍可手动 `/caveman` 激活。这个"可选自动化"模式是好的 UX 原则，Orchestrator 的 steal 模式也应该有类似的 opt-out。

---

## Meta Insights

1. **26K stars 在 10 天内**：核心驱动不是技术，是"穴居人说话"这个具体、可笑、可演示的 gimmick。工程上完全可以用更严肃的名字，但没有这个名字就没有这个传播速度。命名是 distribution 的一部分。

2. **README 是产品前门，CLAUDE.md 为 agent 写作**：项目的 CLAUDE.md 里明确写了"README = product artifact，non-technical people read it"。这个意识很清晰 —— 两份文档服务两类读者，风格完全不同。Orchestrator 可以借鉴这个分层。

3. **Skill 的本质是 prompt injection + persistence rule**：caveman 的 SKILL.md 不复杂，但它有一条 `## Persistence` 规则："ACTIVE EVERY RESPONSE. No revert after many turns. No filler drift." 这条规则比内容本身更重要 —— 它解决了 LLM 在长对话中模式漂移的问题。Orchestrator 的 voice calibration 里应该加入等效的 persistence 声明。

4. **Benchmark 诚实性是信任的基础**：项目 CLAUDE.md 里明确写了"Benchmark numbers from real runs. Never invent or round." benchmark 数字和 eval snapshot 都 commit 进了 git。这个透明度建立了用户信任，也防止了 agent 造假。

5. **Auto-Clarity 是 safety primitive**：在 caveman 模式下，遇到安全警告、不可逆操作、多步骤歧义时自动切回正常模式。这个不是 UX 功能，是 safety primitive。Orchestrator 的 roast 风格也需要这种自动降级机制。

---

*报告生成：R50 偷师行动 | 分支：steal/caveman | 模型：claude-sonnet-4-6*
