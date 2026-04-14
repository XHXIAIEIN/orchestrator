# R57 — Context Compaction Defense Steal Report

**Source**: parcadei/Continuous-Claude-v3 (primary), claudefa.st/context-recovery-hook, mikeadolan/compaction-hooks, badlogic/compaction-research-gist | **Stars**: 1.2k (CC-v3) | **License**: MIT
**Date**: 2026-04-14 | **Category**: Industry survey (focused on single problem domain)
**Lineage**: R35 PUA PreCompact hook → R50 Caveman state IPC → R56 harness engineering survey → R57 context compaction deep dive

---

## TL;DR

Context compaction 是 2026 年 Claude Code 生态的头号未解问题。核心矛盾：自动压缩（~83.5% 触发）是有损操作，丢失指令、决策推理、代码片段、风格规则。现有方案分三个流派：**预防式**（阈值门控，85% 时拦截 + 强制交接）、**抢救式**（PreCompact 写快照 + PostCompact/SessionStart 注回）、**主动式**（token 级增量备份，50K 起步每 10K 触发一次）。Continuous-Claude-v3 是最完整的实现，独创 status.py→tmpfile→Stop hook 两跳架构 + transcript JSONL 解析 + YAML 结构化交接文档。Orchestrator 现有 pre-compact.sh + post-compact.sh 只覆盖"抢救式"的基础版，缺少预防式阈值门控和主动式增量备份。

---

## Architecture Overview

### 问题空间定位

Context compaction 不是一个功能——它是 Claude Code 架构中的**信息论瓶颈**。200K token 窗口看起来大，但实际可用约 167K（33K 硬编码 buffer 不可配置），一旦触发自动压缩，对话历史被送进独立模型调用做摘要，摘要替换原始历史。这是单向有损操作。

### 三流派架构对比

```
┌─────────────────────────────────────────────────────────────┐
│                    PREVENTION LAYER (预防)                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ StatusLine → context% → tmpfile → Stop Hook         │    │
│  │ Block at 85% threshold → force /create_handoff      │    │
│  │ Source: Continuous-Claude-v3                          │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Token-Based Proactive Backup                        │    │
│  │ StatusLine → 50K/60K/70K... token triggers          │    │
│  │ + 30%/15%/5% remaining percentage fallbacks         │    │
│  │ Source: claudefa.st ContextRecoveryHook              │    │
│  └─────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                    RESCUE LAYER (抢救)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ PreCompact Hook                                     │    │
│  │ Parse transcript JSONL → structured handoff → file   │    │
│  │ Behavioral state checkpoint + persona anchor         │    │
│  │ Source: All (CC-v3, clauditor, Dolan, us)            │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ PostCompact / SessionStart(compact) Re-injection    │    │
│  │ Read saved handoff → inject via additionalContext    │    │
│  │ One-shot flag: fire once, consume flag              │    │
│  └─────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                    PERSISTENCE LAYER (持久)                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Full Conversation → SQLite (lossless archive)       │    │
│  │ Source: Dolan's system (1300+ sessions, ~1GB)        │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Agent Output → File Isolation (context-safe)         │    │
│  │ .claude/cache/agents/{name}/latest-output.md        │    │
│  │ Source: CC-v3                                        │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ TLDR Read Gate (prevent context pollution)          │    │
│  │ PreToolUse:Read → redirect large files → summary     │    │
│  │ Source: CC-v3                                        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## Six-Dimensional Scan

### 1. Security / Governance

- **Stop hook 是物理拦截**，不是 prompt-level 建议。`auto-handoff-stop.py` 返回 `{"decision":"block"}` 时 Claude 无法绕过——这是硬约束。
- **Anti-recursion guard**: `if data.get('stop_hook_active')` 防止 Stop hook 在创建 handoff 时触发自身循环。
- **Flag 消费语义**: `state_del("compact.pending")` 确保 re-injection 只触发一次，不会在每次 PostToolUse 都重复注入。CC-v3 的 SessionStart(compact) 也只触发一次。
- **Agent 权限分级**: CC-v3 把 agent 分为 `skip`（自动批准）和 `queue`（排队等审批），`inherit_blocks: true` 继承父会话的工具黑名单。

### 2. Memory / Learning

- **Transcript JSONL 解析**是最大亮点。CC-v3 的 `transcript-parser.ts` 直接读 Claude Code 提供的 `input.transcript_path`，提取：
  - 最后一次 `TodoWrite` 调用的任务状态
  - 最近 5 次工具调用（成功/失败）
  - 最近 5 次 Bash 错误
  - 所有被 Edit/Write 修改的文件路径
  - 最近 500 字符的 assistant 消息
- **Ledger pruning**: `pruneLedger()` 每次加载时删除 `### Session Ended` 条目，agent 报告最多保留 10 个。防止状态文件本身成为 context 负担。
- **Dolan 的 SQLite 全量存档**: 1300+ 会话约 1GB，支持关键词、语义、模糊搜索。PostCompact 从 DB 查询相关上下文注回，不是全量 dump。

