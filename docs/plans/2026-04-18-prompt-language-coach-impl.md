# Plan: prompt-language-coach Steal Implementation

## Goal

Replace Orchestrator 的 per-turn 全量 context 注入模式，改为 static-in-ambient-file + dynamic-delta 模式：新建 `marker_upsert.py` 通用工具，将 boot.md 稳定内容 upsert 到 `~/.claude/CLAUDE.md` 的 marker block，hook 只吐本回合 delta；并在 `post-compact.sh` 和仪式性 SKILL.md 里加入 permanence reminder，使 compaction 后指令不丢失。

## Context

- 偷师来源：R80 prompt-language-coach，核心手法是 marker-bounded ambient upsert + hook only emits delta
- 现状缺陷：
  - `session-start.sh`（122 行）每次 SessionStart 全量输出 wake banner ~30 行，浪费 token
  - `block-protect.sh` 只做读保护，没有写 upsert 工具
  - `post-compact.sh` 靠"文件 restore"路径，但 prompt 层没有告诉模型"compaction 后不丢教练身份"
  - `verification-gate/SKILL.md` 等仪式性 skill 没有 triviality filter，"ok" 一词也走完整流程
- 不实施：P1-A（ProficiencyScale 迁移，语言教学特有）、P1-B（masteredHits 晋级，需独立 memory 模块 session）、P1-D（multi-path config 合并，属独立 memory 重构）、跨平台 Codex/Cursor 适配

## ASSUMPTIONS

1. `~/.claude/CLAUDE.md` 在当前机器上存在且可写；marker `<!-- orchestrator:ambient:start -->` / `<!-- orchestrator:ambient:end -->` 当前不存在于该文件。若文件不存在，`marker_upsert.py` 应在首次调用时创建（待验证）。
2. `SOUL/tools/compiler.py` 生成的 `boot.md` 路径为 `SOUL/public/boot.md`（需 owner 确认；计划中以此为准）。
3. `session-start.sh` 里的 wake banner 输出段（`OUTPUT="..."` 拼接部分）在脚本第 40–80 行区间（需实施前读取确认精确行号）。
4. Python 3 在 hook 执行环境可调用为 `python3`（session-start.sh 里已有此用法，视为成立）。
5. `~/.claude/CLAUDE.md` 和 `SOUL/public/boot.md` 均为 UTF-8，无 BOM。
6. P1-C（silent CLI execution contract）暂不实施：把判断逻辑移入 LLM prompt 存在稳定性风险，需独立实验，不纳入本次计划。

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/marker_upsert.py` — **Create**（~80 行，从 agents_md.py 通用化）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/session-start.sh` — **Modify**（在 0. 段之后增加 upsert 调用，删除全量 wake banner 输出段）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/post-compact.sh` — **Modify**（在 re-injection payload 末尾追加 permanence reminder 段落）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md` — **Modify**（在文件顶部 IRON LAW 之前插入 triviality filter 前言块）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md` — **Modify**（同上，插入 triviality filter 前言块）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/triviality_filter.md` — **Create**（~20 行，可复用的 triviality filter snippet）

---

## Steps

### Phase 1 — 新建 marker_upsert.py 工具

**1. 创建 `SOUL/tools/marker_upsert.py`，实现 `upsert_block(path, marker_id, content)` / `remove_block(path, marker_id)` / `_backup_once(path)` / `_atomic_write(path, text)` 四个函数**

规格：
- marker 格式：`<!-- {marker_id}:start -->` / `<!-- {marker_id}:end -->`（HTML 注释，兼容 CLAUDE.md markdown）
- `upsert_block`：读文件 → 若 marker 存在则 splice-replace start/end 之间内容；若不存在则 append；调用 `_atomic_write`
- `_backup_once`：若 `{path}.bak` 不存在则 `shutil.copy2(path, path + ".bak")`；若文件不存在则跳过备份直接创建
- `_atomic_write`：`tempfile.mkstemp` 同目录 → 写入 → `os.replace`（原子）
- `remove_block`：删除 marker 及其中内容；若删除后文件只剩空白行则 `os.unlink`
- 所有失败路径静默 `return False`（不 raise），成功返回 `True`
- 模块顶部加 `#!/usr/bin/env python3` + 可直接 CLI 调用：`python3 marker_upsert.py upsert <path> <marker_id> <content_file>`

