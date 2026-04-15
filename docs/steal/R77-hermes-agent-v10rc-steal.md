# R77 — Hermes Agent v1.0-rc Steal Report

**Source**: https://github.com/NousResearch/hermes-agent | **Stars**: 87.5K | **License**: MIT
**Date**: 2026-04-15 | **Category**: Complete Framework (follow-up to R48 v0.8, R59 v0.9, R71 v1.0-dev)
**自 R71 起**: 90+ commits · 136 files changed · +11,241/-1,704 lines
**run_agent.py**: ~10,900 lines (微增)

---

## TL;DR

Hermes v1.0-rc 做了一件我们没做的事：**它定义了 agent 的状态是什么。** 压缩模板的 12 个字段（Goal / Completed Actions / Active State / In Progress / Blocked / Key Decisions / Resolved Questions / Pending User Asks / Relevant Files / Remaining Work / Critical Context）不是"一个好的摘要格式"——是 **agent 的 state schema**。这把压缩从"把文字变短"（数据缩减）变成了"从对话中提取状态快照"（状态序列化）。我们的 condenser 还停在前一个范式。

---

## 版本边界说明

| 版本 | Tag | 已覆盖 |
|------|-----|--------|
| v0.7-v0.8 | v2026.3.28 | R48 |
| v0.8-v0.9 | v2026.4.13 | R59 |
| v0.9 → v1.0-dev | v2026.4.13 → 16f9d020 | R71 |
| **v1.0-dev → v1.0-rc** | 16f9d020 → e69526be | **本报告 (R77)** |

---

## 架构总览（v1.0-rc 增量）

```
Layer 5: Web Dashboard
  └── Skills 管理页重写 (SkillsPage.tsx 572 行 diff)
  └── Logs 页重构 (LogsPage.tsx 222 行 diff)

Layer 4: Platform Gateway (+693 lines in gateway/run.py)
  ├── Proxy Mode — 消息转发到远程 API Server [NEW]
  ├── Auto-Continue — 重启后自动恢复中断的 agent 工作 [NEW]
  ├── Stuck-Loop Detection — 连续 3 次重启时活跃的 session 自动挂起 [NEW]
  ├── Compression-Exhaustion Auto-Reset — 压缩耗尽时自动清空 session [NEW]
  ├── Graceful Drain — /restart 先通知活跃 session 再关停 [NEW]
  ├── SIGTERM Auto-Recovery — systemd 非正常退出自动恢复 [NEW]
  ├── Self-Destruct Prevention — regex 阻止 agent kill 自己的 gateway [NEW]
  ├── Matrix 平台支持 (room ID URL-encode) [NEW]
  └── Discord slash command /skill 分类注册 [NEW]

Layer 3: Agent Loop (run_agent.py)
  ├── Compressor v3: anti-thrashing + tool dedup + smart collapse [MAJOR]
  ├── Partial stream recovery — 流中断后复用已交付内容 [NEW]
  ├── Context pressure warnings — 85%/95% 分级提醒 [NEW]
  ├── ASCII API key recovery — 非 ASCII 字符检测+剥离 [NEW]
  └── Stale agent timeout 修复 [FIXED]

Layer 2: Plugin & Tool System
  ├── Namespaced skill registration — plugin:skill 限定名 [NEW]
  ├── Tool auto-discovery via AST — 无需手动 import [NEW]
  ├── MCP server aliases — 显式 toolset 别名 [NEW]
  ├── Dynamic shell completion — bash/zsh/fish 自动同步 [NEW]
  └── Credential pool — 多凭证轮换+冷却 [NEW]

Layer 1: Security
  ├── Supply chain hardening — CI pinning + dep pinning [NEW]
  ├── Dashboard API auth hardening [NEW]
  └── /v1/responses SSE tool events streaming [NEW]
```

---

## 核心发现：压缩 = 状态序列化，不是数据缩减

### 范式对比

Hermes 的 `_template_sections` 定义了 12 个字段。对话历史中的每一条消息都是某个字段值的推导过程——压缩就是"丢掉推导过程，只保留当前值"。

```
我们的 SUMMARIZE_PROMPT:
  "保留关键决策、错误修复、文件修改、最终结果"
  "输出一段连贯中文摘要，不超过 500 字"

Hermes 的 _template_sections:
  12 个具名字段，每个字段有填充标准和示例
  token 预算 = max(2000, min(被压缩内容 × 20%, 12000))
```

