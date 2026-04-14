# R59 — Hermes Agent v0.9 Steal Report

**Source**: https://github.com/NousResearch/hermes-agent | **Stars**: 80.9K | **License**: MIT
**Date**: 2026-04-14 | **Category**: Complete Framework (follow-up to R48 v0.8, R35b v0.6)
**Since v0.8**: 487 commits · 269 merged PRs · 167 resolved issues · 24 contributors
**run_agent.py**: 10,871 lines (562KB, up from 528KB at v0.8)

## TL;DR

v0.8→v0.9 的核心进化方向：**从单机 CLI 转向全平台运维基础设施**。四大方向：
1. Web Dashboard —— 本地浏览器管理面板，完整 CRUD 所有配置/会话/Cron/技能
2. 安全加固深水区 —— 8 个关键漏洞修复（SSRF 重定向、SMS RCE、Git 参数注入、路径穿越）
3. 并发隔离工程化 —— `contextvars` 替代 `os.environ` 做会话隔离，per-thread 中断信号
4. 训练数据管道 —— 轨迹压缩器从 agent run 到 RL 训练的完整管线

80.9K stars（v0.8 时 53.9K），半个月涨了 27K——这不是渐进增长，是破圈。

## Architecture Overview

```
Layer 5: Web Dashboard (React 19 + Vite + Tailwind)
  ├── 8-page SPA (Status/Sessions/Analytics/Logs/Cron/Skills/Config/Keys)
  ├── Session token auth (secrets.token_urlsafe, CORS localhost-only)
  ├── OAuth flow support (PKCE + Device Code)
  └── Rate-limited env reveal (5 req / 30s)

Layer 4: Platform Gateway (16 platforms: +iMessage, +WeChat, +WeCom)
  ├── contextvars session isolation (替代 os.environ)
  ├── TextBatchAggregator (跨平台入站消息合批)
  ├── Staged inactivity warning (超时前阶梯预警)
  ├── Drain-before-restart (优雅排水 → interrupt → finalize hook)
  ├── Per-platform display tier (4 级: High/Medium/Low/Minimal)
  └── Mid-turn commentary messages (独立于 tool_progress)

Layer 3: Agent Loop (run_agent.py 10.8K lines)
  ├── Context Engine ABC (pluggable slot via hermes plugins)
  ├── Focused compression (/compress <topic> → 60-70% budget 优先)
  ├── watch_patterns (后台进程输出模式匹配 + 防过载 kill switch)
  ├── Truncated tool call detection (1 次重试 → 拒绝执行)
  ├── Error classifier taxonomy (12 种 FailoverReason → 结构化恢复)
  ├── Per-thread interrupt scoping (替代全局 threading.Event)
  ├── IterationBudget (线程安全 consume/refund + grace call 防中途放弃)
  └── Prompt caching: system_and_3 strategy (4 个 Anthropic 断点)

Layer 2: Security Hardening (deepest pass yet)
  ├── SSRF: pre-flight DNS check + per-redirect httpx hook (双层)
  ├── Shell injection: shlex.quote + collision-safe heredoc marker
  ├── Git argument injection: hex-only allowlist + dash-prefix block
  ├── Path traversal: resolve() + relative_to() containment
  ├── SMS RCE: Twilio HMAC-SHA1 签名验证 (constant-time)
  ├── API auth: non-loopback 强制 API_SERVER_KEY (hmac.compare_digest)
  ├── Approval button auth: allowed_users 白名单 + .pop() 单次消费
  └── Interrupt scoping: _interrupted_threads set[int] 替代全局 Event

Layer 1: Training Pipeline
  ├── batch_runner.py (并行轨迹生成, content-hash resume)
  ├── trajectory_compressor.py (turn-level 语义压缩, head/tail 保护)
  └── rl_cli.py (下游 RL 训练消费)
```

## Steal Sheet