### 3. Execution / Orchestration

- **两跳架构** (CC-v3): `status.py`（StatusLine 命令）计算 context% → 写 tmpfile → `auto-handoff-stop.py`（Stop hook）读 tmpfile → 判断阈值。两个独立脚本共享同一数据源，没有重复计算。
- **PreCompact 三明治** (CC-v3): PreCompact 写 handoff → Claude Code 执行压缩 → SessionStart(compact) 读 handoff 注回 `additionalContext`。注意 SessionStart 的 `matcher: "resume|compact|clear"` 同时处理三种场景。
- **Session affinity via terminal PID**: `handoff-index.ts` 用 SQLite 存 `terminal_pid → session_name` 映射。跨 `/clear` 后 `session_start_continuity.py` 用 `get_terminal_shell_pid()` 查找正确的会话 handoff，不是抓最新的。

### 4. Context / Budget

- **Claude Code 内部**: 200K 窗口，33K 硬编码 buffer（16.5%，不可配），实际可用 ~167K，~83.5% 触发自动压缩。
- **`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`**: 环境变量，1-100，直接控制触发百分比。
- **StatusLine 是唯一实时 context 监控渠道**: 每轮接收 `context_window.remaining_percentage`。关键：这个百分比包含 buffer，实际可用 = remaining - 16.5%。
- **claudefa.st 的双触发系统**: token 级（50K 起步每 10K）+ 百分比级（30%/15%/5%），在大窗口下 token 触发主导，小窗口下百分比触发覆盖。
- **TLDR Read Gate** (CC-v3): `tldr-read-enforcer.mjs` 拦截大文件 Read → 替换为 TLDR 摘要，从源头减少 context 污染。

### 5. Failure / Recovery

- **Compaction 检测**: CC-v3 的 `status.py` 监测 context% 下降 >10% → 记录到 `~/.claude/autocompact.log`。这是被动检测。
- **Handoff 结构化 recovery**: YAML 格式包含 `goal/now/done/blockers/questions/decisions/findings/worked/failed/next/files` 11 个字段，比我们的 9-section compact template 更细粒度。
- **Recovery 优先级**: claudefa.st 推荐 compaction 后 `/clear` + 读备份，比继续在压缩后的上下文里工作更干净。但这需要人工介入。
- **CC-v3 的 auto-handoff 是自动的**: Stop hook block → Claude 被迫执行 `/create_handoff` → 新会话 SessionStart 自动加载。闭环。

### 6. Quality / Review

- **PostCompact 健康检查** (clauditor): 扫描压缩后的输出检查 identity marker 存活情况，返回 ALIVE/WEAK/SILENT 三级信号。这是唯一看到的**验证型**防御。
- 其他方案都是 fire-and-forget：注入后不检查是否真的恢复了。
- CC-v3 的 `session-outcome.mjs` SessionEnd hook 让用户标记 handoff 结果（成功/部分/失败），形成反馈循环。

---

## Path Dependency Assessment

### Locking Decisions

- **CC-v3 选择 TypeScript + PostgreSQL**: 用 `.mjs` 预编译包实现零安装，但把 session 注册锁死在 PostgreSQL。对单机用户是 overkill。
- **claudefa.st 选择纯 Node.js**: 无外部依赖，但 token 计算依赖 StatusLine API 的 `remaining_percentage` 字段——如果 Claude Code 改 API 就废了。
- **Dolan 选择 SQLite 全量存档**: 简单可靠，但 1GB/1300 session 的增长曲线意味着长期需要清理策略。
- **我们选择 bash + Python 混合**: 轻量、无依赖，但 bash 脚本的 JSON 处理能力弱，难以解析 transcript JSONL。

