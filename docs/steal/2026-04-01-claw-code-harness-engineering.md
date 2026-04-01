# Round 28: instructkr/claw-code — Claude Code Harness 逆向工程

> **Source**: https://github.com/instructkr/claw-code
> **Author**: Sigrid Jin (instructkr)
> **Star**: 30K+（据称史上最快达到 30K star 的 repo）
> **Date**: 2026-04-01
> **Nature**: Claude Code agent harness 的 Python clean-room 重实现 + Rust 重写

## TL;DR

一个韩国开发者在 Claude Code 源码曝光后，用 25B tokens 研究后做的 Python 逆向工程项目。核心价值不在于"又一个 CLI"，而在于它**把 Claude Code 的内部 harness 架构拆解成了可学习的模式**：快照注册表、token 路由、权限推断、会话持久化、多 turn 循环。Rust 重写分支更进一步，引入了层级配置深度合并、trait-based 权限、泛型 agentic loop。

---

## Architecture Overview

```
Python (main branch)                    Rust (dev/rust branch)
┌─────────────────┐                    ┌──────────────────────────┐
│  main.py (CLI)  │                    │  rusty-claude-cli (bin)  │
│  ├─ argparse    │                    │  ├─ app.rs (loop)        │
│  └─ flat dispatch│                   │  ├─ render.rs (markdown) │
├─────────────────┤                    │  └─ spinner (braille)    │
│  runtime.py     │                    ├──────────────────────────┤
│  ├─ route_prompt│                    │  runtime (crate)         │
│  ├─ bootstrap   │                    │  ├─ conversation.rs      │
│  └─ turn_loop   │                    │  ├─ permissions.rs       │
├─────────────────┤                    │  ├─ config.rs (3-tier)   │
│  QueryEngine.py │                    │  ├─ session.rs           │
│  (routing facade)│                   │  ├─ bash.rs              │
├─────────────────┤                    │  └─ file_ops.rs          │
│  commands.py    │                    ├──────────────────────────┤
│  tools.py       │                    │  commands (crate)        │
│  (snapshot load) │                   │  tools (crate)           │
├─────────────────┤                    ├──────────────────────────┤
│  models.py      │                    │  api (crate)             │
│  (frozen DC)    │                    │  ├─ SSE streaming        │
└─────────────────┘                    │  └─ exponential backoff  │
                                       ├──────────────────────────┤
                                       │  compat-harness (crate)  │
                                       │  (upstream fact extraction)│
                                       └──────────────────────────┘
```

---

## Patterns Extracted

### P0 — 直接可偷，填补结构性缺口

#### 1. Snapshot-Based Immutable Registry
**What**: Commands 和 Tools 从 JSON 快照文件加载，`@lru_cache(maxsize=1)` 缓存，返回 `tuple` 而非 `list`。

```python
@lru_cache(maxsize=1)
def load_command_snapshot() -> tuple[PortingModule, ...]:
    raw_entries = json.loads(SNAPSHOT_PATH.read_text())
    return tuple(
        PortingModule(name=e['name'], responsibility=e['responsibility'],
                      source_hint=e['source_hint'], status='mirrored')
        for e in raw_entries
    )
PORTED_COMMANDS = load_command_snapshot()  # 模块级常量
```

**Why it matters**: 我们的 Governor 和 Executor 每次启动都重新发现 tools/commands。快照模式意味着启动成本 = 一次 JSON parse，之后全程不可变。

**Steal target**: Governor 的 tool/command 注册表改为快照加载 + 启动缓存。

**Priority**: P0 | **Effort**: S

---

#### 2. Token-Based Prompt Routing with Scoring
**What**: 用户输入 tokenize 后，对每个 command/tool 的 name、source_hint、responsibility 做 token 命中计数评分。

```python
def route_prompt(self, prompt: str, limit: int = 5) -> list[RoutedMatch]:
    tokens = {t.lower() for t in prompt.replace('/', ' ').replace('-', ' ').split() if t}
    by_kind = {
        'command': self._collect_matches(tokens, PORTED_COMMANDS, 'command'),
        'tool': self._collect_matches(tokens, PORTED_TOOLS, 'tool'),
    }
    # Phase 1: 每种至少选一个
    selected = []
    for kind in ('command', 'tool'):
        if by_kind[kind]:
            selected.append(by_kind[kind].pop(0))
    # Phase 2: 按分数填充剩余
    leftovers = sorted([m for ms in by_kind.values() for m in ms],
                       key=lambda x: (-x.score, x.kind, x.name))
    selected.extend(leftovers[:max(0, limit - len(selected))])
    return selected[:limit]
```

**Key insight**: 两阶段选择——先保证每种类型至少一个命中（diversity guarantee），再按分数排序。防止所有 top-N 都是同一种类型。

