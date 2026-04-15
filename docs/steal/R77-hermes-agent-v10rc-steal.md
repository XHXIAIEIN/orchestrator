# R77 — Hermes Agent v1.0-rc Steal Report

**Source**: https://github.com/NousResearch/hermes-agent | **Stars**: 87.5K | **License**: MIT
**Date**: 2026-04-15 | **Category**: Complete Framework (follow-up to R48 v0.8, R59 v0.9, R71 v1.0-dev)
**自 R71 起**: 90+ commits · 136 files changed · +11,241/-1,704 lines
**run_agent.py**: ~10,900 lines (微增)

---

## TL;DR

R71 判断 Hermes 在"打磨期"——错了。24 小时后的 90 个 commit 证明 v1.0-rc 是一次系统级加固：**compressor 反抖动 + gateway 自愈 + 代理转发架构 + 供应链安全**。核心趋势：从"堆功能"转向"确保已有功能在极端条件下不崩"。

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

## 六维扫描

### 维度 1：执行/编排（40%）

**Compressor v3 — Anti-Thrashing + Smart Collapse + Tool Dedup**

这是本轮最重要的架构升级。三层防护链：

**Layer A — Anti-Thrashing（反抖动）**：

```python
# context_compressor.py:307-326
def should_compress(self, prompt_tokens):
    if tokens < self.threshold_tokens:
        return False
    # 连续 2 次压缩各省 <10% → 停止压缩
    if self._ineffective_compression_count >= 2:
        logger.warning(
            "Compression skipped — last %d compressions saved <10%% each.",
            self._ineffective_compression_count,
        )
        return False
    return True
```

压缩后追踪 savings_pct：

```python
# :1073-1079
savings_pct = (saved_estimate / display_tokens * 100)
self._last_compression_savings_pct = savings_pct
if savings_pct < 10:
    self._ineffective_compression_count += 1
else:
    self._ineffective_compression_count = 0  # 有效压缩重置计数器
```

同时，LLM summary 失败有分级冷却：
- 无 provider → 600s 冷却（不可能自恢复）
- 网络瞬态错误 → 60s 冷却
- 成功 → 清除冷却

**Layer B — Tool Output Smart Collapse（智能折叠）**：

不是简单截断，而是按工具类型生成信息密度最高的单行摘要：

```python
# _summarize_tool_result():
"[terminal] ran `npm test` -> exit 0, 47 lines output"
"[read_file] read config.py from line 1 (1,200 chars)"
"[search_files] content search for 'compress' in agent/ -> 12 matches"
"[delegate_task] 'Fix the login bug' (3,400 chars result)"
```

覆盖 17 种工具类型 + generic fallback。关键：保留了命令/路径/结果码等结构化信息。

**Layer C — Content Hash Dedup（内容去重）**：

```python
# _prune_old_tool_results() Pass 1:
h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
if h in content_hashes:
    result[i] = {**msg, "content": "[Duplicate tool output — same content as a more recent call]"}
else:
    content_hashes[h] = (i, msg.get("tool_call_id", "?"))
```

从尾部向头部扫描，保留最新一份完整内容，旧的替换为反向引用。阈值：>200 chars 才参与去重。

**额外的 Pass 3**：assistant 消息中的 tool_call arguments（如 write_file 的 50KB content 参数）在保护区外截断到 200 chars。

**Partial Stream Recovery**：

流传输中断后，复用已发送给用户的内容而不是浪费 API call 重试：

```python
# run_agent.py:10274-10291
_partial_streamed = getattr(self, "_current_streamed_assistant_text", "")
if self._has_content_after_think_block(_partial_streamed):
    _turn_exit_reason = "partial_stream_recovery"
    _recovered = self._strip_think_blocks(_partial_streamed).strip()
    final_response = _recovered
    self._response_was_previewed = True
    break
```

**Context Pressure Warnings**：

分级预警系统，85% 橙色 + 95% 红色，带 session 级 dedup（同 tier 不重复报警）+ stale entry 清理：