### Missed Forks

- CC-v3 的 `PreCompact → SessionStart(compact)` 路径比我们的 `PreCompact → PostToolUse flag` 更可靠——因为 SessionStart(compact) 是 Claude Code 保证触发的事件，而 PostToolUse 依赖"压缩后用户发消息导致工具调用"才能触发。如果压缩后用户直接打字不触发工具，我们的 re-injection 就丢了。
- claudefa.st 的主动式备份是一个我们完全没走的方向——不等 compaction 发生，提前多次备份。

### Lesson for Us

- CC-v3 的**两跳架构**是值得抄的 active choice（StatusLine → tmpfile → Stop hook）。
- CC-v3 的 PostgreSQL 依赖是 path lock-in，我们应避免。SQLite 足够。
- claudefa.st 的 token 级触发是 active choice，但实现复杂度较高，可以简化为百分比触发。

---

## Steal Sheet

### P0 — Must Steal (4 patterns)

**1. Context Threshold Stop Gate**

| Field | Content |
|-------|---------|
| **What it does** | 在 context 使用率达到 85% 时拦截 Claude 的 Stop 事件，强制执行 handoff 而不是继续工作直到自动压缩 |
| **How it works** | StatusLine 脚本每轮计算 context%，写入 tmpfile；Stop hook 读取 tmpfile，>=85% 返回 `{"decision":"block","reason":"..."}` |
| **Why it's good** | 预防 > 抢救。在 compaction 发生之前就介入，给出清晰指令（"运行 /create_handoff"），避免有损压缩 |
| **How to adapt** | 1) 在 `.claude/scripts/status.py` 写 StatusLine 脚本，计算 context% 写 tmpfile。2) 新建 `.claude/hooks/context-threshold-stop.sh`，读 tmpfile，>=85% 输出 block JSON。3) settings.json 注册 Stop hook |
| **Priority** | P0 |
| **Effort** | ~1.5h |
| **Knowledge categories** | Judgment heuristic (85% 阈值), Pitfall memory (等 95% 再处理来不及) |
| **Triple validation** | ✓ Cross-domain (CC-v3 + claudefa.st). ✓ Generative (任何阈值场景). ✓ Exclusive (Stop hook block 是独特机制) → 3/3 |

```python
# Continuous-Claude-v3: auto-handoff-stop.py (core mechanism)
CONTEXT_THRESHOLD = 85

def main():
    data = json.load(sys.stdin)
    if data.get('stop_hook_active'):  # anti-recursion
        print('{}'); sys.exit(0)
    pct = read_context_pct_from_file(data)  # reads tmpfile
    if pct and pct >= CONTEXT_THRESHOLD:
        print(json.dumps({
            "decision": "block",
            "reason": f"Context at {pct}%. Run: /create_handoff"
        }))
    else:
        print('{}')
```

| Capability | CC-v3 impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Context % monitoring | StatusLine → tmpfile, every turn | None | **Large** | Steal |
| Threshold gate | Stop hook blocks at 85% | None | **Large** | Steal |
| Anti-recursion | `stop_hook_active` check | N/A | N/A | Include |
| Force handoff | Block + instruct "/create_handoff" | None | **Large** | Steal |

---

**2. PreCompact Sandwich — Transcript-Backed Structured Handoff**

