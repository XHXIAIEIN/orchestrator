# R71 — Hermes Agent v0.9 → v1.0-dev 深度偷师报告

**Source**: https://github.com/NousResearch/hermes-agent | **Stars**: 80.9K+ | **License**: MIT
**Date**: 2026-04-14 | **Category**: Complete Framework (follow-up to R48 v0.8, R59 v0.9)
**自 v0.9.0 起**: 53 commits · 9475+ PRs total · 最新 commit: Apr 14 2026
**run_agent.py**: 10,871 lines (保持稳定，v0.9 已是此水位)

---

## TL;DR

v0.9 → 当前（v1.0-dev）的核心方向是**质量固化 + 插件安全边界**，不是大规模增功能。主要动作：

1. **pre_tool_call 阻断机制** —— 插件现在能返回 `{"action": "block"}` 来拦截工具调用，完整的 policy-as-plugin 架构终于闭环
2. **流式 think 块过滤** —— GatewayStreamConsumer 加了完整的状态机过滤，MiniMax/Gemma4 的 `<think>` 不再直达 Telegram/Discord
3. **Budget 耗尽修复** —— grace call 逻辑是死代码，修复后 budget 耗尽时统一走 `_handle_max_iterations` 请求摘要
4. **Dashboard 成熟化** —— react-router + sidebar + 响应式布局 + `/api/model/info` 10步上下文长度检测链
5. **QQBot 平台适配** —— 17 番目平台，1960 行，官方 QQ 机器人 API v2，有 Tencent ASR / SILK 解码

其余 48 个 commit 是 bugfix（duplicate Telegram reply、streaming cursor tofu 字符、CI 测试修复）。**没有新的 P0 架构模式**——v0.9 已是成熟期，当前阶段是打磨。

---

## 版本边界说明

| 版本 | Tag | 已覆盖 |
|------|-----|--------|
| v0.7-v0.8 | v2026.3.28 | R48 |
| v0.8-v0.9 | v2026.4.13 | R59 |
| **v0.9 → HEAD** | v2026.4.13 → HEAD | **本报告 (R71)** |

本报告只分析 `v2026.4.13..HEAD` 的 53 个 commit（截至 Apr 14 2026 20:00 UTC），不重复 R48/R59 内容。

---

## 架构总览（当前状态，5层完整版）

```
Layer 5: Web Dashboard (React 19 + react-router + Vite + Tailwind)
  ├── 全页 SPA：Status / Sessions(FTS5) / Analytics / Logs / Cron / Config / Keys / OAuth
  ├── react-router + sidebar layout + sticky header [v1.0-dev NEW]
  ├── /api/model/info：10步上下文长度检测链 + capability badges [v1.0-dev NEW]
  ├── model_context_length 虚拟字段 normalize/denormalize cycle [v1.0-dev NEW]
  └── i18n: en.ts / zh.ts

Layer 4: Platform Gateway (17 platforms: v0.9 16个 + QQBot)
  ├── QQBot (QQ Official Bot API v2) — 1960行，WebSocket + REST [v1.0-dev NEW]
  │   ├── Tencent ASR 优先 → voice_wav_url → SILK→WAV ffmpeg 3级 STT
  │   ├── dm/group/guild 三种消息路径 + allowlist/open policy
  │   └── QQCloseError 携带 close_code 供 reconnect 分类处理
  ├── ignored_threads config for Telegram [v1.0-dev NEW]
  ├── Stream Consumer <think> 状态机过滤 [v1.0-dev NEW]
  ├── 流式 cursor 最小字符防护 (MIN_NEW_MSG_CHARS=4) [v1.0-dev NEW]
  ├── /stop 不再 suspend session（保留会话历史）[v1.0-dev NEW]
  └── duplicate reply 防护 (CancelledError + already_sent flag) [v1.0-dev NEW]

Layer 3: Agent Loop (run_agent.py 10,871 lines)
  ├── Budget 耗尽路径修复 → _handle_max_iterations [v1.0-dev FIXED]
  ├── reasoning effort "minimal" clamp → "low" on Responses API [v1.0-dev FIXED]
  ├── MCP tool wait 支持 interrupt [v1.0-dev FIXED]
  └── 上游 R59 模式保持稳定 (ContextEngine/IterationBudget/FailoverReason 等)

Layer 2: Plugin System (hermes_cli/plugins.py)
  ├── pre_tool_call blocking: {"action": "block", "message": "..."} [v1.0-dev NEW]
  │   ├── get_pre_tool_call_block_message() 集中检查
  │   ├── skip_pre_tool_call_hook=True 防双触发
  │   └── 两条路径都覆盖: model_tools.py + run_agent.py _invoke_tool
  └── 现有 VALID_HOOKS 11个保持稳定

Layer 1: API Server
  ├── X-Hermes-Session-Id header → session continuity [来自 v0.9 pre-release]
  └── CANONICAL_PROVIDERS 单一真实源消除 3 处硬编码 [来自 v0.9 pre-release]
```