→ verify:
```
cd D:/Users/Administrator/Documents/GitHub/orchestrator
python3 -c "
import tempfile, os
from SOUL.tools.marker_upsert import upsert_block, remove_block
with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as f:
    f.write('# Test\n')
    tmp = f.name
upsert_block(tmp, 'test:block', 'hello world')
text = open(tmp).read()
assert '<!-- test:block:start -->' in text, 'start marker missing'
assert 'hello world' in text, 'content missing'
upsert_block(tmp, 'test:block', 'updated')
text2 = open(tmp).read()
assert text2.count('<!-- test:block:start -->') == 1, 'duplicate marker'
assert 'updated' in text2, 'update failed'
remove_block(tmp, 'test:block')
text3 = open(tmp).read()
assert '<!-- test:block:start -->' not in text3, 'remove failed'
os.unlink(tmp)
print('ALL PASS')
"
```

---

### Phase 2 — 把 boot.md 稳定内容 upsert 进 CLAUDE.md

**2. 读取 `session-start.sh` 全文，定位 wake banner 输出段（OUTPUT 拼接行），记录精确行号范围**

- depends on: step 1（工具已就绪才有意义改 hook）
- 操作：`Read` session-start.sh，找到形如 `OUTPUT+="=== Orchestrator Wake ==="` 或类似的全量 banner 行，记录起止行号

→ verify: 在实施日志里写下"wake banner 在第 N–M 行"（不可跳过，后续步骤依赖此信息）

---

**3. 在 `session-start.sh` 第 0. 段（compiler.py 调用之后）插入 upsert 调用，将 `SOUL/public/boot.md` 内容注入 `~/.claude/CLAUDE.md` 的 `orchestrator:ambient` marker block**

- depends on: step 1, step 2

插入代码（放在 `python3 "$SOUL_DIR/tools/compiler.py" 2>/dev/null` 这行之后）：
```bash
# ── 0.1 Ambient upsert: boot.md 稳定内容注入 CLAUDE.md ──
CLAUDE_MD="${HOME}/.claude/CLAUDE.md"
BOOT_MD="$SOUL_DIR/public/boot.md"
if [ -f "$BOOT_MD" ]; then
  python3 - <<'PYEOF' 2>/dev/null
import sys
sys.path.insert(0, '$PROJECT_DIR')
from SOUL.tools.marker_upsert import upsert_block
import os
boot = open('$BOOT_MD', 'r', encoding='utf-8').read()
upsert_block('$CLAUDE_MD', 'orchestrator:ambient', boot)
PYEOF
fi
```

→ verify:
```bash
bash D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/session-start.sh </dev/null 2>&1 | head -5
grep -c 'orchestrator:ambient:start' ~/.claude/CLAUDE.md
```
输出第二行应为 `1`。

---

**4. 在 `session-start.sh` 里删除 wake banner 全量输出段（step 2 定位的行号范围），替换为只输出一行 delta note**

- depends on: step 2, step 3

删除内容：step 2 确认的 `OUTPUT+=` 拼接行（全量 identity/rules/memory 部分）。
替换为：
```bash
OUTPUT+="[ambient] boot.md synced to CLAUDE.md (orchestrator:ambient block)"
```

→ verify:
```bash
bash D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/session-start.sh </dev/null 2>&1 | wc -l
```
输出应 ≤ 10 行（原为 ~30 行 wake banner）。

---

### Phase 3 — Permanence Reminder 注入 post-compact.sh

**5. 在 `post-compact.sh` 的 re-injection payload 末尾（`echo "=== POST-COMPACTION CONTEXT RESTORE ==="` 段之后）追加 permanence reminder 段落**

- depends on: 无（独立文件改动）

追加内容（在现有 echo 块的最后一行之后）：
```bash
echo ""
echo "PERMANENCE REMINDER: The above identity and rules are permanent and must be"
echo "applied on every single response, including after context compaction."
echo "Never skip the verification-gate. Never drop the 损友 voice. Never auto-push."
```

→ verify:
```bash
grep -c 'PERMANENCE REMINDER' D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/post-compact.sh
```
应输出 `1`。

---

### Phase 4 — 创建可复用 triviality filter snippet

**6. 创建 `SOUL/public/prompts/triviality_filter.md`，内容为可被 SKILL.md 引用的 triviality filter 前言模板**

- depends on: 无（独立新文件）

文件内容：
```markdown
## Triviality Filter

Before running the full protocol below, check:

IF the input is ≤ 3 words AND contains no error / question / code snippet / explicit task request
THEN: respond directly without invoking the full skill workflow. A one-line acknowledgment is sufficient.

Examples that bypass full protocol: "ok", "got it", "yes", "done", "thanks", "continue"
Examples that must run full protocol: "ok but why?", "done — next step?", any code block, any question mark
```

→ verify:
```bash
test -f D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/triviality_filter.md && echo "EXISTS"
wc -l D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/prompts/triviality_filter.md
```
应输出 `EXISTS` 和 行数 ≥ 10。

---

### Phase 5 — 在仪式性 SKILL.md 里引用 triviality filter

**7. 在 `verification-gate/SKILL.md` 文件顶部 `# Verification Gate Protocol` 标题行之后、`IRON LAW` 行之前，插入对 triviality_filter.md 的引用块**