```python
# run_agent.py:10216-10235
if _compaction_progress >= 0.95: _warn_tier = 0.95
elif _compaction_progress >= 0.85: _warn_tier = 0.85
if _warn_tier > self._context_pressure_warned_at:
    _sid = self.session_id or "default"
    _last = AIAgent._context_pressure_last_warned.get(_sid)
    if _last is None or _last[0] < _warn_tier or (_now - _last[1]) >= cooldown:
        self._emit_context_pressure(_compaction_progress, _compressor)
```

### 维度 2：故障/恢复

**Gateway 五重自愈体系**：

| 机制 | 触发条件 | 行为 |
|------|---------|------|
| **Auto-Continue** | 重启后 history 尾部是 tool result | 注入 system note 让 agent 先处理未完成的 tool 结果 |
| **Stuck-Loop Detection** | 同一 session 在连续 3 次重启时都处于活跃 | 自动 suspend，下次消息 auto-reset |
| **Compression-Exhaustion Reset** | 压缩后仍超 context window | 自动 reset session，通知用户 |
| **Graceful Drain** | `/restart` 命令 | 先通知活跃 session → 等待 drain → 写 `.clean_shutdown` marker |
| **SIGTERM Recovery** | 非正常 SIGTERM（systemd kill） | 非零退出码 → systemd `Restart=on-failure` 自动恢复 |

**Auto-Continue 实现细节**：

```python
# gateway/run.py:8681-8691
if agent_history and agent_history[-1].get("role") == "tool":
    message = (
        "[System note: Your previous turn was interrupted before you could "
        "process the last tool result(s). ...]\n\n" + message
    )
```

**Graceful Drain 的 clean_shutdown marker**：

- 正常 drain 完成 → 写 `.clean_shutdown` 文件
- 下次启动时检测到 marker → 跳过 session suspend（合法重启不需要挂起）
- drain 超时 → 不写 marker → 下次启动挂起未完成 session

**Self-Destruct Prevention**：

```python
# tools/approval.py — regex 阻止 agent 杀自己：
(r'\b(pkill|killall)\b.*\b(hermes|gateway|cli\.py)\b', "kill hermes process"),
(r'\bkill\b.*\$\(\s*pgrep\b', "kill via pgrep expansion"),
(r'\bhermes\s+gateway\s+(stop|restart)\b', "stop/restart gateway"),
```

匹配到的命令进入 approval 队列，需要用户确认。

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

### P0 — 必须偷（4 个）

| Pattern | 机制 | 我们当前状态 | 适配方向 | 工时 |
|---------|------|------------|---------|------|
| **Compressor Anti-Thrashing** | 连续 2 次压缩各省 <10% 时停止压缩 + LLM 摘要失败分级冷却 (60s/600s) | `condenser/` 有 `water_level.py` 控制触发阈值，但无反抖动机制——连续无效压缩会无限循环 | 在 `context_condenser.py` 加 `_ineffective_count` + `should_condense()` 前置检查 | ~1h |
| **Tool Output Smart Collapse** | 17 种工具类型的结构化单行摘要（保留命令/路径/exit code） | `tool_output_pruner.py` 只做 head+tail 截断，丢失结构化信息（"200 chars...20% tail" 不知道跑了什么命令） | 在 pruner 加 `_summarize_tool_result()` 按 tool name 分支生成信息密度最高的摘要 | ~1.5h |
| **Gateway Auto-Continue** | 重启后检测 history 尾部是 tool result → 注入 system note 让 agent 恢复中断工作 | TG bot 重启后 session 从零开始，中断的工作完全丢失 | 在 `bot-tg` session 恢复路径加 tool-result-tail 检测 + system note 注入 | ~1h |
| **Compression-Exhaustion Circuit Breaker** | 压缩耗尽 → 自动 reset session + 通知用户；retry counter 中毒清理 | `context_condenser.py` 无耗尽检测——压缩失败时 agent 以过大 context 重试，循环到 API 报错 | 加 `compression_exhausted` 信号 + 在 executor 中处理 | ~1h |