| Field | Content |
|-------|---------|
| **What it does** | 在 compaction 前解析 JSONL transcript，提取任务/工具调用/错误/文件/决策，写成结构化 YAML/MD 交接文档；compaction 后通过 SessionStart(compact) 的 additionalContext 注回 |
| **How it works** | PreCompact hook 读 `input.transcript_path` → `parseTranscript()` 提取结构化数据 → `generateAutoHandoff()` 写文件。SessionStart(compact) 读最新 handoff → `additionalContext` 注入 |
| **Why it's good** | 比我们的"EventsDB 任务 + 日志 dump"更全面——直接从对话记录提取，覆盖工具调用、错误、文件修改、决策。additionalContext 是官方 API，比 stdout 注入更可靠 |
| **How to adapt** | 升级 `pre-compact.sh` → Python 脚本，读 transcript JSONL 提取结构化数据。升级 `post-compact.sh` → 改用 SessionStart(compact) matcher + `additionalContext` 输出 |
| **Priority** | P0 |
| **Effort** | ~2h |
| **Knowledge categories** | Hidden context (transcript_path 是 Claude Code 提供的未文档化字段), Pitfall memory (stdout 注入不如 additionalContext 可靠) |
| **Triple validation** | ✓ Cross-domain (CC-v3, clauditor, Dolan). ✓ Generative ("save before, inject after" 通用). ✓ Exclusive (transcript JSONL 解析 + additionalContext 注入是独特组合) → 3/3 |

```typescript
// Continuous-Claude-v3: transcript-parser.ts (core extraction)
function parseTranscript(transcriptPath: string): TranscriptSummary {
    const lines = readFileSync(transcriptPath, 'utf8').split('\n');
    const summary: TranscriptSummary = {
        todos: [], recentToolCalls: [], recentErrors: [],
        filesModified: [], lastAssistantMsg: ''
    };
    for (const line of lines) {
        const entry = JSON.parse(line);
        if (entry.tool_name === 'TodoWrite') summary.todos = entry.result.todos;
        if (entry.tool_name === 'Edit' || entry.tool_name === 'Write')
            summary.filesModified.push(entry.params.file_path);
        if (entry.tool_name === 'Bash' && entry.result?.exit_code !== 0)
            summary.recentErrors.push(entry.result.stderr?.slice(0, 200));
    }
    return summary;
}
```

```python
# Continuous-Claude-v3: pre_compact_continuity.py (handoff generation)
summary = parse_transcript(Path(transcript_path_str))
handoff_content = generate_auto_handoff(summary, session_name)
handoff_dir = project_dir / "thoughts" / "shared" / "handoffs" / session_name
handoff_dir.mkdir(parents=True, exist_ok=True)
timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
handoff_path = handoff_dir / f"auto-handoff-{timestamp}.md"
handoff_path.write_text(handoff_content)
```

| Capability | CC-v3 impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Transcript JSONL parsing | Full parser (todos, tools, errors, files) | None (reads EventsDB) | **Large** | Steal |
| Handoff structure | 11-field YAML (goal/now/done/blockers/...) | 9-section compact template (prompt, not saved) | **Medium** | Enhance |
| Post-compact injection | SessionStart(compact) → additionalContext | PostToolUse → stdout (flag-based) | **Medium** | Steal |
| Handoff storage | `thoughts/shared/handoffs/{session}/` | `tmp/compaction-snapshots/` | **Small** | Keep ours |

---

**3. StatusLine Context Monitor + Proactive Backup**

| Field | Content |
|-------|---------|
| **What it does** | 用 StatusLine 命令实时显示 context 使用百分比（带颜色），同时作为阈值门控和主动备份的数据源 |
| **How it works** | StatusLine 脚本每轮接收 `context_window` JSON → 计算 `(input_tokens + cache_read + cache_creation + 45K_overhead) / window_size * 100` → 写 tmpfile 供其他 hook 读取 → 显示带颜色的状态栏 |
| **Why it's good** | 单一数据源驱动多个消费者（状态栏 + 阈值门控 + 备份触发）。比我们完全不监控 context 使用率好无限倍 |
| **How to adapt** | 配置 `statusLine` 指向新脚本。脚本计算 context%，写 tmpfile（供 Stop hook 读），输出彩色状态栏。可选：在特定阈值触发备份 |
| **Priority** | P0（是 Pattern 1 的前置依赖） |
| **Effort** | ~1h |
| **Knowledge categories** | Hidden context (StatusLine API 的 context_window 字段), Judgment heuristic (绿<60%/黄60-79%/红>=80%) |
| **Triple validation** | ✓ Cross-domain (CC-v3, claudefa.st). ✓ Generative. ✓ Exclusive (StatusLine→tmpfile→multi-consumer 是独特架构) → 3/3 |