|  | 我们 | Hermes |
|---|---|---|
| 压缩是什么 | 把文字变短 | 把对话转化为状态快照 |
| 输出格式 | 自由文本（summarizer 自由发挥） | 12 字段 schema（字段固定，值变化） |
| 迭代更新 | 每次从零摘要 → 前次摘要的信息可能丢失 | 读上次 summary → update 对应字段（`Move items from "In Progress" to "Completed Actions"`） |
| Token 预算 | 硬编码 500 字 | 按内容比例缩放，上限 12K |
| 消费者 | 隐含是同一个 agent | 显式定义为 "a DIFFERENT assistant" |
| 保留标准 | "关键"（主观，每次不同） | 每个字段有明确标准（"include tool used, target, and outcome"） |

### 为什么"DIFFERENT assistant"这个 framing 很重要

Hermes 的 summarizer preamble：

```python
"You are a summarization agent creating a context checkpoint."
"Your output will be injected as reference material for a DIFFERENT assistant"
"Do NOT respond to any questions or requests in the conversation"
```

三层防护：
1. **身份分离**——你是 summarizer，不是对话 agent
2. **消费者分离**——你的输出给"另一个 agent"看，不是给自己看
3. **行为约束**——不准回答对话中的问题

第 2 层改变了 summarizer 的信息保留策略：
- "给自己看" → 省略"自己应该知道的" → **信息以不可预测的方式丢失**
- "给别人看" → 不假设对方知道任何事 → **被迫写明所有必要上下文**

这不是 prompt trick——是对 summarizer 行为的根本性约束。

### Resolved Questions 字段——一个没在任何文档里的设计决策

```
## Resolved Questions
[Questions the user asked that were ALREADY answered —
include the answer so the next assistant does not re-answer them]
```

关键：**包含答案**。如果只记"这个问题已回答"，新 assistant 不知道答案是什么，遇到类似问题可能重新回答——答案可能跟上次不一致。这解决的是**跨压缩的一致性问题**，不是信息密度问题。

### 迭代更新为什么依赖结构化

当 summary 有固定字段时，"更新"是字段级操作：

```
Update the summary using this exact structure.
PRESERVE all existing information that is still relevant.
ADD new completed actions to the numbered list (continue numbering).
Move items from "In Progress" to "Completed Actions" when done.
Move answered questions to "Resolved Questions".
Update "Active State" to reflect current state.
Remove information only if it is clearly obsolete.
```

这些是**状态转换规则**——不是"请更新一下摘要"。每条规则对应一种状态迁移（in_progress → completed, pending → resolved）。

如果 summary 是自由文本，"更新"就退化为"在一段话后面加一段话"。没有结构约束，summarizer 无法精确地"移动"信息——只能重写整段，每次重写都引入信息漂移。

### SUMMARY_PREFIX——注入到模型 context 中的 instruction

```python
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] ...
    treat it as background reference, NOT as active instructions.
    Do NOT answer questions or fulfill requests mentioned in this summary;
    they were already addressed. Respond ONLY to the latest user message
    that appears AFTER this summary. ...avoid repeating it:"
)
```

这段文字被注入到压缩后的 messages 里，**模型每次 inference 都会读到它**。它解决三个问题：
- **幻觉重复**：模型看到 summary 中的"用户问了 X"→ 觉得需要回答 X → 但 X 已经被回答过了
- **指令穿透**：summary 中的"用户要求做 Y"被模型当成新指令执行
- **工作重复**：summary 中的"修改了 config.py"→ 模型再修改一次

三个问题的共同根源：**模型无法区分"历史记录"和"当前指令"**。SUMMARY_PREFIX 是一个硬编码的提示，在模型的注意力中标记这段内容为"只读参考"。

### 对我们的意义

我们的 `LLMSummarizingCondenser` 要做三件事：

1. **定义 state schema**——不是"保留关键信息"，而是定义"agent 的状态由哪些字段组成"，然后让 summarizer 填充这些字段
2. **支持迭代更新**——存储 `_previous_summary`，第二次压缩是 update 而非 rewrite
3. **给压缩结果加 read-only 标记**——防止模型把 summary 当成新指令

---

## 六维扫描

### 维度 1：执行/编排（40%）

**Compressor v3 的 bug 修复——理解为什么单文件架构会产生这些 bug**

Hermes 的 agent loop 有 7 种 retry counter（`_empty_content_retries`, `_thinking_prefill_retries`, `_invalid_tool_retries`, `_invalid_json_retries`, `_incomplete_scratchpad_retries`, `_codex_incomplete_retries`, `_unicode_sanitization_passes`），加上 3 种压缩触发路径（主循环阈值触发、preflight 预压缩、API 413/context overflow 被动触发）。这些状态之间的交互产生了一族组合 bug：

**Bug 1 — Retry Counter 中毒（真正的 root cause）**：

压缩前模型可能已经重试了几次（空响应、thinking-only 响应），`_empty_content_retries` 累积到 2。压缩后 context 变了，模型需要重新适应——但 retry counter 没重置。结果：压缩后第一次空响应直接触发 "too many retries" 退出，用户收到空响应。