---

## 六维扫描

### 维度 1：执行/编排（40% 分析时间）

**budget 耗尽修复（重要的是它是怎么坏的）**

v0.9 之前的 grace call 逻辑是死代码：设 `_budget_grace_call = True` 后 `while` 循环已经退出，flag 永远不会被 consume。结果：budget 耗尽时 `final_response is None`，用户收到空响应。

v1.0-dev 修复（commit `934318ba`）删掉死代码，统一走 `_handle_max_iterations`：

```python
# 修复后的路径 (run_agent.py ~10203)
if final_response is None and (
    api_call_count >= self.max_iterations
    or self.iteration_budget.remaining <= 0
):
    _turn_exit_reason = f"max_iterations_reached({api_call_count}/{self.max_iterations})"
    final_response = self._handle_max_iterations(messages, api_call_count)
```

`_handle_max_iterations` 的实现：把 `tools` 字段剥掉，注入 `"Please provide a final response summarizing what you've found..."` user message，再发一次 API call（toolless），处理 `<think>` 过滤。

**MCP tool interrupt 支持**（commit `e0859088`）：
之前 MCP 工具在等待 server 响应时无法响应 interrupt。修复是在 `_run_on_mcp_loop` 中轮询 `set_interrupt`，通过 `asyncio.cancel()` 取消 awaiting coroutine，抛出 `InterruptedError("User sent a new message")`。

**reasoning effort clamp**（commit `19199cd3`）：
GPT-5.4 Responses API 不支持 `"minimal"` effort，只有 `none/low/medium/high/xhigh`。OpenRouter 惯例允许 `"minimal"`，直接透传会 400。修复：

```python
_effort_clamp = {"minimal": "low"}
reasoning_effort = _effort_clamp.get(reasoning_effort, reasoning_effort)
```

### 维度 2：工具系统

**pre_tool_call 阻断机制**（commit `eabc0a2f`）——这是本轮最重要的新 pattern：

```python
# hermes_cli/plugins.py
def get_pre_tool_call_block_message(
    tool_name: str, args: dict, task_id: str = "", ...
) -> Optional[str]:
    """插件返回 {"action": "block", "message": "reason"} 即可阻断。"""
    hook_results = invoke_hook("pre_tool_call", tool_name=tool_name, ...)
    for result in hook_results:
        if not isinstance(result, dict):
            continue
        if result.get("action") != "block":
            continue
        message = result.get("message")
        if isinstance(message, str) and message:
            return message
    return None
```

关键设计决策：
- **错误格式静默忽略**：不是 dict、或 `action != "block"`、或 `message` 非 str，全部跳过。已有的观察者钩子（只返回 None）不受影响
- **阻断结果送回模型**：blocked tool 返回 `{"error": "Blocked by policy"}` 作为 tool result，让模型自行调整策略
- **双路径覆盖**：`model_tools.py::handle_function_call` + `run_agent.py::_invoke_tool + sequential/concurrent`
- **skip_pre_tool_call_hook=True**：run_agent.py 已检查过不再让 model_tools.py 二次检查

阻断后跳过的副作用：counter reset、checkpoint、read-loop tracker、所有 callbacks。

### 维度 3：内存/上下文

无新增。`/compress <focus>` 和 ContextEngine ABC 都在 R59 已覆盖。

### 维度 4：安全治理

**流式 think 块状态机过滤**（commit `3de2b985`）——防止推理块泄露到平台消息：

```python
# gateway/stream_consumer.py
class GatewayStreamConsumer:
    _OPEN_THINK_TAGS = (
        "<REASONING_SCRATCHPAD>", "<think>", "<reasoning>",
        "<THINKING>", "<thinking>", "<thought>",
    )
    _CLOSE_THINK_TAGS = (...)

    def _filter_and_accumulate(self, text: str) -> None:
        """状态机：_in_think_block + _think_buffer 处理跨 delta 的 tag 边界。"""
        buf = self._think_buffer + text
        self._think_buffer = ""
        while buf:
            if self._in_think_block:
                # 找最早闭合 tag，找不到则保留尾部等下一个 delta
                ...
            else:
                # 只在行边界匹配（防止模型提到 tag 标签名被误过滤）
                # 前面有非空内容的 tag 不算行边界
                ...
```