### P0 — Must Steal (6 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| contextvars Session Isolation | 7 个 `ContextVar` 替代 `os.environ`，`set_session_vars()` 返回 tokens，finally 中 `clear_session_vars(tokens)` 恢复。落地为 `get_session_env()` 兼容 CLI/cron/gateway 三种入口 | Channel 层无并发隔离，TG/WX 同时来消息可能串会话 | `src/channels/` 并发消息处理需要隔离 context。直接移植此 pattern | ~2h |
| watch_patterns 后台监控 | 后台进程输出按行 substring 匹配，滑动窗口限流（8 次/10s），持续过载 45s 自动 kill watch，通知入 completion_queue | 无后台进程监控能力 | scheduler 长任务（爬取/编译）可复用。关键：防过载的 3 级降级（限流→抑制→永久禁用） | ~3h |
| Truncated Tool Call Detection | 流式响应截断时，给 1 次无痕重试（不 append 坏消息），再截断则拒绝执行 + 回滚到上一个完整 assistant turn | 无此防护，Claude Code 偶尔返回截断 JSON 会直接报错 | Agent dispatch 路径 + 直接 API 调用都需要 | ~1h |
| Error Classifier Taxonomy | 12 种 `FailoverReason` enum + `ClassifiedError` dataclass（含 retryable/should_compress/should_rotate/should_fallback 4 个恢复提示）。集中替代散落的字符串匹配 | llm_router 有基础重试但无分类 | 统一 API 错误处理。关键：billing vs rate_limit vs auth 的区分决定了完全不同的恢复策略 | ~2h |
| Focused Compression | `/compress <topic>` → 60-70% 摘要 token 预算分给 focus topic，其余激进压缩。Prompt injection 在压缩提示末尾（take precedence） | `.remember/` 压缩无 focus 控制 | 对话管理的精细化。长 session 中只关心某个子话题时极有用 | ~1h |
| Anti-Premature-Stop Budget | `IterationBudget` 线程安全计数器 + grace call（耗尽后注入"请总结"再给 1 次 API 调用）。**关键：不警告模型预算快用完**——中间压力警告导致模型提前放弃（#7915） | agent dispatch 有 max_turns 但无 grace call | 长任务（steal/plan）经常在最后一步被截断。加 grace call + 禁止中间预算警告 | ~1h |

### P1 — Worth Doing (6 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| Web Dashboard API 蓝图 | 完整的 REST API 设计：Status/Sessions(FTS5 搜索)/Analytics/Logs/Config(schema-driven+raw YAML)/Cron/Skills/Env/OAuth。Session token auth + CORS localhost | 我们的 dashboard 可参考此 API 设计。8 个页面覆盖日常运维所需 | ~8h (MVP) |
| TextBatchAggregator | 跨平台入站消息合批，adaptive delay（0.6s 短文本 / 2.0s 长文本分割后续），cancel+restart asyncio timer | TG/WX 快速连发消息时可能创建多个会话。合批减少 agent 调用 | ~2h |
| Drain-Before-Restart | 快照运行中 agents → 轮询等待 → interrupt 所有活跃 → finalize hook → .clean_shutdown marker。Exit code 75 让 service manager 重启 | Docker 容器重启时可能丢失 in-flight 工作。加 drain 机制 | ~3h |
| Per-Platform Display Tier | 4 级解析链：platform override → global → platform default → fallback。High(TG/Discord)→Medium(Slack)→Low(WeChat)→Minimal(webhook) | 不同 channel 输出详细度应该不同。TG 可以 verbose，webhook 要精简 | ~1h |
| Prompt Caching system_and_3 | 4 个 cache_control 断点：system prompt + 最后 3 条非 system 消息。支持 5m/1h TTL | 我们直接调 Claude API 时可手动加 cache 标记 | ~1h |
| Backup/Import with SQLite backup() | zip 备份 ~/.hermes/，SQLite 用 `sqlite3.backup()` API 做 WAL-safe 快照；quick snapshot 只备份 8 个关键文件 | DB 备份/迁移需要。`backup()` API 比文件复制安全得多 | ~2h |