```python
# run_agent.py:8042-8050 — 修复：压缩后重置所有 retry counter
# Fix: reset retry counters after compression so the model
# gets a fresh budget on the compressed context.  Without
# this, pre-compression retries carry over and the model
# hits "(empty)" immediately after compression-induced
# context loss.
self._empty_content_retries = 0
self._thinking_prefill_retries = 0
self._last_content_with_tools = None
self._mute_post_response = False
```

**这才是真正的 insight**：不是"加个 counter reset"——而是"当你有 N 个独立状态变量和 M 种触发路径时，在路径切换时（如压缩后）必须清理所有跨路径泄漏的状态"。这是一个状态机卫生问题，不是一个功能问题。

**Bug 2 — 对话历史中毒**：

空响应恢复时，旧代码注入 "Calling the X tools..." 到 assistant message，这段文字被持久化到 session DB。下次加载时模型看到一条自己"说过"但实际没说过的话，开始幻觉。

```python
# run_agent.py:10306 — 修复注释
# Do NOT modify the assistant message content — the
# old code injected "Calling the X tools..." which
# poisoned the conversation history.  Just use the
# fallback text as the final response and break.
```

**教训**：任何向 messages 列表注入内容的操作都可能被持久化到 DB，然后在未来的 session 加载中变成"事实"。这是 stateful agent 的一个固有风险——修改 messages 就是修改 agent 的"记忆"。

**Bug 3 — 压缩后 tool_call/result 配对断裂**：

压缩删除中间 turns 时，可能删掉一个 assistant 的 tool_call 但保留了对应的 tool result（或反过来）。API 拒绝不配对的消息，agent 崩溃。

`_sanitize_tool_pairs()` 的修复不是简单地"删掉孤儿"——它分两种情况处理：
- 孤儿 tool result（call 被删）→ **直接删除**（安全——result 没有对应的 call 就没有上下文意义）
- 孤儿 tool call（result 被删）→ **注入 stub result**: `"[Result from earlier conversation — see context summary above]"` → 保持配对完整性同时指向摘要

更微妙的是 `_align_boundary_backward()`：压缩边界不能切在 tool_call group 中间。如果边界落在连续的 tool result 消息之间，它会向后回退到 parent assistant message，确保整个 call+result group 被完整地压缩或完整地保留。

```python
# _align_boundary_backward():827-859
# Walk backward past consecutive tool results
check = idx - 1
while check >= 0 and messages[check].get("role") == "tool":
    check -= 1
# If we landed on the parent assistant with tool_calls,
# pull the boundary before it so the whole group gets
# summarised together.
if check >= 0 and messages[check].get("role") == "assistant" \
   and messages[check].get("tool_calls"):
    idx = check
```

**Bug 4 — Summary 角色交替冲突**：

压缩后的 summary 需要插入到 head 和 tail 之间，但 OpenAI API 要求消息角色交替（user/assistant 不能连续同角色）。如果 head 末尾是 assistant，summary 不能也是 assistant；如果 tail 开头是 user，summary 也不能是 user。

当两个约束冲突（head 末尾和 tail 开头同角色）时，没有合法的独立角色——解决方案是**把 summary 合并进 tail 的第一条消息**，而不是单独插入：

```python
# :1044-1049
# Both roles would create consecutive same-role messages
# (e.g. head=assistant, tail=user — neither role works).
# Merge the summary into the first tail message instead
# of inserting a standalone message that breaks alternation.
_merge_summary_into_tail = True
```

**这不在任何 README 里。** 这是只有处理过 production edge case 才会发现的问题。

**迭代摘要合并——不是"加个 previous_summary"那么简单**：

第一次压缩用 `_template_sections`（12 个结构化字段：Goal, Constraints, Completed Actions, Active State 等）从零生成摘要。

第二次压缩读取 `_previous_summary`，要求 summarizer **PRESERVE existing info + ADD new progress**。核心 prompt 指令：

```
Update the summary using this exact structure.
PRESERVE all existing information that is still relevant.
ADD new completed actions to the numbered list (continue numbering).
Move items from "In Progress" to "Completed Actions" when done.
Move answered questions to "Resolved Questions".
Update "Active State" to reflect current state.
Remove information only if it is clearly obsolete.
```

**设计张力**：iterative update 比 from-scratch 摘要更保真（信息不会在多次压缩间丢失），但引入了 summary 膨胀风险——如果 summarizer 不够 aggressive，每次 update 只加不删，summary 本身会变得很大。`_SUMMARY_TOKENS_CEILING = 12000` 是硬上限，但 summarizer 可能在上限内就已经丢失信息密度了。