```python
# Continuous-Claude-v3: status.py (core context% computation)
def compute_context_pct(data: dict) -> int:
    cw = data.get('context_window', {})
    usage = cw.get('current_usage', {})
    total = (usage.get('input_tokens', 0)
             + usage.get('cache_read_input_tokens', 0)
             + usage.get('cache_creation_input_tokens', 0)
             + 45000)  # overhead estimate
    window_size = cw.get('context_window_size', 200000)
    return min(100, int(total / window_size * 100))

def write_context_pct(context_pct: int, data: dict) -> None:
    session_id = get_session_id(data)
    tmp_file = Path(tempfile.gettempdir()) / f"claude-context-pct-{session_id[:8]}.txt"
    if tmp_file.exists():
        prev = int(tmp_file.read_text().strip())
        if prev - context_pct > 10:  # compaction detected!
            log_context_drop(session_id, prev, context_pct)
    tmp_file.write_text(str(context_pct))
```

| Capability | CC-v3 + claudefa.st | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Real-time context % display | StatusLine, colored, every turn | None | **Large** | Steal |
| Context % tmpfile (IPC) | tmpfile per session_id | None | **Large** | Steal |
| Compaction detection (drop >10%) | Automatic logging | None | **Medium** | Steal |
| Proactive backup triggers | 50K/10K token intervals | Only at PreCompact | **Medium** | Consider (P1) |

---

**4. PostCompact Identity Health Check**

| Field | Content |
|-------|---------|
| **What it does** | Compaction 后扫描输出，检查 identity marker 是否存活，返回 ALIVE/WEAK/SILENT 三级信号 |
| **How it works** | PostCompact hook 检查压缩后的上下文中是否包含预定义的 identity marker（persona 文件、记忆文件、治理文档关键词）。三级评估：ALIVE（充足）、WEAK（部分存活，建议重载）、SILENT（完全丢失） |
| **Why it's good** | 所有其他方案都是 fire-and-forget——注入后不验证。这是唯一的**闭环验证**。WEAK 信号让系统知道需要更激进的恢复策略 |
| **How to adapt** | 在 `post-compact.sh` 中加入 marker 检查逻辑。定义 Orchestrator 的 identity marker 列表（Orchestrator 名字、损友、roast first 等关键词），检查 compaction 后是否存在。WEAK/SILENT 时注入完整 identity 包 |
| **Priority** | P0 |
| **Effort** | ~1h |
| **Knowledge categories** | Unique behavioral pattern (验证型防御 vs fire-and-forget), Pitfall memory (不验证=不知道丢了什么) |
| **Triple validation** | ✓ Cross-domain (clauditor primary, CC-v3 的 session-outcome 是类似反馈机制). ✓ Generative (任何有损操作后都应验证). ✗ Exclusive partial (ALIVE/WEAK/SILENT 分级是独特的，但"检查存活"本身不独特) → 2/3, P0 with caveat |

| Capability | clauditor | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Post-compact verification | ALIVE/WEAK/SILENT 三级 | None (fire-and-forget) | **Large** | Steal |
| Adaptive recovery intensity | WEAK → partial reload, SILENT → full reload | Fixed payload every time | **Medium** | Steal |
| Identity marker definition | Persona files, memory files, governance docs | None | **Large** | Define |

---

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Agent Output File Isolation** | Agent 写 `.claude/cache/agents/{name}/latest-output.md`，主会话读文件而非接收 transcript。7 天自动清理 | 修改 agent dispatch 模板，要求输出到文件。减少 TaskOutput 使用 | ~3h |
| **TLDR Read Gate** | PreToolUse:Read hook 拦截大文件读取，替换为 TLDR 摘要。从源头减少 context 污染 | 需要 TLDR daemon 或类似摘要服务。可用 Ollama 本地模型实现简化版 | ~4h |
| **Session Affinity via Terminal PID** | SQLite 存 `terminal_pid → session_name`，跨 /clear 后加载正确会话的 handoff | 加入 session-start.sh，用 `$PPID` 链追溯 terminal PID | ~2h |
| **Ledger Pruning** | 每次加载 handoff/ledger 时删除旧条目，agent 报告最多 10 个。防止状态文件膨胀 | 在 session-start.sh 加 snapshot 清理逻辑，保留最近 5 个 | ~1h |
| **Token-Based Proactive Backup** | 50K 起步每 10K token 触发备份，百分比阈值兜底 | 在 StatusLine 脚本中加 token 阈值判断，触发备份到 `tmp/compaction-snapshots/` | ~2h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **PostgreSQL Session Registry** | CC-v3 在 PG 中注册会话，显示同项目的 peer session | 单用户场景 overkill，SQLite 足够 |
| **Braintrust Tracing Pipeline** | 每个 hook 事件 → Braintrust span → session-end 学习提取 | 我们有 EventsDB + growth_loops，架构不同但功能覆盖 |
| **Multi-session Tool Broadcast** | PreToolUse 广播工具意图给其他会话，防冲突 | 需要 IPC 基础设施，当前不需要多会话协调 |
| **compactPrompt 设置** | settings.json 里 `"compactPrompt"` 自定义压缩指令 | 我们已用 PreCompact hook 注入 compact_template.md，效果相同 |