### P2 — Reference Only (6 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| Trajectory Compressor | Turn-level 语义压缩（保护 head/tail，贪心最小前缀压缩，LLM 摘要替换），async fan-out 50 并发。输出 ShareGPT 格式给 RL 训练 | 我们不做 RL 训练，但"最小前缀压缩"思想可用于对话压缩 |
| WeCom WebSocket 适配器 | 持久 WebSocket + 心跳 + 3 阶段分块媒体上传协议 + AES-128-CBC 解密 | 我们的 WX channel 走不同协议 |
| OAuth Provider UI Flow | 浏览器内 PKCE/device_code 两种流程，poll 轮询 + 取消 | 我们暂无需要在 web UI 做 OAuth |
| Credential Pool 4 策略 | fill_first/round_robin/random/least_used，exhausted TTL 1h，lease/release | R48 已记录，本次无显著变化 |
| Smart Model Routing Keywords | 40 个关键词触发 strong model，URL 触发 strong，短消息路由 cheap model | 简单启发式，不如 token 预算分级精确 |
| i18n 中英双语 | web dashboard 的 en.ts/zh.ts + context provider | Web 功能性需求，非核心模式 |

## Comparison Matrix (P0 Patterns)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| Session isolation | `contextvars.ContextVar` × 7，`set_session_vars()` 返回 tokens，`get_session_env()` 三级 fallback（contextvar → os.environ → default） | Channel 层无并发隔离。TG 和 WX handler 共享 process 全局状态 | **Large** | Steal：`src/channels/` 加 contextvars |
| Background process monitoring | `ProcessSession.watch_patterns` + `_check_watch_patterns()` 滑动窗口限流（8/10s） + 45s 过载 kill switch，通知入 `completion_queue` | scheduler 长任务只有超时判断，无输出监控 | **Large** | Steal：scheduler 加 pattern watch |
| Truncated tool call guard | `truncated_tool_call_retries < 1` → 静默重试一次（不 append 坏消息到 messages）；再截断 → return partial=True | 无此防护 | **Medium** | Steal：API 调用层加截断检测 |
| Error classification | `FailoverReason` enum (12 种) + `ClassifiedError` dataclass，集中分类管线，恢复策略由 4 个 bool flag 决定 | llm_router 有 try/except 但无分类 | **Medium** | Steal：统一 error taxonomy |
| Focused compression | `focus_topic` 参数流入 `_generate_summary()`，prompt 末尾注入 focus 指令，60-70% budget 分配 | `.remember/` 压缩是全量的 | **Small** | Steal：compaction 加 focus 参数 |
| Anti-premature-stop | `IterationBudget.consume()/refund()` 线程安全 + grace call 注入"请总结" + 不警告模型预算状态 + `execute_code` 调用 refund 不计入 budget | max_turns 硬截断，无 grace | **Medium** | Steal：grace call + 禁止中间预算警告 |

## Security Patterns Deep Dive

v0.9 的安全加固是迄今最深的一轮。8 个修复中有 3 个值得逐一分析：

### 1. SSRF 双层防护（pre-flight + per-redirect hook）

```python
# url_safety.py — DNS 解析后检查 IP 范围
def _is_blocked_ip(ip) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip in _CGNAT_NETWORK:   # 100.64.0.0/10，is_private 不覆盖
        return True
    return False

# slack.py — httpx event_hooks 拦截重定向
async def _ssrf_redirect_guard(response):
    if response.is_redirect and response.next_request:
        redirect_url = str(response.next_request.url)
        if not is_safe_url(redirect_url):
            raise ValueError("Blocked redirect to private/internal address")

async with httpx.AsyncClient(
    event_hooks={"response": [_ssrf_redirect_guard]},
) as client:
    response = await client.get(image_url)
```

**关键洞察**：单纯的 pre-flight check 有 TOCTOU 漏洞——公网 URL 可以 302 重定向到 `169.254.169.254`。httpx 的 `event_hooks` 在每次重定向时触发，实现了真正的深度防护。CGNAT 地址段（`100.64.0.0/10`）被单独处理，因为 Python 的 `is_private` 不覆盖它。

### 2. Per-Thread Interrupt Scoping

```python
# tools/interrupt.py — 替代全局 threading.Event
_interrupted_threads: set[int] = set()
_lock = threading.Lock()

def set_interrupt(active: bool, thread_id: int | None = None) -> None:
    tid = thread_id if thread_id is not None else threading.current_thread().ident
    with _lock:
        if active:
            _interrupted_threads.add(tid)
        else:
            _interrupted_threads.discard(tid)
```