#### P0 Triple Validation

**Compressor Anti-Thrashing**:
- 跨域复现 ✅: Claude Code 有 context auto-compact，OpenCode 有 compressor cooldown，至少 3 个项目独立实现
- 生成力 ✅: "当压缩节省 <10% 且连续 2 次"→ 预测行为：应停止并建议用户 /new
- 排他性 ✅: 10% 阈值 + 连续 2 次的双条件是特定设计选择，不是"加个 retry limit"
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 踩坑经验（压缩无限循环是真实 prod 问题 #9893）+ 判断直觉（10% 阈值是经验值）= 2 categories

**Tool Output Smart Collapse**:
- 跨域复现 ✅: Claude Code 用 `[tool_result truncated...]`，PraisonAI 用 `_prune()`——但都不按工具类型分支
- 生成力 ✅: 新增工具时可以预测需要什么摘要格式
- 排他性 ✅: 17 种工具类型的特化摘要 + 保留结构化信息（exit code、match count），远超 generic placeholder
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 独特行为模式（按 tool name dispatch 生成摘要）= 1 category

**Gateway Auto-Continue**:
- 跨域复现 ✅: Claude Code 自动压缩时保持 session，Cursor 有 session resume
- 生成力 ✅: 任何"重启后 agent 该怎么恢复"的场景都适用此 pattern
- 排他性 ✅: "检测尾部消息角色"的简单判断 + system note 注入——不是复杂的 checkpoint/replay
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 故障记忆（#4493 是真实用户报告的数据丢失）= 1 category

**Compression-Exhaustion Circuit Breaker**:
- 跨域复现 ✅: Codex 有 context overflow handling，Claude Code 自动 compact
- 生成力 ✅: "当压缩不再有效时"→ 预测行为：应切断循环而非无限重试
- 排他性 ✅: 与 Anti-Thrashing 配合形成双层防护——anti-thrashing 防慢死，circuit breaker 防猝死
- Score: **3/3 confirmed P0**
- Knowledge irreplaceability: 故障记忆（#9893 是 compression-exhaustion infinite loop 的真实 incident）= 1 category

### P1 — 值得做（5 个）

| Pattern | 机制 | 适配方向 | 工时 |
|---------|------|---------|------|
| **Stuck-Loop Session Suspension** | 连续 3 次重启时活跃的 session 自动 suspend，restart-failure counter 持久化到 JSON | TG bot 长期运行时可能遇到——加 restart counter 文件 | ~2h |
| **Gateway Proxy Mode** | `GATEWAY_PROXY_URL` → 本地只做平台 I/O，agent 执行转发到远程 | 允许 Orchestrator 在低配机器上运行 TG bot，agent 跑在 GPU 机器上 | ~4h |
| **Self-Destruct Prevention** | regex 阻止 `pkill hermes`/`hermes gateway stop` 等自杀命令 | Orchestrator agent 有 terminal 权限时可能 kill 自己的 Docker container | ~1h |
| **Namespaced Plugin Skills** | `plugin:skill` 限定名注册，不污染全局 | 我们的 skill 目录已经很拥挤（200+ skills），命名空间可以解耦 | ~2h |
| **Context Pressure Warnings** | 85%/95% 分级预警 + session 级 dedup + stale entry 清理 | 给用户提前感知 context 即将压缩的信号 | ~1h |

### P2 — 仅参考（4 个）

| Pattern | 为何参考 |
|---------|---------|
| **Tool Auto-Discovery via AST** | 用 AST 静态分析找 `registry.register()` 调用，避免 import 副作用。我们的 tool 注册是显式的，暂无需求 |
| **Dynamic Shell Completion** | 递归遍历 argparse 树生成 bash/zsh/fish 补全。Orchestrator 不是 CLI 工具，但如果做 CLI 时可参考 |
| **Credential Pool** | 多凭证轮换 + 冷却。我们 `src/core/credential_pool.py` 已有类似实现 |
| **Partial Stream Recovery** | 流中断后复用已交付内容。依赖流式输出基础设施，当前架构不直接适用 |