关键：行边界检查（`idx == 0` 或前导内容 `strip() == ""`）避免误匹配"the `<think>` tag is used for..."。处理了 5 种边界情况：跨 delta 分裂、未闭合块、连续多块、partial tag 缓冲、stream 结束时 flush。

**流式 cursor 孤立消息防护**（commit `b4fcec64`）：

```python
# gateway/stream_consumer.py::_send_or_edit
_MIN_NEW_MSG_CHARS = 4
if (self._message_id is None          # 新消息（非编辑）
        and self.cfg.cursor
        and self.cfg.cursor in text
        and len(_visible_stripped) < _MIN_NEW_MSG_CHARS):
    return True  # 积累后再发，不创建孤立 cursor 消息
```

背景：模型快速 tool-calling 时常在 tool call 前 emit 1-2 token，会产生 `"I ▉"` 消息。后续 rate-limit 时 cursor strip edit 失败，Telegram 上 `▉` 渲染成白色方块（tofu）永久残留。

**duplicate Telegram reply 防护**（commit `0cc7f790`）：
5秒 stream_task timeout 取消时，`CancelledError handler` 未设 `final_response_sent=True`。网关 fall through 到 normal send path 导致重复消息。修复 1 行：
```python
if self._already_sent:
    self._final_response_sent = True
```

**v0.9 pre-release 安全补丁**（覆盖 R59 未包含的部分，已在当前 HEAD 中）：
- 浏览器 URL 泄露：navigate/extract 前扫描 URL 中的 API key pattern（`sk-ant-api03-`、`sk-or-v1-` 等正则）
- 辅助 LLM 响应脱敏：`_extract_relevant_content` 和 vision 调用后 `redact_sensitive_text()`
- `X-Hermes-Session-Id` header 会话连续性（API Server）

### 维度 5：平台/集成

**QQBot 平台（17 番目）**（commit `1acf81fd` 文档，实现在 `v2026.4.13` pre-release）：

```python
# gateway/platforms/qqbot.py — 1960 行
async def _stt_voice_attachment(self, url, content_type, filename,
                                 *, asr_refer_text=None, voice_wav_url=None):
    # 3 级优先：QQ 内置 ASR → voice_wav_url(预转 WAV) → 下载+SILK→WAV
    if asr_refer_text:
        return asr_refer_text  # Tencent 原生 ASR，免费，无 API 调用
    ...
```

设计亮点：
- `dm_policy: open/allowlist/disabled` 三档私信策略
- `group_policy: open/allowlist/disabled` + `group_allow_from` 白名单
- `QQCloseError(code, reason)` 携带 WebSocket close code，reconnect loop 分类处理
- markdown_support: true → `msg_type=2`（QQ 专有 markdown 消息类型）

**Telegram ignored_threads**（commit `2cfd2daf`）：
```yaml
platforms:
  telegram:
    ignored_threads: [12345, 67890]  # Telegram supergroup thread IDs to ignore
```

**CANONICAL_PROVIDERS 单一真实源**（commit `204e9190`，v0.9 pre-release）：
三处各自维护的 provider 列表（/model、/provider、hermes model）产生漂移——有些 provider 只出现在部分命令中。修复：在 `hermes_cli/models.py` 创建 `CANONICAL_PROVIDERS`（`NamedTuple(slug, tui_desc)`），所有命令 derive from 此。同时废弃两层 provider picker，改为单一 flat list。

### 维度 6：测试工程

**E2E 测试基础设施**（v0.9 pre-release，`tests/e2e/`）：
```python
# tests/e2e/conftest.py — 完整的 adapter mock 工厂
# 无需真实 Telegram/Discord 库，动态注入 mock 模块
# 覆盖: /help /status /new /stop /commands /provider slash commands
# 参数化跨平台: @pytest.fixture(params=["telegram", "discord"])
```

关键：`_ensure_telegram_mock()` 在 CI 环境注入 mock `telegram` 模块，不需要安装真实库。测试驱动完整 async pipeline：`adapter.handle_message → GatewayRunner._handle_message → adapter.send`。

**CI 贡献者归因检查**（commit `dd86deef`）：
PR 检查脚本自动验证 `AUTHOR_MAP` 完整性，防止贡献者被遗漏于 changelog。

---

## 五深度层分析：pre_tool_call 阻断机制

> 这是本轮唯一真正新颖的架构 pattern，值得做深度分析。

### Layer 1 — 接口契约