**Steal target**: 三省六部的工单路由可以借鉴 diversity guarantee 模式——先保证每个部至少分到一个候选，再按 score 填充。

**Priority**: P0 | **Effort**: M

---

#### 3. Permission Denial Inference (Pre-execution Gate)
**What**: 在 routing 阶段就推断哪些 tool 会被拒绝，而不是等到执行时才报错。

```python
def _infer_permission_denials(self, matches: list[RoutedMatch]) -> list[PermissionDenial]:
    denials = []
    for match in matches:
        if match.kind == 'tool' and 'bash' in match.name.lower():
            denials.append(PermissionDenial(
                tool_name=match.name,
                reason='destructive shell execution remains gated'
            ))
    return denials
```

**Why**: 带着 denial 信息提交给 engine，engine 可以在生成回复时告知用户"这个我没权限做"，而不是静默失败。

**Steal target**: Governor dispatch 时，pre-scan 工单中的操作权限，附带 denial 列表发给 executor。

**Priority**: P0 | **Effort**: S

---

#### 4. Hierarchical Config with Deep Merge (Rust)
**What**: 三层配置——用户级 `~/.claude/settings.json` → 项目级 `.claude/settings.json` → 本地级 `.claude/settings.local.json`，递归深度合并。

**Why**: 我们的 `.env` + `docker-compose.yml` 是扁平覆盖。深度合并意味着项目可以只覆盖特定字段而不丢失用户级默认值。

**Steal target**: Orchestrator 配置系统引入分层合并，SOUL 配置（身份/语气/规则）和项目配置（采集器/调度）分离。

**Priority**: P0 | **Effort**: M

---

### P1 — 值得偷，但需要适配

#### 5. Agentic Loop with Max Iterations
**What**: Rust 的 `ConversationRuntime` 用泛型 `<C, T>` (Client, ToolExecutor) 实现 agentic loop，硬上限 16 iterations/turn。

```
Loop: request → API stream → message aggregation → tool detection →
      permission check → execution → feedback → (repeat until stop or max)
```

**Relevance**: 我们的 Agent SDK executor 没有明确的 iteration cap。一个跑飞的 tool loop 可以烧掉大量 tokens。

**Steal target**: Executor 加 `max_tool_iterations` 参数（默认 16），超限时 force-stop + 报告。

**Priority**: P1 | **Effort**: S

---

#### 6. History Log Milestone Pattern
**What**: Session 执行过程中，每个阶段写一条结构化 history：

```python
history.add('context', f'python_files={ctx.python_file_count}, archive_available={ctx.archive_available}')
history.add('registry', f'commands={len(PORTED_COMMANDS)}, tools={len(PORTED_TOOLS)}')
history.add('routing', f'matches={len(matches)} for prompt={prompt!r}')
history.add('execution', f'command_execs={len(cmd_execs)} tool_execs={len(tool_execs)}')
history.add('turn', f'commands=... tools=... denials=... stop={stop_reason}')
history.add('session_store', persisted_path)
```

**Why**: 比我们的 `events.db` 粒度更细——每个 session 内部的 routing/execution/turn 阶段都有记录，调试时可以精确定位哪个阶段出问题。

**Steal target**: Executor 运行日志加入 phase-level milestones（routing → permission → execution → result）。

**Priority**: P1 | **Effort**: S

---

#### 7. Frozen Dataclass + Immutable Return Convention
**What**: 所有核心模型用 `@dataclass(frozen=True)`，所有集合返回 `tuple` 而非 `list`。`UsageSummary.add_turn()` 不 mutate，而是返回新实例。

```python
@dataclass(frozen=True)
class UsageSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    def add_turn(self, prompt, output) -> 'UsageSummary':
        return UsageSummary(
            input_tokens=self.input_tokens + len(prompt.split()),
            output_tokens=self.output_tokens + len(output.split()))
```

**Why**: 防止运行时意外修改，尤其在多 agent 并发场景。

**Steal target**: Governor 的 WorkOrder / ExecutionResult 模型改为 frozen。

**Priority**: P1 | **Effort**: S

---

#### 8. Compat-Harness: Evidence-Driven Development
**What**: Rust 分支有一个专门的 `compat-harness` crate，作用是：从上游 TypeScript 源码提取可观察事实（command 列表、tool 签名、bootstrap 序列），写成测试，再用 Rust 实现通过这些测试。

**Methodology**:
1. Extract upstream facts → JSON/test fixtures
2. Write tests proving extraction correct
3. Implement Rust equivalent to pass tests
4. Validate parity with `compat-harness` runner

**Relevance**: 我们偷师经常是"看一遍然后凭印象实现"。Compat-harness 模式要求**先把偷来的东西固化为测试**，再实现。

**Steal target**: 偷师工作流加一步——每个 P0 pattern 先写 fixture/test，再实现。

**Priority**: P1 | **Effort**: M

