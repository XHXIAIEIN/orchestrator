# Plan: memto P0+P1 Steal Implementation

## Goal

`memto` CLI 装好、skill 注册完、indexer/scorer 的 chrome 过滤扩展到 5 条规则、prompt 采样新增 `head-and-tail` 策略、JSONL 解析加 skip-malformed 防御——全部验证通过并提交。

## Context

R78 偷师报告识别了 1 个 P0（直接安装 memto + 注册 skill）和 4 个 P1（chrome 过滤增强、auto-scaled timeout、7 策略 prompt 采样、streaming JSONL skip-malformed）。

P2（NormalizedSession schema、fs snapshot diff 清理、Hermes noise extractor）本次不做——我们目前只面对 Claude Code，跨 runtime 需求为零。

## ASSUMPTIONS

- `npm` / `npx` 已安装且可全局执行（ASSUMPTION-A：如果 npm 不可用，步骤 1 改为从源码 `bun install && bun build` 打包，路径 `/d/Agent/.steal/memto/`）
- 步骤 5 的 auto-scaled timeout 适用场景：凡是我们代码里 `subprocess.run` 调用外部 CLI（如将来 `claude -p`）的地方。**当前 `SOUL/tools/` 里没有调用 `claude -p` 的代码**，所以步骤 5 实现一个独立工具函数即可，不修改现有调用（ASSUMPTION-B：如果 owner 确认有隐藏调用点，需补充 `depends on: step 5` 的后续步骤）
- `SOUL/tools/remember.py` 或 `memory_synthesizer.py` 里的 "first+last" prompt 采样是硬编码的——ASSUMPTION-C：如果采样逻辑在别的文件，步骤 6 需要先 grep 确认再修改
- memto CLI 的 `--fork-session` 是 Claude Code 官方 flag，本计划只调用不实现 fork 协议本身（ASSUMPTION-D）

## File Map

- `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/memto/SKILL.md` — Create（从 memto 源码 `skills/memto.md` 适配）
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/indexer.py` — Modify（扩展 chrome 过滤 + skip-malformed 增强）
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/scorer.py` — Modify（扩展 TOOL_MARKERS + system_noise 规则）
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/prompt_sampler.py` — Create（7 策略采样函数）
- `/d/Users/Administrator/Documents/GitHub/orchestrator/SOUL/tools/spawn_utils.py` — Create（auto-scaled timeout 工具函数）

---

## Steps

### Phase 1 — P0: 安装 memto + 注册 skill

**1. 安装 memto CLI 并验证可执行**

```
npm install -g memto
```
→ verify: `memto --version` 返回版本号（无报错退出码 0）

---

**2. 读取 memto 上游 skill 文件，理解触发条件和命令模板**

读取 `/d/Agent/.steal/memto/skills/memto.md` 全文，记录：
- `memto list` 的触发场景（需要查询历史 session 时）
- `memto ask "<keyword>" --question "<q>"` 的命令格式
- `--json` flag 用于 agent 消费的场景

→ verify: 文件内容可读，提取出至少 2 个触发场景描述

---

**3. 在 `.claude/skills/memto/` 创建 `SKILL.md`，适配到 Orchestrator 语境**

在 `/d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/memto/SKILL.md` 写入以下内容：

```markdown
---
name: memto
description: "Query dormant past sessions as expert collaborators. Use when: need to recall a past decision or debate, want to ask 'what did we conclude about X in the R38 session', or want to compare answers across multiple historical sessions."
---

# memto — Session Expert Protocol

memto treats past Claude Code sessions as dormant collaborators. Instead of distilling facts, you fork the original session non-destructively, ask your question in the fork, then the fork is auto-cleaned up.

## When to Use

- User asks "what did we decide about X" and `.remember/` doesn't have it
- Need to verify a past architectural decision (e.g., "the R38 AutoAgent boundary debate")
- Want to ask the same question across N past sessions and surface disagreements

## Commands

List recent sessions matching a keyword:
```
memto list [--keyword <term>] [--top 10]
```

Ask a question across matching sessions (returns JSON for agent consumption):
```
memto ask "<keyword>" --question "<your question>" --top 3 --json
```

Ask a specific session by ID:
```
memto ask --session-id <id> --question "<your question>"
```

## Constraints