**关键洞察**：Gateway 并发处理多个会话时，全局 `threading.Event.set()` 会中断所有会话。用 thread ident set 做隔离后，Session A 的 /stop 不会误杀 Session B。`_ThreadAwareEventProxy` 兼容旧代码的 `.set()/.clear()/.is_set()` API。

### 3. Git Argument Injection

```python
_COMMIT_HASH_RE = re.compile(r'^[0-9a-fA-F]{4,64}$')

def _validate_commit_hash(commit_hash: str) -> Optional[str]:
    if commit_hash.startswith("-"):
        return f"Invalid commit hash (must not start with '-'): {commit_hash!r}"
    if not _COMMIT_HASH_RE.match(commit_hash):
        return f"Invalid commit hash (expected 4-64 hex characters): {commit_hash!r}"
```

**关键洞察**：`--patch` 作为 commit hash 传入 `git checkout` 会被解释为 flag。Dash-prefix check 是最关键的防线——hex-only regex 是第二层。两层叠加，缺一不可。

## Gaps Identified

| Dimension | Their Coverage | Our Gap |
|-----------|---------------|---------|
| **Security / Governance** | 8 项深度加固，SSRF 双层、SMS RCE、Git 注入、per-thread interrupt | guard.sh 做文件保护，但缺 SSRF/注入/并发隔离类防护 |
| **Memory / Learning** | Hindsight memory plugin + Honcho dialectic modeling，FTS5 会话搜索 | `.remember/` 单一路径，无 FTS 搜索 |
| **Execution / Orchestration** | watch_patterns 后台监控 + drain-before-restart + truncated tool call guard | scheduler 缺输出监控，无优雅 drain |
| **Context / Budget** | Focused compression + Context Engine ABC (已从 v0.8 升级为 plugin slot) | 压缩无 focus 控制 |
| **Failure / Recovery** | Error classifier taxonomy (12 种) + credential rotation on billing 400 + fallback activation | llm_router 有重试但无分类回复策略 |
| **Quality / Review** | Web dashboard analytics (daily token/cost breakdown per model) + rate limit tracking | 吏部绩效报告有但无可视化 dashboard |

## Adjacent Discoveries

1. **TextBatchAggregator 的 adaptive delay**：短文本 0.6s 延迟合批，长文本（>4000 字符，意味着平台分割了消息）2.0s 延迟等后续。这不是固定延迟——它通过文本长度推断"用户是否还在打字"。比简单的 debounce 更聪明。

2. **SQLite backup() API**：比 `shutil.copy2` 安全得多——处理 WAL journal、进行中的事务、共享缓存。我们的 DB 备份应该用这个。

3. **Trajectory 最小前缀压缩**：不压缩整个 middle region，而是从前向后贪心累积直到省够 token。保留更多最近上下文。这个思想可以迁移到对话压缩。

4. **Web Dashboard 的 schema-driven config**：ConfigPage 从 `/api/config/schema` 拉字段定义（类型、描述、choices、分类），AutoField 组件根据 schema 自动渲染 input/select/switch。零手写表单字段。

5. **Staged Inactivity Warning**：超时前先发一次"你还在吗？"预警。只火一次（`_warning_fired = True`），避免轰炸。比直接超时杀掉好太多——用户有机会回应。

## Path Dependency Analysis

### Locking Decisions
- **run_agent.py 大泥球路线**：10.8K 行单文件，从 v0.6 的 8K 到现在。Context Engine ABC、Plugin hooks、Error Classifier 都是"从泥球中抽 ABC"，而非一开始就分模块。好处：所有逻辑在一个上下文里，grep 一个文件就行；坏处：新贡献者门槛极高。
- **Gateway run.py 425KB**：比 run_agent.py 还大。16 个平台适配器分了文件，但 GatewayRunner 本身又是个大泥球。

### Missed Forks
- **v0.7 可以分拆 run_agent.py**：当时引入 Context Engine ABC 时是最佳分拆时机。选择了抽接口但不分文件，错过了窗口。现在 10.8K 行再分拆成本极高。
- **contextvars 应该从 v0.1 就用**：os.environ 做会话状态是个技术债从第一天就在积累，直到并发 bug 暴露才修。