```python
# 插件 register() 里注册：
ctx.register_hook("pre_tool_call", my_policy_check)

# 回调签名：
def my_policy_check(tool_name: str, args: dict, task_id: str,
                    session_id: str, tool_call_id: str) -> Optional[dict]:
    if should_block(tool_name, args):
        return {"action": "block", "message": f"Tool {tool_name} requires approval"}
    return None  # 不阻断
```

### Layer 2 — 分发与聚合

```python
# plugins.py::get_pre_tool_call_block_message
hook_results = invoke_hook("pre_tool_call", ...)
for result in hook_results:
    if isinstance(result, dict) and result.get("action") == "block":
        if isinstance(result.get("message"), str) and result["message"]:
            return result["message"]  # 第一个有效 block 胜出
return None
```

**"第一个有效 block 胜出"策略**：多个插件注册时，顺序有意义。可以用来做分层 policy：快速路径先检查，慢路径（需要网络）在后。

### Layer 3 — 执行路径覆盖

```python
# model_tools.py::handle_function_call (工具调用主路径)
if not skip_pre_tool_call_hook:
    block_msg = get_pre_tool_call_block_message(tool_name, args, ...)
    if block_msg:
        return json.dumps({"error": block_msg})

# run_agent.py::_invoke_tool (agent loop 工具调用)
block_msg = get_pre_tool_call_block_message(tool_name, args, ...)
if block_msg:
    # skip_pre_tool_call_hook=True 传给 handle_function_call
    return ..., json.dumps({"error": block_msg})
```

### Layer 4 — 副作用保护

阻断后跳过的完整列表：
- `tool_usage_counter.reset()` 不调用
- `checkpoint_manager.save()` 不调用
- `read_loop_tracker.notify()` 不调用
- 所有 `tool_progress_callback` 不触发
- 模型收到 `{"error": "..."}` 作为 tool result → 可以选择解释/重试/换策略

### Layer 5 — 适用场景

| 场景 | 实现方式 | 解锁的能力 |
|------|---------|-----------|
| 速率限制 | 插件维护 per-tool 计数器，超额 block | 防止 write_file 过度调用 |
| 审批工作流 | 发消息给管理员，block 直到审批 | 危险操作人工确认 |
| 沙箱限制 | allowlist/denylist tool 名称 | 子代理权限隔离 |
| 审计日志 | observer 模式（不 block，只记录） | 现有用法 |

---

## Pattern 提取（P0/P1/P2）

**重要**：R48 和 R59 已覆盖的 pattern 不再重复。以下仅列 v0.9→HEAD **真正新增**的内容。

### P0 — 必须偷（2个）

| Pattern | 机制 | 我们当前状态 | 适配方向 | 工时 |
|---------|------|------------|---------|------|
| **pre_tool_call 阻断** | 插件返回 `{"action": "block", "message": "..."}` 拦截任意工具；错误格式静默忽略；阻断结果作为 tool result 反馈给模型；双路径覆盖 | `.claude/hooks/` 有 pre/post 钩子但无法阻断工具执行（只能 stop 整个 agent）| Claude Code 的 `PreToolUse` hook 已支持 `{"decision": "block"}`，语义完全对齐。我们的 `guard-redflags.sh` 就是这个 pattern，但只有 exit code——缺少结构化 `{"decision": "block", "message": "reason"}` 格式 | ~1h |
| **Budget 耗尽摘要**（修复版） | 删死代码 grace flag；统一走 `_handle_max_iterations`：剥 tools、注入摘要请求、无工具 API call、过滤 `<think>` | agent dispatch 有 max_turns 但 budget 耗尽时直接截断，没有 graceful summary | 在 Orchestrator 的 agent dispatch 路径加 `_handle_max_iterations` 等效逻辑：tools=None、注入"请总结"、再调一次 API | ~1h |

### P1 — 值得做（3个）

| Pattern | 机制 | 适配方向 | 工时 |
|---------|------|---------|------|
| **Think 块状态机过滤** | `_in_think_block` + `_think_buffer` 处理流式 delta 的 tag 边界；6 种 open/close tag；行边界检查防误匹配；stream 结束 flush | 我们用 Claude（原生不输出 `<think>`），但接入 Gemma/MiniMax 类模型时会遇到 | 接入非 Anthropic 模型时的通用防护，约 50 行状态机 | ~1h |
| **Streaming cursor 孤立消息防护** | `MIN_NEW_MSG_CHARS=4`：新建消息时要求至少 4 个可见字符，否则积累到下一 delta | TG bot 偶尔有 cursor tofu 问题，特别是多 tool call 时 | `bot-tg` 的 stream consumer 加相同防护 | ~30min |
| **CANONICAL_PROVIDERS 单一真实源** | 一个 `NamedTuple` 列表，所有命令（/model、/provider、picker）derive from 此；provider 增减只改一处 | `config/channels.yml` 和代码里 channel 列表分散 | 把 channel 定义集中到一个 registry，所有命令从中 derive | ~1h |