**Summarizer preamble 的 prompt 设计——三层防护**：

```python
# 1. 身份分离：你是 summarization agent，不是对话 agent
"You are a summarization agent creating a context checkpoint."
# 2. 消费者分离：你的输出给"另一个 assistant"看
"Your output will be injected as reference material for a DIFFERENT assistant"
# 3. 行为约束：不准回答问题
"Do NOT respond to any questions or requests in the conversation"
```

第 2 点（"DIFFERENT assistant"）来自 Codex，第 3 点来自 OpenCode。灵感标注在注释里。这不是功能——这是**防止 summarizer 角色混淆**的 prompt 工程。

**`/compress <focus>` 的 token 预算重分配**：

focused compression 不是过滤——是重新分配 summary token budget。focus topic 相关内容获 60-70% budget，其余"brief one-liners or omit"。这比"只保留 focus topic"更聪明——非 focus 内容不完全丢弃，只是压缩更激进。

**LLM Summary 失败的分级冷却——不是"加个 cooldown"**：

关键是失败分类：
- `RuntimeError`（无 provider）→ 600s 冷却。**为什么长？**因为没有 provider 的情况不可能自恢复（用户需要手动配置），短冷却只是白白浪费 should_compress() 的检查。
- `404/503/model_not_found` + summary_model != main_model → **不冷却，立即 fallback 到主模型**。这是 #8620 sub-issue 4：如果你配了一个便宜的 summary model 但它挂了，用主模型兜底比等 600s 好。
- 其他瞬态错误 → 60s 冷却。

三种路径的背后逻辑：**不是所有失败都一样。** 把"retry after X seconds"一刀切是懒设计。

### 维度 2：故障/恢复

**核心发现：五重自愈不是五个功能——是一个有严格时序依赖的状态机**

关键问题不是"有哪五种恢复"，而是"它们之间怎么交互、谁先谁后、冲突时谁赢"。

**时序链：Gateway 关停 → 启动**：

```
关停序列（stop()内部）：
1. _notify_active_sessions_of_shutdown()     ← 通知用户"我要关了"
2. _drain_active_agents(timeout)             ← 等活跃 agent 完成
   ├── 未超时 → 写 .clean_shutdown marker
   └── 超时 → 不写 marker + 强制 interrupt
3. _increment_restart_failure_counts(active_keys)  ← 记录哪些 session 在关停时活跃

启动序列（start()内部）：
4. 检查 .clean_shutdown marker
   ├── 存在 → 跳过 session suspend（正常重启）
   └── 不存在 → 挂起最近活跃的 session
5. _suspend_stuck_loop_sessions()            ← 检查 restart counter
   ├── counter >= 3 → 自动 suspend 该 session
   └── counter < 3 → 保留
6. 收到用户消息时：
   ├── session 未 suspend → auto-continue (检查 history 尾部)
   └── session 已 suspend → auto-reset（清空 history，给用户干净的开始）
```

**设计张力 1 — `.clean_shutdown` marker 解决的是什么？**

没有这个 marker 时：用户执行 `hermes gateway restart` → gateway 正常 drain → 下次启动挂起所有 session → 用户发消息 → session 被 auto-reset → **用户的工作进度丢失**。

marker 让 gateway 区分"我被正常重启了"和"我被意外杀掉了"。只有后者才需要挂起 session。

**但这引入了新风险**：如果 drain 完成但 marker 写入失败（文件系统满/权限问题），下次启动会误判为异常关停，错误地挂起 session。代码用 `try/except pass` 吞掉了这个异常——意味着 marker 丢失时的行为是"保守地挂起"而非"乐观地保留"。这是个正确的 default：误挂起（用户重发消息就恢复）比误保留（session 可能真的卡死了）的代价低。

**设计张力 2 — Auto-Continue 的局限**

Auto-continue 检测的是 `history[-1].role == "tool"`——即 agent 最后一条消息是 tool result，说明 agent 还没处理它就被中断了。

但如果 **context 在中断前已经被压缩**，那个 tool result 可能已经被 summary 吞掉了。此时 history[-1] 可能是 assistant（summary 消息），auto-continue 不会触发——agent 不知道自己有未完成的工作。

Hermes 没有解决这个问题。这是 prompt-injection 式恢复（而非 checkpoint/replay）的固有局限：**你只能恢复你还记得的东西**。

**设计张力 3 — Stuck-Loop Counter 持久化在 JSON 文件里**

为什么不用 SQLite（session store 已经在用了）？因为 stuck loop 的本质是"session 加载本身导致崩溃"——如果 counter 存在 SQLite 里，加载 counter 的代码路径可能就是崩溃的路径。**JSON 文件读取是独立于 session store 的**，即使 DB 损坏了也能读到 counter。