- Never modify original sessions — memto forks before querying
- Use `--json` when consuming output in code; omit for human-readable output
- `memto ask` spawns subprocesses and may take 30-120s per session; plan accordingly
- If `memto` is not installed: `npm install -g memto`
```

→ verify: `cat /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/skills/memto/SKILL.md` 输出完整文件，无截断

---

--- PHASE GATE: Phase 1 (P0 install) → Phase 2 (P1 code changes) ---
[ ] Deliverable exists: `memto --version` passes; `SKILL.md` file exists with correct path
[ ] Acceptance criteria met: skill 触发描述覆盖"查询历史 session"场景；命令模板包含 `--json` 和 `--question`
[ ] No open questions: ASSUMPTION-A（npm 可用）成立
[ ] Owner review: not required

---

### Phase 2 — P1a: chrome 过滤扩展（indexer.py + scorer.py）

**4. 在 `indexer.py` 的 `parse_session()` 函数的 "跳过系统噪音" 块（当前第 139-147 行），新增 4 条过滤规则**

在现有规则之后（`if u_text.strip().startswith('<') and u_text.strip().endswith('>')` 之前或之后）追加：

```python
# memto R78: 扩展 chrome 过滤（原 memto isSystemPrompt 5 条规则）
if '<environment_context>' in u_text:
    continue
if 'Sender (untrusted metadata)' in u_text:
    continue
if '<command-message>' in u_text:
    continue
if '# AGENTS.md instructions' in u_text:
    continue
```

→ verify:
```bash
python3 -c "
import sys; sys.path.insert(0, 'SOUL/tools')
from indexer import parse_session
from pathlib import Path
import tempfile, json

# 构造包含 <environment_context> 的 fake jsonl
lines = [
    json.dumps({'type': 'user', 'message': {'content': '<environment_context>some env</environment_context>'}}),
    json.dumps({'type': 'assistant', 'message': {'content': 'I will help you'}}),
    json.dumps({'type': 'user', 'message': {'content': 'real question here please'}}),
    json.dumps({'type': 'assistant', 'message': {'content': 'real answer, more than 20 chars'}}),
]
with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
    f.write('\n'.join(lines)); fname = f.name
result = parse_session(Path(fname))
assert len(result) == 1, f'Expected 1 exchange (env_context filtered), got {len(result)}'
assert result[0]['user'] == 'real question here please'
print('PASS: environment_context filtered correctly')
"
```

- depends on: (none — isolated change)

---

**5. 在 `scorer.py` 的 `TOOL_MARKERS` 列表（当前第 46-49 行）新增 4 个 chrome 标记**

将：
```python
TOOL_MARKERS = [
    'tool_use', 'tool_result', '<system-reminder>',
    '<function_calls>', '<invoke',
]
```
改为：
```python
TOOL_MARKERS = [
    'tool_use', 'tool_result', '<system-reminder>',
    '<function_calls>', '<invoke',
    '<environment_context>', '<command-message>',
    'Sender (untrusted metadata)', '# AGENTS.md instructions',
]
```

同时在 `score_exchange()` 的 "Skill 加载/系统提示" 判断（当前第 204 行）扩展为：

```python
if ('Base directory for this skill' in user_text
        or '<system-reminder>' in user_text
        or '<environment_context>' in user_text
        or '<command-message>' in user_text
        or 'Sender (untrusted metadata)' in user_text
        or '# AGENTS.md instructions' in user_text):
    score -= 15
    tags.append('system_noise')
```

→ verify:
```bash
python3 -c "
import sys; sys.path.insert(0, 'SOUL/tools')
from scorer import score_exchange
s, tags = score_exchange('<environment_context>env stuff</environment_context>', 'answer')
assert 'system_noise' in tags, f'Expected system_noise tag, got {tags}'
print('PASS: environment_context scored as system_noise')
"
```

- depends on: (none — isolated change)

---

### Phase 2 — P1b: skip-malformed JSONL 防御增强

**6. 在 `indexer.py` 的 `parse_session()` 函数，将当前单层 try/except 改为逐行 skip-malformed 模式**

当前代码（第 98-108 行）：
```python
try:
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        messages = []
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get('type') in ('user', 'assistant'):
                    messages.append(obj)
            except json.JSONDecodeError:
                continue
except (OSError, IOError):
    return []
```

这已经有逐行 skip-malformed，但缺少对半行（truncated chunk）的防御。在内层 `except json.JSONDecodeError` 中，同时 catch `UnicodeDecodeError` 和 `ValueError`，并跳过空行：

```python
try:
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        messages = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') in ('user', 'assistant'):
                    messages.append(obj)
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                continue
except (OSError, IOError):
    return []