### P2 — 仅参考（3个）

| Pattern | 为何参考 |
|---------|---------|
| QQBot 平台适配 | 1960 行完整实现，QQ 官方 Bot API v2，Tencent ASR 优先。我们暂无 QQ 需求，但 SILK→WAV 转换链（pilk → ffmpeg fallback）值得参考 |
| E2E 测试基础设施 | mock 模块注入 + 完整 adapter pipeline + 跨平台参数化的测试架构，我们加 gateway platform 时可参考 |
| ignored_threads Telegram config | 简单实用，屏蔽 supergroup 特定话题线程，我们有需要时直接抄 |

---

## 对比矩阵（P0 Patterns）

| 能力 | Hermes 实现 | 我们的实现 | 差距 | 行动 |
|------|------------|-----------|------|------|
| Tool 级别阻断 | `get_pre_tool_call_block_message()` → `{"error": "..."}` 反馈模型 | `guard-redflags.sh` exit code 2 → stop 整个 agent | **Medium**：我们能 stop 但无法让模型调整策略 | 加 structured block response |
| Budget 耗尽处理 | `_handle_max_iterations`：剥 tools + 注入摘要 + 额外 API call | max_turns 硬截断，无摘要 | **Medium** | 加 graceful summary path |

---

## 路径依赖分析

Hermes 在 v0.9→v1.0 的演进轨迹揭示了一个清晰的成熟度模式：

**Hermes 的技术债清理路径**：
1. v0.6-v0.7：堆功能（平台、工具、记忆）
2. v0.8：加抽象层（ABC、Plugin hooks）
3. v0.9：打通并发安全（contextvars）、安全加固（8个漏洞）
4. **v1.0-dev**：清死代码（1784行）、修 bug（grace call、duplicate reply）、插件安全边界

**我们的路径依赖**：R48 偷的 Plugin ABC、R59 偷的 contextvars Session Isolation，是 pre_tool_call 阻断的先决条件。如果没有 plugin hook 基础设施，`get_pre_tool_call_block_message` 就无法工作。**顺序重要：先搞基础设施，再加 policy layer。**

当前 Hermes 最活跃的 PR 方向（从 #9000-9543 看）：
- Web Dashboard 功能完整性（model info、OAuth management）
- 测试覆盖（E2E、CI 稳定性）
- 国际化（QQBot、kimi-cn）

**预测下一轮偷师重点**（~1个月后 v1.0 正式发布时）：
- Skills marketplace 完整实现（已有 centralized index）
- ACP 协议多智能体通信成熟（目前 `acp_adapter/` 还在早期）
- 更多 optional-skills（drug-discovery 模式复制到其他领域）

---

## 实施计划（按优先级）

### P0-1：pre_tool_call structured block（~1h）

目标：让 `guard-redflags.sh` 返回结构化原因而不是直接 stop。

```bash
# 当前
exit 2  # stop agent

# 目标（匹配 Claude Code PreToolUse hook 格式）
echo '{"decision": "block", "reason": "Blocked: rm -rf pattern detected"}'
exit 0  # 让 harness 返回 block，模型收到 tool result 中的错误
```

验证：`echo '{"decision": "block", "reason": "test"}' | python -c "import json,sys; d=json.load(sys.stdin); assert d['decision']=='block'"`

### P0-2：Budget 耗尽 graceful summary（~1h）

目标：在 Orchestrator 的 agent 调用路径加 post-loop summary。

涉及文件：检查 `src/` 中调用 Claude API 的主循环，在 `max_turns` 耗尽后加 toolless summary call。

验证：构造一个需要 5 轮但 max_turns=3 的任务，确认收到摘要而不是空响应。

---

## 星级统计与趋势

| 时间点 | Stars | 增量 |
|--------|-------|------|
| v0.6 (R35b) | ~30K | - |
| v0.8 (R48) | 53.9K | +24K |
| v0.9 (R59) | 80.9K | +27K |
| 当前 (R71) | 80.9K+ | 持平（v0.9 发布 24h 内） |

80.9K stars 在 AI agent 框架中属于第一梯队（和 AutoGPT/MetaGPT 同量级）。但增速放缓是正常的——破圈后回归正常增长曲线。

---

*报告生成：2026-04-14 | 覆盖 commit 范围：v2026.4.13..HEAD (53 commits)*