```python
_STUCK_LOOP_THRESHOLD = 3  # 连续 3 次重启时活跃
_STUCK_LOOP_FILE = ".restart_failure_counts"  # 独立于 SQLite

# 成功完成一次 turn 后清零该 session 的 counter
# 这确保 counter 只在"连续"重启时累积
```

**Self-Destruct Prevention — 为什么用 regex 而不是更优雅的方案？**

regex 看起来粗暴，但它是 **physical interception**（在 tools/approval.py 的执行层）。对比 prompt-level "don't kill yourself"：
- prompt-level 依赖模型遵守指令 → 可以被 jailbreak
- regex 在代码层拦截 → 模型无法绕过

更重要的是 regex 覆盖了**间接路径**：`kill $(pgrep ...)` 和 `hermes gateway stop`——不只是直接的 `pkill hermes`。一个不了解自己进程树的 agent 可能无意中执行这些命令（#6666 是真实 issue）。

**Compression-Exhaustion 的完整路径（4 种触发点）**：

`compression_exhausted` 在 run_agent.py 中有 4 处设置——不是 1 处：
1. 主循环 `should_compress()` 后 `len(messages) >= _orig_len`（压缩后消息数没减少）
2. API 返回 413（payload too large）+ 压缩尝试 >= max_compression_attempts
3. Context length error + 压缩尝试 >= max_compression_attempts
4. Context length error + 压缩后 `len(messages) >= original_len`（压缩无效）

4 种路径都返回 `{"compression_exhausted": True, "failed": True}`。Gateway 检查这个 flag 并 auto-reset session。**关键：reset 发生在 gateway 层而非 agent loop 内**——因为 agent loop 可能就是因为 context 太大而无法执行 reset logic。

### 维度 3：安全/治理

**Supply Chain Hardening**：

CI workflow 全面加固：action 版本 pinning（SHA 而非 tag）、依赖版本 pinning、代码层面修复。

**Dashboard API Auth**：commit 99bcc2de — 未认证访问加固，细节在 api_server.py 的 middleware 层。

**API Key ASCII Recovery**：

```python
# 检测非 ASCII 字符（如 UTF-8 BOM、中文引号包裹的 key）
# commit da528a82: strip 非 ASCII → 同步 client.api_key
# commit 5d5d2155: UnicodeEncodeError 恢复路径中同步凭证
```

### 维度 4：插件/工具系统

**Namespaced Skill Registration**：

```python
# hermes_cli/plugins.py
qualified = f"{self.manifest.name}:{name}"
self._manager._plugin_skills[qualified] = {
    "path": path, "plugin": self.manifest.name,
    "bare_name": name, "description": description,
}
```

- 插件 skill 以 `plugin-name:skill-name` 限定名注册
- 不注入 system prompt，不污染用户 skills 目录
- 冒号在 bare name 中被禁止（防歧义）
- 查找链: `find_plugin_skill()` → `list_plugin_skills(plugin_name)`

**Tool Auto-Discovery via AST**：

```python
# tools/registry.py
def _module_registers_tools(module_path: Path) -> bool:
    tree = ast.parse(source)
    return any(_is_registry_register_call(stmt) for stmt in tree.body)

# 只在模块级 AST 检查 registry.register() 调用
# 避免 import 副作用，只导入真正注册了工具的模块
```

**Credential Pool**：

```python
# agent/credential_pool.py
@dataclass
class PooledCredential:
    provider: str; id: str; label: str; auth_type: str
    priority: int; source: str; access_token: str
    refresh_token: Optional[str] = None
```

策略: `fill_first | round_robin | random | least_used`。耗尽凭证冷却 1h（provider 可自定义 `reset_at`）。

**Dynamic Shell Completion**：

```python
# hermes_cli/completion.py — 递归遍历 argparse 树生成补全脚本
def _walk(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for pseudo in action._choices_actions:
                subparser = action.choices.get(pseudo.dest)
                subcommands[pseudo.dest] = _walk(subparser)
```

支持 bash/zsh/fish，profile 名从 `~/.hermes/profiles` 动态读取。

### 维度 5：上下文/预算

**Context Pressure 两级预警**已在维度 1 覆盖。

**Scaled Summary Budget**：摘要 token 预算与被压缩内容成比例（20%），上限 12K tokens，下限 2K tokens。大 context window 模型获得更丰富的摘要。

### 维度 6：质量/测试

新增测试文件 20+，覆盖：
- `test_auto_continue.py` — 重启后自动恢复
- `test_stuck_loop.py` — 卡循环检测
- `test_proxy_mode.py` (445 lines) — 代理模式完整链路
- `test_busy_session_ack.py` (293 lines) — 忙碌 session 响应
- `test_completion.py` (271 lines) — shell 补全生成
- `test_plugin_skills.py` (371 lines) — 命名空间 skill 注册
- `test_credential_pool.py` — 凭证池轮换