---

## Comparison Matrix

### Orchestrator vs Continuous-Claude-v3 vs claudefa.st — 层对层

| 维度 | Orchestrator (当前) | Continuous-Claude-v3 | claudefa.st | Gap |
|------|-------------------|---------------------|-------------|-----|
| **Context 监控** | 无 | StatusLine → tmpfile, 彩色显示 | StatusLine → JSON state file | **Critical** |
| **阈值门控** | 无 | Stop hook @ 85%, block + instruct | 30%/15%/5% 百分比提醒 | **Critical** |
| **PreCompact 内容** | EventsDB 任务 + 日志 dump + 行为检查点 + compact 模板 + persona | Transcript JSONL 解析 → 11-field YAML handoff | Emergency backup to .md | **Medium** |
| **PostCompact 注入** | PostToolUse flag → stdout (<500 token identity) | SessionStart(compact) → additionalContext (full handoff) | PostCompact → DB query → additionalContext | **Medium** |
| **Handoff 存储** | `tmp/compaction-snapshots/` (flat) | `thoughts/shared/handoffs/{session}/` (session-scoped) | `.claude/backups/` (numbered) | **Small** |
| **Session affinity** | 无（抓最新 snapshot） | Terminal PID → SQLite → session name | JSON state file per session | **Medium** |
| **Agent output 隔离** | 无（agent output 进 context） | 文件隔离 + 7天清理 | N/A | **Medium** |
| **读取门控** | 无 | TLDR Read Gate (大文件 → 摘要) | N/A | **Medium** |
| **Compaction 检测** | 无（不知道 compaction 发生了） | context% drop >10% → log | StatusLine state tracking | **Large** |
| **验证/反馈** | 无 | session-outcome (用户标记) | N/A | **Medium** |
| **状态 IPC** | `/tmp/orchestrator-state/` flag files (R50) | tmpfile per session_id | JSON state file | Even |
| **Persona 保持** | PreCompact anchor + PostToolUse re-inject | Handoff includes session context | N/A | Even |

---

## Gaps Identified

### Gap 1: 完全没有 Context 使用率监控 (Context / Budget)

**当前状态**: 对 context 使用率完全无感。不知道用了多少、还剩多少、什么时候会触发 compaction。

**影响**: 被动挨打——compaction 突然发生，PreCompact 被迫紧急保存，质量取决于那一刻能抓到什么。

**补法**: StatusLine context monitor (P0-3)

### Gap 2: 没有预防式阈值门控 (Security / Governance)

**当前状态**: 没有在 compaction 发生前拦截并引导行为的机制。

**影响**: 一旦 context 达到自动压缩阈值，有损压缩直接执行。没有"提前交接"的机会。

**补法**: Context Threshold Stop Gate (P0-1)

### Gap 3: PreCompact 不读 transcript (Memory / Learning)

**当前状态**: `pre-compact.sh` 只从 EventsDB 读任务和日志，不解析对话 transcript。

**影响**: 丢失对话中的工具调用记录、具体错误信息、文件修改路径、决策推理。这些只存在于 transcript 中。

**补法**: Transcript-Backed Structured Handoff (P0-2)

### Gap 4: PostCompact 注入不可靠 (Failure / Recovery)