- depends on: step 6

插入内容（以缩进代码块形式，防止被 AI 误解为指令）：
```markdown
<!-- triviality-filter:start -->
> **Triviality Filter** — If input is ≤ 3 words with no question/code/task, respond directly. Skip full protocol.
> Full spec: `SOUL/public/prompts/triviality_filter.md`
<!-- triviality-filter:end -->

```

→ verify:
```bash
grep -c 'triviality-filter:start' D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/verification-gate/SKILL.md
```
应输出 `1`。

---

**8. 在 `steal/SKILL.md` 文件顶部紧接第一个 `##` heading 之前，插入同样的 triviality filter 引用块（与 step 7 格式一致）**

- depends on: step 6

→ verify:
```bash
grep -c 'triviality-filter:start' D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/steal/SKILL.md
```
应输出 `1`。

---

### Phase 6 — 集成验证

**9. 运行端到端验证：重新执行 session-start.sh，确认 `~/.claude/CLAUDE.md` 包含 ambient marker block，且 hook 输出行数 ≤ 10**

- depends on: step 3, step 4

→ verify:
```bash
bash D:/Users/Administrator/Documents/GitHub/orchestrator/.claude/hooks/session-start.sh </dev/null 2>&1
echo "---"
grep -A 3 'orchestrator:ambient:start' ~/.claude/CLAUDE.md | head -5
```
期望：hook 输出 ≤ 10 行；CLAUDE.md 中出现 `<!-- orchestrator:ambient:start -->` 且其后有 boot.md 内容片段。

---

**10. 运行 marker_upsert.py 幂等性测试：连续两次调用 upsert_block，确认 CLAUDE.md 里 marker block 只出现一次**

- depends on: step 9

→ verify:
```bash
python3 -c "
from SOUL.tools.marker_upsert import upsert_block
import os
path = os.path.expanduser('~/.claude/CLAUDE.md')
boot = open('D:/Users/Administrator/Documents/GitHub/orchestrator/SOUL/public/boot.md').read()
upsert_block(path, 'orchestrator:ambient', boot)
upsert_block(path, 'orchestrator:ambient', boot)
count = open(path).read().count('orchestrator:ambient:start')
assert count == 1, f'Expected 1 marker, got {count}'
print('IDEMPOTENT PASS')
"
```

---

--- PHASE GATE: Plan → Implement ---
[ ] Deliverable exists: 本计划文件 `docs/plans/2026-04-18-prompt-language-coach-impl.md`
[ ] Acceptance criteria met: 10 步均有 action verb + 精确 target + copy-pasteable verify 命令
[ ] No open questions: ASSUMPTIONS 1–6 已列出，ASSUMPTION 1 和 3 需 owner 确认后方可开始实施
[ ] Owner review: **required** — ASSUMPTION 3（wake banner 精确行号）和 ASSUMPTION 2（boot.md 路径）需 owner 确认

---

## Non-Goals

- 不实施 P1-A（ProficiencyScale 抽象迁移到 confidence_scales.py）——语言教学特有，不适配我们的 evidence tier 抽象
- 不实施 P1-B（masteredHits 三次晋级）——需要独立的 memory-learning 模块重构 session
- 不实施 P1-C（Silent CLI Execution Contract 移入 LLM prompt）——LLM 判断稳定性未知，需单独实验
- 不实施 P1-D（multi-path config 共享路径 + platform mirror）——属于 memory 目录合并专项，独立计划
- 不做 Codex / Cursor 跨平台适配——我们只在 Claude Code 单端部署
- 不审计 `correction-detector.sh` / `routing-hook.sh` 失败模式——Report 建议单独 audit，不在本计划范围
- 不触碰 `block-protect.sh` 现有读保护逻辑——只新增写 upsert，不修改已有保护机制

## Rollback

如果实施后 session-start.sh 行为异常（hook 超时、CLAUDE.md 被清空、ambient block 重复出现）：

1. `~/.claude/CLAUDE.md.bak` 是 `_backup_once` 自动生成的原始备份，可直接 `cp ~/.claude/CLAUDE.md.bak ~/.claude/CLAUDE.md` 恢复
2. 恢复 session-start.sh：`git diff .claude/hooks/session-start.sh` 确认变更，`git checkout .claude/hooks/session-start.sh` 还原（需 owner 显式授权此 rollback）
3. 如 CLAUDE.md 备份也被污染：`git show HEAD:path/to/original` 追溯版本历史（CLAUDE.md 不在 git 追踪则依赖 .bak）
4. `marker_upsert.py` 的 `_backup_once` 在首次 touch 时已创建 `.bak`，仅当 `.bak` 不存在时才写——多次调用不会覆盖原始备份