---

## 五深度层分析：Compressor v3 反抖动体系

### 调度层 (Orchestration)

`run_agent.py` 主循环在每次 tool call 后检查 `should_compress()`。压缩是同步阻塞的（在 agent loop 内执行），不是异步后台任务。

### 实践层 (Implementation)

三级裁剪流水线：
1. **Pass 1 — Content Hash Dedup**: MD5[:12] 去重，从尾到头扫描
2. **Pass 2 — Smart Collapse**: 按工具类型生成结构化单行摘要（17 种特化 + fallback）
3. **Pass 3 — Argument Truncation**: assistant 的 tool_call.function.arguments > 500 chars 截断

去重 key 是内容 MD5 前 12 位，非 tool name 或 file path——同一文件不同版本不会被去重。

### 消费层 (Consumption)

压缩结果直接替换 `messages` 列表传回主循环。Summary 以 `SUMMARY_PREFIX` 标记，明确告知模型"这是参考，不是指令"。后续 compaction 是迭代的——读取 `_previous_summary` 并 update，不是从零重新摘要。

### 状态层 (State)

反抖动状态全在内存：
- `_ineffective_compression_count: int` — 连续无效压缩计数
- `_last_compression_savings_pct: float` — 上次压缩节省比
- `_summary_failure_cooldown_until: float` — LLM 摘要失败冷却截止时间
- `_previous_summary: str` — 上次摘要文本（迭代更新用）

无持久化——session reset 时归零。这是有意的：持久化反抖动状态会让过期信号影响新对话。

### 边界层 (Boundary)

- Content < 200 chars 跳过去重（避免误判短结果）
- Multimodal content（list 类型）跳过所有裁剪
- 保护区边界：token budget 优先，message count 做下限（向后兼容）
- Summary model fallback: 配置的 summary model 不可用时 fallback 到主模型

---

## Pattern 提取

### P0 — 必须偷（2 个）

| Pattern | 核心 | 我们当前状态 | 适配方向 | 工时 |
|---------|------|------------|---------|------|
| **压缩 = 状态序列化** | 压缩不是"把文字变短"，是"从对话中提取 12 字段的 state snapshot"。结构化 schema 让迭代更新变成字段级操作（而非全文重写）。消费者定义为"DIFFERENT assistant"迫使 summarizer 不省略任何上下文。SUMMARY_PREFIX 在 inference 时标记压缩结果为 read-only，防止模型把历史当指令。 | `LLMSummarizingCondenser`: 自由文本 prompt + 500 字硬编码上限 + 每次从零摘要 + 无 read-only 标记。summarizer 输出的字段/粒度/遗漏每次不同——无法做可靠的迭代更新。 | 1) 定义 Orchestrator 的 agent state schema（基于 Hermes 的 12 字段裁剪出适合我们的版本）2) 改 `SUMMARIZE_PROMPT` 为结构化模板 3) 加 `_previous_summary` 支持迭代 update 4) 加 `SUMMARY_PREFIX` read-only 标记 5) token 预算从 500 字改为 `max(2000, min(内容×20%, 12000))` | ~3h |
| **工具输出语义折叠** | 保留的不是"前 N 个字符"而是"模型做下一步决策需要的信息"：exit code、match count、file path、command。信息选择标准从位置变为语义。Content hash dedup（MD5[:12]从尾到头）消除重复读取同一文件的冗余。 | `tool_output_pruner.py`: 头 200 + 尾 20% 固定截断。头部 200 chars 可能全是 JSON 格式噪音。无 dedup。 | 替换截断逻辑为 tool-type-aware 摘要 + hash dedup | ~1.5h |

#### P0 Triple Validation

**压缩 = 状态序列化**：
- 跨域复现 ✅: 数据库的 WAL checkpoint（不是重放日志，是写 checkpoint）、游戏的 save state（不是录像回放，是状态快照）、VM snapshot（不是录屏，是内存镜像）——**所有高效恢复系统都序列化状态而非压缩历史**
- 生成力 ✅: 任何新的 agent 类型都可以用"定义 state schema → 压缩 = 提取字段值"这个范式。Schema 的字段会变，但范式不变。它还预测了一个我们尚未遇到的问题：当我们做迭代压缩时，自由文本 summary 会产生信息漂移——结构化 schema 是解药
- 排他性 ✅: 不是"用结构化 prompt"——是**改变了压缩的定义**。大多数 agent 框架（包括我们）把压缩当"数据缩减"；Hermes 把压缩当"状态序列化"。这是范式级的差异
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 判断直觉（"DIFFERENT assistant" framing 改变 summarizer 行为）+ 隐性上下文（Resolved Questions 包含答案是为了跨压缩一致性）+ 独特行为模式（12 字段 schema 是 agent 状态的隐式定义）= **3 categories**