**当前状态**: `post-compact.sh` 依赖 PostToolUse 事件触发。如果 compaction 后用户直接打字且没有工具调用，re-injection 不会触发。

**影响**: 存在注入窗口空洞——compaction 发生了但 identity 没有被恢复。

**补法**: 改用 SessionStart(compact) matcher + additionalContext (P0-2)

### Gap 5: 没有 post-compaction 验证 (Quality / Review)

**当前状态**: 注入后不检查是否成功。Fire-and-forget。

**影响**: 不知道 compaction 后 identity/rules 是否真的存活。可能丢了都不知道。

**补法**: PostCompact Identity Health Check (P0-4)

---

## Adjacent Discoveries

### 1. `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 环境变量

未广泛文档化的 Claude Code 配置项，值 1-100，直接控制自动压缩触发百分比。默认约 83.5%（考虑 33K buffer 后）。设为 95-100 可延迟 compaction。

**适用场景**: 短期紧急任务不想被打断时，临时设为 99 禁止自动压缩。

### 2. `/model sonnet[1m]` — 1M token 窗口

Sonnet 支持 1M context window（无额外费用），将 compaction 触发点推到 ~835K token。对于长 session 研究型任务，这可能比任何 compaction 防御都有效。

### 3. Dicklesworthstone/post_compact_reminder

30 行 shell 脚本，PostToolUse hook 检测 compaction 后注入 "re-read AGENTS.md" 提醒。最简解决方案。我们的 post-compact.sh 已经比这复杂得多。

### 4. Compression Monitor (agent-morrow)

测量"ghost lexicon"和"behavioral fingerprints"来检测多次 compaction 后的行为漂移。这不是修复——是**量化损失**。可能对评估我们的 compaction 防御有效性有用。

### 5. Amp 的"无自动压缩"哲学

Sourcegraph 的 Amp 完全不做自动压缩，只提供手动 Handoff + Fork + Thread References。哲学：**context window 里的每一个 token 都影响输出**，自动压缩必然引入不可控的行为变化。这是所有方案中最激进的立场。

---

## Meta Insights

### 1. 预防 > 抢救 > 持久化——但几乎所有人都从抢救开始

R56 调查的 50+ 仓库中，只有 CC-v3 和 claudefa.st 实现了预防层。绝大多数（包括我们）都是 PreCompact/PostCompact 抢救派。这是因为 PreCompact hook 在 Claude Code 中最早可用，而 StatusLine API 的 context_window 字段是后来才有的。但现在该跳级了。

### 2. Stop hook block 是物理拦截——这是与所有 prompt-level 防御的本质区别

`{"decision":"block"}` 不是"请不要继续"，是"你不能继续"。Claude 无法通过推理绕过它。这和 CLAUDE.md 里写"85% 时请交接"有本质区别——prompt 级指令在压力下会被忽略，物理拦截不会。

### 3. 两跳架构揭示了 hook 系统的组合性

CC-v3 的 status.py → tmpfile → auto-handoff-stop.py 不是因为懒才分成两个脚本——是因为 StatusLine 和 Stop 是不同的 hook 事件，不能直接共享状态。tmpfile 是 cross-hook IPC 的最简实现。我们的 `/tmp/orchestrator-state/` flag 系统（R50 Caveman steal）已经有这个基础设施。

### 4. Transcript JSONL 是被低估的金矿

Claude Code 通过 `input.transcript_path` 提供当前会话的完整 JSONL transcript。这意味着 PreCompact hook 可以访问**完整对话历史**——不只是能看到的 context，而是包括已经被压缩掉的部分（如果之前没压缩过）。这比任何 prompt-level 保存策略都强，因为你拿到的是原始数据，不是 LLM 摘要。

### 5. Context compaction 的终极解决方案不是防御——是避免

1M token 窗口、session 分段（30-60 分钟）、TLDR read gate、agent output 文件隔离——这些不是 compaction 防御，是**减少 context 消耗速率**的手段。如果 context 消耗速率足够低，compaction 永远不会触发。真正的策略是：降低消耗速率（TLDR gate, agent isolation）+ 延迟触发阈值（1M window, AUTOCOMPACT_PCT_OVERRIDE）+ 优化压缩（compact template）+ 防御性验证（PostCompact health check）的四层组合。