---

## 对比矩阵（P0 Patterns）

| 能力 | Hermes 实现 | 我们的实现 | 差距 | 行动 |
|------|------------|-----------|------|------|
| **压缩反抖动** | `_ineffective_compression_count >= 2` + savings <10% 检测 + LLM 摘要分级冷却 | `condenser/water_level.py` 控制触发阈值但无连续无效检测——可能无限循环 | **Large** | 加 anti-thrashing guard |
| **工具输出摘要** | `_summarize_tool_result()` 按 17 种工具类型生成结构化单行摘要 | `tool_output_pruner.py` 头 200 + 尾 20% 固定截断，信息密度低 | **Large** | 加 tool-type-aware collapse |
| **重启自动恢复** | 检测 history[-1].role == "tool" → 注入 system note | TG bot 重启 = session 丢失 | **Large** | 加 session persistence + auto-continue |
| **压缩耗尽熔断** | `compression_exhausted` flag → auto-reset session → 通知用户 | 无检测，压缩失败时以过大 context 重试直到 API 报错 | **Large** | 加 circuit breaker |

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
| **执行/编排** | 我们的 condenser 缺乏反抖动机制（anti-thrashing）和工具类型感知摘要 |
| **故障/恢复** | 缺乏 gateway-level 的多重自愈（auto-continue, stuck-loop, compression-exhaustion）|
| **安全/治理** | Self-destruct prevention 未实现——agent 理论上可以 `docker stop` 自己的 container |
| **上下文/预算** | 无 context pressure 分级预警——用户不知道 context 何时接近压缩阈值 |
| **质量/测试** | N/A（测试覆盖不是 steal 目标）|
| **记忆/学习** | N/A（本轮无新增）|

---

## Adjacent Discoveries

- **Hermes 的 iterative summary update**（`_previous_summary`）让多次压缩时不丢失信息——我们的 condenser 每次从零摘要，可能丢失早期压缩的关键信息
- **`SUMMARY_PREFIX` 的 prompt 设计**值得研究：明确告知模型"这是参考不是指令"+"不要回答摘要中的问题"+"不要重复已完成的工作"——是反摘要幻觉的实战模板
- **`.clean_shutdown` marker 模式**是通用的——任何需要区分"正常停止"和"异常崩溃"的长运行进程都能用

---

## Meta Insights

1. **v1.0 的真正含义是"极端条件不崩"**: Hermes 从 v0.6 到 v1.0 的演进不是功能增长——是把每一个"偶尔崩一下"变成"自动恢复"。五重自愈体系（auto-continue, stuck-loop, compression-exhaustion, graceful drain, SIGTERM recovery）是这个思路的产物。

2. **反抖动是压缩系统的必经之路**: 任何 lossy compression 系统最终都会遇到"压缩收益递减到无限循环"的问题。Hermes 用简单的计数器+阈值解决了——不需要复杂的自适应算法。我们的 condenser 也该有这个防护。

3. **工具摘要的信息密度比截断重要**: `[terminal] ran npm test -> exit 0, 47 lines` 比 `200 chars...20% tail` 提供了更多可操作的上下文。模型可以根据这个决定"是否需要重新读取完整输出"——而固定截断让模型无法判断。

4. **Gateway 作为"弹性层"的架构定位**: Hermes 把所有恢复逻辑放在 gateway 而非 agent loop 里。原因：agent loop 可能就是崩溃的原因（context overflow → 无法运行 recovery logic）。把恢复逻辑放在 agent 外面，才能在 agent 崩溃时恢复 agent。

5. **Self-destruct prevention 是 agent 安全的基线**: 当 agent 有 terminal 权限时，`pkill` 自己的进程是一个真实风险（#6666 是真实 issue）。regex 阻断虽然粗暴但有效——这是 prompt-level "don't kill yourself" 无法替代的 physical interception。

---

*报告生成：2026-04-15 | 覆盖 commit 范围：16f9d020..e69526be (90+ commits)*