**工具输出语义折叠**：
- 跨域复现 ✅: 编译器的 AST（不保留空白和注释，保留语义结构）、日志聚合（不保留每行，保留 count + first/last occurrence）——信息压缩的通用原则是"按消费者需求选择保留什么"
- 生成力 ✅: 新增工具时 pattern 直接指导"保留哪些字段"——exit code for terminal, match count for search, file path for read/write
- 排他性 ✅: 不是"加个 switch-case"——是信息选择标准从"位置"变为"决策相关性"
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 独特行为模式 + 判断直觉 = **2 categories**

### P1 — 值得做（5 个）

| Pattern | 机制 | 适配方向 | 工时 |
|---------|------|---------|------|
| **压缩状态机卫生** | Anti-thrashing（连续 2 次压缩各省 <10% → 停止）+ tool pair sanitize + summary 角色交替 merge-into-tail fallback + 压缩后 retry counter 全量 reset | 我们的 pipeline 天然避免 counter 中毒，但缺 tool pair sanitize 和 role alternation 检查 | ~2h |
| **恢复逻辑外层化** | Gateway 检测 `compression_exhausted` flag → 在 agent 外层 reset session。Auto-continue 检测 `history[-1].role == "tool"` → 注入 system note。Stuck-loop counter 持久化在独立 JSON（不在 SQLite）——因为 DB 可能是崩溃源 | bot-tg 监控 executor 返回值，在 bot 层执行 session reset | ~3h |
| **Self-Destruct Prevention** | regex 在 tools/approval.py 执行层拦截 `pkill hermes` / `kill $(pgrep ...)` / `hermes gateway stop`。Physical interception 而非 prompt-level | 加 regex guard 防止 agent kill 自己的 container | ~1h |
| **Namespaced Plugin Skills** | `plugin:skill` 限定名注册，不注入 system prompt，不污染用户 skills 目录 | 200+ skills 时命名空间可以解耦上下文污染 | ~2h |
| **Context Pressure Warnings** | 85%/95% 两级预警 + session 级 dedup + stale entry 清理 | 让用户预知 context 即将压缩 | ~1h |

### P2 — 仅参考（4 个）

| Pattern | 为何参考 |
|---------|---------|
| **Tool Auto-Discovery via AST** | 用 AST 静态分析找 `registry.register()` 调用，避免 import 副作用。我们的 tool 注册是显式的，暂无需求 |
| **Dynamic Shell Completion** | 递归遍历 argparse 树生成 bash/zsh/fish 补全。Orchestrator 不是 CLI 工具，但如果做 CLI 时可参考 |
| **Credential Pool** | 多凭证轮换 + 冷却。我们 `src/core/credential_pool.py` 已有类似实现 |
| **Partial Stream Recovery** | 流中断后复用已交付内容。依赖流式输出基础设施，当前架构不直接适用 |

---

## 对比矩阵（P0 Patterns）

| 能力 | Hermes | Orchestrator | 差异性质 | 行动 |
|------|--------|-------------|---------|------|
| **压缩范式** | 状态序列化：12 字段 schema + 迭代 update + DIFFERENT assistant framing + SUMMARY_PREFIX read-only 标记 | 数据缩减：自由文本 prompt + 500 字硬编码 + 每次从零摘要 + 无 read-only 标记 | **范式级**——不是"我们的差"，是我们在用不同的范式做同一件事 | 定义 state schema → 改 prompt → 加 iterative update |
| **工具输出压缩** | 语义选择：按 tool type 保留决策相关字段（exit code, match count, file path）+ content hash dedup | 位置选择：头 200 + 尾 20% | **策略级**——同一个范式内的不同策略 | 替换为 semantic collapse + hash dedup |

---

## 路径依赖分析

### Locking Decisions

1. **run_agent.py 10,900 行单文件**: 所有 agent 逻辑集中在一个文件里，任何变更都要在万行文件中导航。但这也意味着状态管理简单——没有跨文件的隐式状态传递。Hermes 选择了"理解难度"换"一致性"。
2. **SQLite 单节点持久化**: session store、restart counter、消息历史全在 SQLite。scalability 受限但部署极简。
3. **sync-first agent loop**: 压缩在主循环内同步执行，不是后台任务。这让状态管理简单，但长时间压缩会阻塞用户响应。

### Missed Forks