```

→ verify:
```bash
python3 -c "
import sys; sys.path.insert(0, 'SOUL/tools')
from indexer import parse_session
from pathlib import Path
import tempfile, json

# 包含截断行、空行、正常行
lines = [
    '{\"type\": \"user\", \"message\": {\"content\": \"hello world question here\"}}',
    '{truncated json line without closing brace',
    '',
    '{\"type\": \"assistant\", \"message\": {\"content\": \"this is a valid answer more than 20 chars\"}}',
]
with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
    f.write('\n'.join(lines)); fname = f.name
result = parse_session(Path(fname))
print(f'PASS: parsed {len(result)} exchanges from malformed file (no crash)')
"
```

- depends on: step 4

---

### Phase 2 — P1c: 7 策略 prompt 采样

**7. 创建 `SOUL/tools/prompt_sampler.py`，实现 7 种采样策略**

```python
"""
Prompt 采样策略模块（R78 memto 偷点）

7 种策略，首尾锁定（head-and-tail 前 2 后 2），
供 memory_synthesizer / compact 模板 / subagent 派发时使用。
"""
from typing import Literal

SamplingStrategy = Literal[
    'all', 'none', 'first-n', 'last-n',
    'head-and-tail', 'every-nth', 'evenly-spaced',
]


def sample_prompts(
    prompts: list[str],
    strategy: SamplingStrategy = 'head-and-tail',
    n: int = 4,
    nth: int = 3,
) -> list[str]:
    """
    从 prompts 列表中按策略采样。

    Args:
        prompts: 原始 prompt 列表（按时间排序，最旧在前）
        strategy: 采样策略
        n: first-n / last-n 取几条；head-and-tail 时前后各取 n//2 条（默认 n=4 → 前2后2）
        nth: every-nth 的步长

    Returns:
        采样后的 prompt 列表，保持原始顺序
    """
    if not prompts:
        return []

    if strategy == 'all':
        return list(prompts)

    if strategy == 'none':
        return []

    if strategy == 'first-n':
        return list(prompts[:n])

    if strategy == 'last-n':
        return list(prompts[-n:])

    if strategy == 'head-and-tail':
        half = max(1, n // 2)
        if len(prompts) <= n:
            return list(prompts)
        head = list(prompts[:half])
        tail = list(prompts[-half:])
        # 避免重叠
        overlap_start = len(prompts) - half
        if overlap_start < half:
            return list(prompts)
        return head + tail

    if strategy == 'every-nth':
        return [p for i, p in enumerate(prompts) if i % nth == 0]

    if strategy == 'evenly-spaced':
        if len(prompts) <= n:
            return list(prompts)
        step = (len(prompts) - 1) / (n - 1)
        indices = {round(i * step) for i in range(n)}
        return [prompts[i] for i in sorted(indices)]

    raise ValueError(f'Unknown strategy: {strategy}')
```

→ verify:
```bash
python3 -c "
import sys; sys.path.insert(0, 'SOUL/tools')
from prompt_sampler import sample_prompts

p = list(range(10))  # [0,1,...,9]

# head-and-tail: 前2后2
result = sample_prompts(p, 'head-and-tail', n=4)
assert result == [0, 1, 8, 9], f'head-and-tail failed: {result}'

# first-n
assert sample_prompts(p, 'first-n', n=3) == [0, 1, 2]

# last-n
assert sample_prompts(p, 'last-n', n=3) == [7, 8, 9]

# every-nth (step=3)
assert sample_prompts(p, 'every-nth', nth=3) == [0, 3, 6, 9]

# all
assert sample_prompts(p, 'all') == list(range(10))

# none
assert sample_prompts(p, 'none') == []

# evenly-spaced n=5
result = sample_prompts(p, 'evenly-spaced', n=5)
assert len(result) == 5
assert result[0] == 0 and result[-1] == 9

print('PASS: all 7 strategies verified')
"
```

- depends on: (none — new file)

---

### Phase 2 — P1d: auto-scaled timeout 工具函数

**8. 创建 `SOUL/tools/spawn_utils.py`，实现 `scaled_timeout_ms(session_path)` 函数**

```python
"""
Subprocess spawn 工具（R78 memto 偷点）

auto-scaled timeout: 120s 基准 + 1s/MB，
用于将来调用外部 CLI（如 claude -p）时根据 session 文件大小自动扩展超时。
"""
import os
from pathlib import Path


def scaled_timeout_ms(session_path: str | Path) -> int:
    """
    根据 session 文件大小计算超时毫秒数。

    公式（来自 memto）: max(120_000, 120_000 + mb * 1_000)
    即基准 120s，每 MB 额外加 1s。

    Args:
        session_path: session 文件路径（用于读取文件大小）

    Returns:
        超时毫秒数（int）

    Example:
        >>> scaled_timeout_ms('/path/to/session.jsonl')  # 50MB 文件
        170000  # 120s + 50s = 170s = 170_000ms
    """
    try:
        size_bytes = os.path.getsize(session_path)
        mb = size_bytes / (1024 * 1024)
    except (OSError, FileNotFoundError):
        mb = 0.0
    return max(120_000, int(120_000 + mb * 1_000))


def scaled_timeout_s(session_path: str | Path) -> float:
    """同上，返回秒数（供 subprocess.run timeout= 参数使用）"""
    return scaled_timeout_ms(session_path) / 1000.0
```

→ verify:
```bash
python3 -c "
import sys, tempfile, os; sys.path.insert(0, 'SOUL/tools')
from spawn_utils import scaled_timeout_ms, scaled_timeout_s

# 空文件 → 120_000ms
with tempfile.NamedTemporaryFile(delete=False) as f:
    fname = f.name
assert scaled_timeout_ms(fname) == 120_000, f'Empty file should be 120000, got {scaled_timeout_ms(fname)}'

# 50MB 文件 → 120_000 + 50*1000 = 170_000ms
with tempfile.NamedTemporaryFile(delete=False) as f:
    f.write(b'x' * (50 * 1024 * 1024)); fname2 = f.name
result = scaled_timeout_ms(fname2)
assert result == 170_000, f'50MB should be 170000ms, got {result}'

# 不存在的路径 → fallback 120_000
assert scaled_timeout_ms('/nonexistent/path.jsonl') == 120_000

# 秒版本
assert scaled_timeout_s(fname) == 120.0
os.unlink(fname); os.unlink(fname2)
print('PASS: scaled_timeout verified (empty=120s, 50MB=170s, missing=120s)')
"
```

- depends on: (none — new file)

---

### Phase 3 — Commit

**9. 在 worktree 根目录暂存并提交所有变更**

```bash
cd /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-memto
git add \
  .claude/skills/memto/SKILL.md \
  SOUL/tools/indexer.py \
  SOUL/tools/scorer.py \
  SOUL/tools/prompt_sampler.py \
  SOUL/tools/spawn_utils.py
git status
```

→ verify: `git status` 显示 5 个文件 staged，无其他意外变更

- depends on: steps 3, 4, 5, 6, 7, 8

---

**10. 提交**

```bash
git commit -m "feat(memto): steal P0+P1 — install skill, chrome filter x4, prompt sampler 7 strategies, scaled timeout"
```

→ verify: `git log --oneline -1` 显示上述 commit message，`git show --stat HEAD` 列出 5 个文件

- depends on: step 9

---

## Non-Goals

- **P2 items**（NormalizedSession schema、fs snapshot diff 清理、Hermes noise extractor）：我们只面对 Claude Code，不做
- **跨 runtime 统一适配**：不写 codex/hermes/openclaw adapter
- **fork-resume 协议实现**：我们调用 `memto` CLI，不自己实现 `--fork-session` 逻辑
- **memto 源码修改**：只安装使用，不 fork
- **auto-scaled timeout 接入现有代码**：当前 `SOUL/tools/` 没有 `claude -p` 调用点；`spawn_utils.py` 只提供工具函数，等实际调用点出现时再接入
- **`memory_synthesizer.py` 接入 `prompt_sampler.py`**：下一步工作，本次只建立工具函数

## Rollback

每步均有独立 verify 命令。如需回滚：

```bash
# 回滚 indexer.py 和 scorer.py 的修改
cd /d/Users/Administrator/Documents/GitHub/orchestrator/.claude/worktrees/steal-memto
git diff SOUL/tools/indexer.py   # 确认 diff
git diff SOUL/tools/scorer.py

# 删除新建文件
rm SOUL/tools/prompt_sampler.py
rm SOUL/tools/spawn_utils.py
rm -rf .claude/skills/memto/

# 恢复修改文件（仅在 owner 明确说 "roll back" 后执行）
# git checkout -- SOUL/tools/indexer.py SOUL/tools/scorer.py
```

---

*Plan generated: 2026-04-18 | Source: R78-memto-steal.md | Template: SOUL/public/prompts/plan_template.md*