---

### P2 — 有参考价值

#### 9. Streaming Markdown Renderer (Rust)
**What**: CLI 输出用 `pulldown_cmark` 事件解析 + `syntect` 语法高亮，支持逐词输出（8ms 延迟）和 braille spinner 动画。

**Relevance**: Dashboard 的 Markdown 渲染可以参考，但不是当前瓶颈。

**Priority**: P2 | **Effort**: L

---

#### 10. Archived Subsystem Placeholder Pattern
**What**: 不再使用的模块不删除，而是替换为轻量 placeholder package，从 JSON 加载元数据，暴露 `ARCHIVE_NAME`, `MODULE_COUNT`, `SAMPLE_FILES`。

```python
# archived_subsystem/__init__.py
# Loads metadata from reference_data/subsystems/hooks.json
# Exposes: ARCHIVE_NAME, MODULE_COUNT, SAMPLE_FILES, PORTING_NOTE
```

**Why**: 保留历史上下文，新开发者能知道"这里曾经有什么"。

**Relevance**: 我们的 `.trash/` 模式更直接，但 placeholder 模式在需要保持 import 兼容性时有用。

**Priority**: P2 | **Effort**: S

---

#### 11. Multi-Dimensional Tool Filtering Pipeline
**What**: Tool 检索支持 5 维过滤：query string → simple_mode → MCP inclusion → permission context (deny-tool + deny-prefix) → limit。

```python
def get_tools(simple_mode=False, include_mcp=True, permission_context=None):
    tools = list(PORTED_TOOLS)
    if simple_mode:
        tools = [m for m in tools if m.name in {'BashTool', 'FileReadTool', 'FileEditTool'}]
    if not include_mcp:
        tools = [m for m in tools if 'mcp' not in m.name.lower()]
    return filter_tools_by_permission_context(tuple(tools), permission_context)
```

**Relevance**: Governor 的 tool 选择目前是全量注入。按场景过滤（simple mode 只给基础 tool）可以降低 context 占用。

**Priority**: P2 | **Effort**: M

---

#### 12. Exponential Backoff with Status Code Classification (Rust)
**What**: API client 对 408/409/429/5xx 自动重试，200ms-2s 指数退避。

**Relevance**: 我们的 Agent SDK 调用已有重试，但分类粒度不如这个细。记下备查。

**Priority**: P2 | **Effort**: S

---

## Cross-Cutting Observations

### 与我们的差距分析

| 维度 | claw-code | Orchestrator | Gap |
|------|-----------|-------------|-----|
| Tool 注册 | 快照 + LRU 缓存 | 每次动态发现 | 启动性能 |
| Prompt 路由 | Token scoring + diversity | Governor 规则路由 | 路由智能度 |
| 权限 | Pre-execution inference | Post-execution guard | 反馈时机 |
| 配置 | 3-tier deep merge | 扁平 .env | 灵活性 |
| 不可变性 | frozen DC everywhere | 可变对象 | 并发安全 |
| Tool loop | Max 16 iterations | 无上限 | 失控风险 |
| 历史 | Phase-level milestones | Event-level DB | 调试粒度 |

### 最值得偷的不是代码，是方法论

claw-code 最大的贡献不是具体实现，而是 **compat-harness 方法论**：
1. 从目标系统提取可观察事实
2. 固化为 JSON fixtures + 测试
3. 实现到测试通过
4. 用 harness 验证一致性

这比我们的"看一遍 → 凭印象偷"要严谨得多。

---

## Implementation Roadmap

### Phase 1: Quick Wins (本周)
- [ ] P0-1: Governor tool 注册表快照化（JSON + LRU）
- [ ] P0-3: Governor dispatch 加 permission denial pre-scan
- [ ] P1-5: Executor 加 `max_tool_iterations=16`

### Phase 2: Architecture Upgrade (本月)
- [ ] P0-2: 六部路由引入 diversity guarantee
- [ ] P0-4: 配置系统分层（SOUL / project / local）
- [ ] P1-6: Executor 日志加 phase-level milestones

### Phase 3: Methodology (持续)
- [ ] P1-8: 偷师工作流加 compat-harness 步骤
- [ ] P1-7: 核心模型 frozen 化

---

## Summary

| Priority | Count | Key Themes |
|----------|-------|------------|
| P0 | 4 | 快照注册表、diversity 路由、权限预推断、分层配置 |
| P1 | 4 | 迭代上限、里程碑日志、不可变模型、证据驱动开发 |
| P2 | 4 | 流式渲染、归档占位、多维过滤、指数退避 |
| **Total** | **12** | |

**一句话**: claw-code 是 Claude Code 内部架构的解剖教材。技术层面最值得偷的是快照注册表和 diversity 路由；方法论层面最值得偷的是 compat-harness 的"先固化事实再实现"范式。