- **可以用 checkpoint/replay 而非 system note**: auto-continue 用 prompt injection 而非真正的 checkpoint 恢复。如果 context 已被压缩且丢了关键 tool result，system note 无法恢复那些信息。
- **可以用概率模型而非固定阈值**: 10% savings 和 2 次连续的 anti-thrashing 参数是硬编码的，没有自适应机制。

### Self-Reinforcement

- 87.5K stars + 17 个平台 + 200+ PR 作者 → 社区动量要求向后兼容
- 10,900 行 run_agent.py 是理解门槛 → 新贡献者倾向于加 patch 而非重构
- Gateway 自愈系统越完善 → 越依赖"出问题后修复"而非"预防出问题"

### Lesson for Us

**学他们的 chosen path**: anti-thrashing 和 circuit breaker 是真实 production incident 驱动的设计——比理论上的优雅方案更实用。

**避免他们的 path lock-in**: 不要让单文件膨胀到万行级别。我们的 `condenser/` 拆分成多个 condenser 子模块的架构是更好的选择。

---

## Gaps Identified

| 维度 | 差距描述 |
|------|---------|
| **执行/编排** | 压缩范式差距：我们是数据缩减（自由文本），Hermes 是状态序列化（12 字段 schema）。差距不在代码量——在范式 |
| **上下文/预算** | 三个缺失：1) 无 state schema 定义 2) 无迭代更新（每次从零）3) 无 read-only 标记（模型可能把 summary 当指令）|
| **故障/恢复** | 恢复逻辑在 executor 内部——executor 崩溃时无人恢复 |
| **安全/治理** | Agent 可以 kill 自己的 container（无 physical interception）|
| **质量/测试** | N/A |
| **记忆/学习** | N/A |

---

## Adjacent Discoveries

- **Hermes 的 iterative summary update**（`_previous_summary`）让多次压缩时不丢失信息——我们的 condenser 每次从零摘要，可能丢失早期压缩的关键信息
- **`SUMMARY_PREFIX` 的 prompt 设计**值得研究：明确告知模型"这是参考不是指令"+"不要回答摘要中的问题"+"不要重复已完成的工作"——是反摘要幻觉的实战模板
- **`.clean_shutdown` marker 模式**是通用的——任何需要区分"正常停止"和"异常崩溃"的长运行进程都能用

---

## Meta Insights

1. **压缩的本质是"定义什么是状态"**：Hermes 的 12 字段模板不是"一个好的 prompt"——是 agent state 的 schema definition。一旦你定义了状态是什么，压缩就从"把文字变短"变成"提取字段的当前值"，迭代更新就从"重写段落"变成"状态迁移"（In Progress → Completed），信息保全就从"尽量保留多一点"变成"每个字段都必须有值"。**所有下游的好设计都是这个定义的推论——不是独立的功能。**

2. **"给别人看"改变一切**：summarizer 把消费者定义为 "a DIFFERENT assistant" 而非自己，迫使它不假设对方知道任何事。这个 framing 解决了一个微妙的信息论问题：当 summarizer 和消费者是"同一个人"时，summarizer 会省略"自己应该知道的"信息——但压缩后那些隐性知识已经丢了。"DIFFERENT assistant" 是对 summarizer 说"你不知道对方知道什么"——**这就是 Shannon 的信道模型：假设接收方没有先验知识。**

3. **结构化是迭代更新的前提条件**：自由文本 summary 无法做可靠的迭代更新——"在一段话后面加一段话"不是 update，是 append。只有当 summary 有固定字段时，"更新"才能变成字段级操作。这解释了为什么我们的 condenser 每次从零摘要：**不是因为我们懒得存 previous_summary，而是因为自由文本格式下存了也没用——没有结构可以 diff。**

4. **Generation loss 是迭代压缩的固有风险**：第 3 次压缩的 summary 是 summarizer 对 summarizer 输出的 summarizer 输出的理解。每一层都引入幻觉。Hermes 用结构化模板约束漂移（字段固定，只有值变化），但没有根本解决。真正的解决方案可能是：**把 state schema 从 prompt 提升到代码层**——不让 summarizer 自由生成结构，而是代码提取字段值（类似数据库 checkpoint 而非日志压缩）。这是 Hermes 没走但值得探索的路。

5. **SUMMARY_PREFIX 解决的是一个根本问题：模型无法区分历史和指令**：LLM 的 attention 不区分"这是参考"和"这是要执行的"——一切都是 token。SUMMARY_PREFIX 是一个硬编码的注意力引导，在 inference 层面标记内容为 read-only。这不是 Hermes 特有的问题——任何做 context compression 的 agent 都会遇到模型把 summary 当指令执行的幻觉。我们的 condenser 输出没有这个标记。

---

*报告生成：2026-04-15 | 覆盖 commit 范围：16f9d020..e69526be (90+ commits)*