### Self-Reinforcement
- **Star 数驱动的平台宽度**：53.9K→80.9K stars 期间加了 iMessage + WeChat + WeCom，平台数 13→16。社区贡献者 PR 集中在"加新平台"，形成了"平台越多 → star 越多 → 贡献者越多 → 平台越多"的飞轮。
- **技术债的网络效应**：run_agent.py 每加一个 feature 都会让分拆成本更高，形成"不分拆因为太大，太大因为不分拆"的死锁。

### Lesson for Us
- 学他们的 **pattern**（contextvars、watch_patterns、error taxonomy），不学他们的 **structure**（单文件大泥球）。
- 我们的模块化路线（scheduler/channels/governance 分离）更健康，但要防止跨模块协调成本失控。

## Meta Insights

### 1. 安全从"防人"进化到"防自己"

v0.9 的安全加固中，**没有一个是防外部攻击者的**。SSRF 防的是 agent 自己下载图片时被重定向到内网；Git 注入防的是 model 返回的 commit hash 里带 flag；SMS RCE 防的是未验证的 webhook 让 agent 执行任意代码。所有漏洞的根源都是 **AI agent 本身的 tool 调用路径**。

这验证了我们在 R38 提出的论断：agent 安全的主战场不是外部入侵，而是**工具调用链的信任边界**。

### 2. 从"单机工具"到"可运维基础设施"

Web Dashboard + backup/import + drain-before-restart + per-platform display tiers——这些不是 feature，是**运维基础设施**。hermes 正在从"一个聪明的 CLI 工具"变成"一个需要运维的服务"。

80K stars 意味着大量非技术用户（"在 VPS 上跑一个 Telegram bot"），他们不会看日志、不会改 YAML。Web UI 是面向这个人群的答案。

### 3. 并发是 gateway 架构的试金石

`contextvars` 替代 `os.environ` + per-thread interrupt scoping——这两个修复暴露了一个深层问题：**单进程多会话的 gateway 架构，并发隔离不是可选项，是存亡线**。

v0.8 时 os.environ 串会话可能只是偶尔出 bug（用户少、消息稀疏），v0.9 用户量暴增后变成了必须修的 blocker。对 Orchestrator 的启示：如果我们要走多 channel 并发处理，**从第一天就用 contextvars/asyncio.TaskGroup 做隔离**。

### 4. watch_patterns 的防过载设计是教科书级

3 级降级：正常通知 → 窗口限流（8 次/10s）→ 持续过载 kill（45s 后永久禁用该进程的 watch）。这不是简单的 rate limit——它会**杀掉你的监控**，因为一个产生海量输出的进程如果不断触发通知，通知本身会成为新的性能问题（通知 → agent 处理 → API 调用 → 更多 token）。

这个设计体现了"**系统必须能保护自己免受自己的功能的伤害**"的思想。

### 5. 反直觉：不要告诉 AI 它的预算快用完了

hermes 在 #7915 中发现：**中间预算压力警告会导致模型提前放弃复杂任务**。他们的注释写得很清楚：

> "No intermediate pressure warnings — they caused models to 'give up' prematurely on complex tasks."

模型收到"你只剩 3 次 API 调用"后，不会更高效地利用剩余调用——而是草草收场、输出不完整的结果。正确做法是：预算耗尽时才告知，并给一次 grace call 让模型体面地总结。

**对 Orchestrator 的启示**：agent dispatch 的 max_turns 提示不应该在中间出现。Turn 计数器是内部机制，不是给模型看的信息。

### 6. 训练管道是战略投资，不是功能

`trajectory_compressor.py` + `batch_runner.py` + `rl_cli.py` 构成了从 agent 运行到 RL 训练的完整管道。这不是给用户用的功能——这是 Nous Research 自己训练下一代 tool-calling 模型的基础设施。

每一个用 hermes 的用户都在为 Nous 生成训练数据。80K stars = 80K 数据源。这才是 hermes 开源的真正商业逻辑。
