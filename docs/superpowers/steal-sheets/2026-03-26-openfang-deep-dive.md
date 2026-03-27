# OpenFang 深度偷师分析 (15.6K Stars · 1 个月)

> 仓库: https://github.com/RightNow-AI/openfang
> 语言: Rust (137K LOC, 14 crates)
> 定位: Agent Operating System（不是框架，是运行时）
> 日期: 2026-03-26

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      openfang-kernel                            │
│  (编排 · 工作流 · 计量 · RBAC · 调度器 · 预算追踪)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  openfang-runtime ──► Agent Loop (max 50 iterations)            │
│       │                    │                                    │
│       ├── 3 LLM Driver     ├── Loop Guard (SHA256 去重)          │
│       ├── 53 Built-in Tools├── Context Budget (双层截断)         │
│       ├── WASM Sandbox     ├── Hallucination Detector            │
│       └── MCP / A2A        └── Token Continuation Limiter       │
│                                                                 │
│  openfang-channels ──► 40 Adapters (TG/Discord/Slack/WX/...)   │
│       │                                                         │
│       ├── Bridge Manager (并发 32 · DM/Group 策略)               │
│       └── Agent Router (5 级优先级路由)                          │
│                                                                 │
│  openfang-memory ──► SQLite + Vector Embedding                  │
│  openfang-skills ──► 60 Skills + Prompt 注入扫描器              │
│  openfang-hands  ──► 7 个自主 Agent 包 (HAND.toml)              │
│  openfang-wire   ──► OFP P2P 协议 (HMAC-SHA256 双向认证)        │
│  openfang-desktop──► Tauri 2.0 桌面应用                         │
│                                                                 │
│  16 层安全体系 ─► WASM 沙箱 · Merkle 审计链 · 污点追踪          │
│                  · Ed25519 签名 · SSRF 防护 · 循环守卫          │
│                  · Prompt 注入扫描 · 能力门 · GCRA 限流         │
└─────────────────────────────────────────────────────────────────┘
```

### 关键模块对照

| OpenFang 模块 | 我们的对应 | 差距 |
|--------------|-----------|------|
| Loop Guard (SHA256 + ping-pong) | StuckDetector (6 pattern) | 我们缺 ping-pong 检测和结果感知 |
| Taint Tracking (5 label lattice) | 无 | **完全缺失** |
| Merkle Audit Chain | run_logger.py (SHA-256 hash chain) | 已有！格式几乎相同 |
| WASM Sandbox | 无（Python 无法直接复刻） | 用 subprocess isolation 替代 |
| Context Budget (双层截断) | 无显式管理 | 可借鉴 |
| Tool Policy (deny-wins + glob) | ImmutableConstraints + Blueprint | 我们有但粒度较粗 |
| HAND.toml 声明式 agent | blueprint.yaml | 思路相似但 HAND 更完整 |
| Agent Router (5 级路由) | channels/config.py | 我们的路由简单得多 |
| Capability RBAC (24 种) | AuthorityCeiling (4 级) | 可细化 |

---

## 二、可偷模式 (按优先级)

### P0 — 立即可偷

#### 1. 污点追踪 (Taint Tracking)

**核心思想**: 数据从来源到消费全程携带"污染标签"，到达敏感出口时自动拦截。

```
TaintLabel 枚举 (5 种):
  ExternalNetwork  — 来自外部网络的数据
  UserInput        — 用户输入（可能含注入）
  Pii              — 个人身份信息
  Secret           — API key / 密码 / token
  UntrustedAgent   — 来自不可信 agent 的数据

Sink 规则 (3 种):
  shell_exec  → 阻止 ExternalNetwork + UntrustedAgent + UserInput
  net_fetch   → 阻止 Secret + Pii（防数据外泄）
  agent_msg   → 阻止 Secret

关键方法:
  merge_taint()   — 数据合并时取标签并集
  check_sink()    — 到达 sink 时检查标签
  declassify()    — 显式移除标签（数据消毒后）
```

**偷法**: 在 executor_session.py 的工具调用链中加 `TaintedValue` 包装器。每次工具返回结果，根据工具类型打标签；传入下一个工具前，检查 sink 规则。

**对我们的价值**: executor 当前只有 ImmutableConstraints 做静态黑名单。污点追踪是**动态的信息流控制** —— 不是禁止用某个工具，而是禁止"用外部数据去跑 shell"这种组合。

```python
# 伪代码 — Python 版 TaintTracking
class TaintLabel(Flag):
    EXTERNAL = auto()
    USER_INPUT = auto()
    PII = auto()
    SECRET = auto()
    UNTRUSTED = auto()

SINK_RULES = {
    "shell_exec": TaintLabel.EXTERNAL | TaintLabel.UNTRUSTED | TaintLabel.USER_INPUT,
    "net_fetch":  TaintLabel.SECRET | TaintLabel.PII,
    "agent_msg":  TaintLabel.SECRET,
}

class TaintedValue:
    def __init__(self, value, labels=TaintLabel(0)):
        self.value = value
        self.labels = labels

    def merge(self, other):
        return TaintedValue(f"{self.value}\n{other.value}",
                           self.labels | other.labels)

    def check_sink(self, sink_name):
        blocked = SINK_RULES.get(sink_name, TaintLabel(0))
        violation = self.labels & blocked
        if violation:
            raise TaintViolation(f"{sink_name} blocked: {violation}")
```

---

#### 2. Loop Guard 升级 — 结果感知 + Ping-Pong 检测

**核心思想**: 不只检测"调了同一个工具"，还检测"调了同一个工具且拿到了同一个结果"（方法不奏效），以及 A-B-A-B 交替模式。

```
三套检测机制:
1. 结果感知: 跟踪 (call, result) 对
   - 同 call + 同 result = "方法不奏效"，阈值减半加速升级
   - 同 call + 不同 result = 正常轮询（给 multiplier）

2. Ping-Pong: 在最近 30 次调用中寻找交替模式
   - A-B-A-B 或 A-B-C-A-B-C
   - 3+ 次重复 → Block

3. 轮询识别: shell_exec + 关键词 (status/poll/wait/docker ps)
   → 阈值 × poll_multiplier (默认 3x)

四种裁决: Allow / Warn / Block / CircuitBreak (全局 30 次)
```

**偷法**: 升级现有 StuckDetector，加入结果哈希和 ping-pong 检测。

**对比我们的 StuckDetector**:
- 我们有: REPEATED_ACTION, MONOLOGUE, CONTEXT_WINDOW_LOOP, SIGNATURE_REPEAT
- 缺失: **结果感知**（同工具不同结果 = 正常轮询 vs 同结果 = 死循环）
- 缺失: **Ping-Pong 模式检测**（A-B-A-B 交替）
- 缺失: **轮询工具白名单**（docker ps 之类不应该算重复）

---

#### 3. Context Budget 动态管理

**核心思想**: 工具输出占满上下文时，按时间序压缩旧结果而非硬截断。

```
ContextBudget:
  context_window_tokens = 200K
  tool_chars_per_token = 2.0    # 工具输出密度高
  general_chars_per_token = 4.0

Layer 1 — 单结果上限:
  max = context_window × 30%，硬限 50%
  超出 → 截断（UTF-8 安全：检查多字节字符边界回退）

Layer 2 — 全局守卫:
  总工具输出 > headroom × 75%
  → 按时间序压缩最旧的工具结果（保留摘要）
```

**偷法**: 在 executor_session.py 加 ContextBudget 类，每次工具返回后检查。

**对我们的价值**: 当前 MAX_AGENT_TURNS=25 是粗粒度控制。Context Budget 让 agent 在长任务中"忘掉旧的工具输出"而非直接中断。

---

### P1 — 短期可偷

#### 4. Tool Policy — deny-wins + glob 匹配 + 深度限制

```
ToolPolicy:
  agent_rules   → 最高优先级
  global_rules   → 兜底
  groups         → @web_tools, @shell_tools 等命名组

规则引擎:
  1. deny 规则先检查，命中即拒绝
  2. 有 allow 规则时，必须至少匹配一条
  3. glob 匹配: shell_*, mcp_github_*

深度限制 (子 agent):
  SUBAGENT_DENY_ALWAYS: cron_create, process_start → 任何深度禁止
  SUBAGENT_DENY_LEAF:   agent_spawn → 最大深度时禁止

Capability 继承验证:
  validate_capability_inheritance() → 子 agent 不能超过父 agent 权限
```

**对比我们的 ImmutableConstraints**:
- 我们有: FORBIDDEN_TOOLS 黑名单，FORBIDDEN_PATHS glob，CEILING_TOOL_CAPS 按权限级别
- 缺失: **deny-wins 引擎**（当前是简单列表检查，没有 allow/deny 优先级逻辑）
- 缺失: **glob 匹配工具名**（`shell_*` 一次禁一类）
- 缺失: **子 agent 深度限制**（当前 agent_semaphore 只限并发数，不限嵌套深度）
- 缺失: **权限继承验证**（子 agent 可能绕过父 agent 限制）

---

#### 5. 幻觉动作检测 (Hallucinated Action Detection)

**核心思想**: LLM 声称"已发送邮件"/"已保存文件"但没有实际工具调用 → 强制重新 prompt。

```
检测模式:
  - 扫描 assistant 回复中的动作关键词: "已发送", "已保存", "已执行", "done", "sent"
  - 检查该 turn 是否有对应的工具调用
  - 无工具调用 → 注入修正 prompt: "你声称做了 X，但没有实际执行。请使用工具来完成。"
```

**偷法**: 在 executor_session.py 的 turn 处理后加检测。

**对我们的价值**: 有时 agent 会说"我已经提交了代码"但实际只是在回复中写了这句话。这个检测器能捕获这类"幻觉执行"。

---

#### 6. HAND.toml 声明式 Agent 包

**核心思想**: 把 agent 的所有配置打包成一个声明式文件，类似 K8s manifest。

```toml
[agent]
name = "collector"
version = "0.1.0"
schedule = "Periodic"

[model]
provider = "default"
model = "default"
temperature = 0.5
system_prompt = """...(500+ 词操作手册)..."""

[capabilities]
tools = ["web_search", "web_fetch", "file_read"]
network = ["*"]
memory_write = ["self.*", "shared.*"]

[resources]
max_llm_tokens_per_hour = 150000

[autonomous]
max_iterations = 100
heartbeat_interval_s = 300

[[fallback_models]]
provider = "openai"
model = "gpt-4o"
```

**对比我们的 blueprint.yaml**:
- 相似: 版本、超时、最大轮数、模型、权限
- 缺失: **fallback 模型链**（我们的 waterfall 在 llm_router 里硬编码）
- 缺失: **资源配额**（per-agent token/hour 限制）
- 缺失: **自主模式配置**（heartbeat、安静时段、max_iterations）
- 缺失: **工具 profile**（Minimal/Coding/Research/Full 一键切换）

---

### P2 — 长期参考

#### 7. Prompt 注入扫描器

```
三级检测:
  Critical: "ignore previous instructions", "system prompt override" 等
  Warning:  HTTP POST / base64 编码（外泄）, rm -rf / sudo（shell 注入）
  Info:     > 50KB prompt（异常大）

背景: 2026-02 在 FangHub 发现 341 个恶意 skill → 实战响应
```

**对我们的价值**: 我们有 deslop_scanner 检测 AI 套话，但没有专门的 prompt 注入检测。当 agent 处理外部输入（用户消息、网页内容）时需要。

---

#### 8. Channel 5 级路由

```
路由优先级:
  1. Binding（按特异性排序：约束数越多越优先）
  2. 直接路由（消息显式指定 agent）
  3. 用户默认 agent
  4. 频道默认 agent
  5. 全局默认 agent

Binding 匹配维度: channel_type, peer_id, guild_id, roles, account_id
```

**对我们的价值**: 当前 channel 路由是简单的 if/else。多 agent 场景下需要更细粒度的路由。

---

#### 9. Secret Zeroization

```rust
// Rust: Zeroizing<String> — 析构时内存清零
let api_key = Zeroizing::new(config.api_key.clone());
// 离开作用域时自动覆写内存
```

**Python 等价**: `ctypes.memset(id(s), 0, len(s))` 不可靠（CPython 字符串不可变）。但可以：
- 使用 `SecretStr`（pydantic）限制序列化
- 环境变量用完立即 `del os.environ[key]`
- 日志 scrubber 过滤 key pattern

---

#### 10. 文本工具调用恢复 (Text Tool Call Recovery)

```
支持 13+ 种非标工具调用格式解析:
  <function=name>   — OpenAI 旧格式
  <tool>...</tool>   — Anthropic XML
  <tool_call>        — Claude Code 格式
  ReAct: Action/Input — ReAct 框架格式
  裸 JSON {...}       — 模型直接输出 JSON

用途: 当模型不规范地输出工具调用时，降级兼容解析
```

**对我们的价值**: 用 Ollama 本地模型时容易遇到格式不规范的工具调用。当前硬依赖 Claude Agent SDK 的结构化输出，缺乏降级路径。

---

## 三、安全体系对比

| 安全层 | OpenFang | Orchestrator | 评估 |
|--------|----------|-------------|------|
| 工具黑名单 | deny-wins + glob | ImmutableConstraints | 我们有，需细化 |
| 循环检测 | 3 机制 + 4 裁决 | StuckDetector 6 pattern | 接近，缺结果感知 |
| 成本控制 | per-agent token/hour | per-task $5 cap | 我们有，维度不同 |
| 审计链 | Merkle SHA-256 + SQLite | SHA-256 hash chain JSONL | **几乎相同** ✓ |
| 并发控制 | 32 并发 dispatch | AgentSemaphore 分级 | 我们更细 ✓ |
| 权限模型 | 24 Capability + RBAC | 4 级 AuthorityCeiling | 我们更简单但够用 |
| 背压 | 未明确 | SystemMonitor CPU/RAM | 我们有 ✓ |
| 污点追踪 | 5 标签 + 3 sink | **无** | 缺失 |
| WASM 沙箱 | Wasmtime fuel+epoch | **无** | 语言限制 |
| 幻觉检测 | 动作关键词扫描 | **无** | 可加 |
| Prompt 注入 | 3 级扫描 | deslop_scanner (不同目的) | 可加 |
| Secret 清零 | Zeroizing<String> | **无** | Python 受限 |

---

## 四、直接应用计划

| # | 模式 | 优先级 | 影响文件 | 复杂度 |
|---|------|--------|---------|--------|
| 1 | 污点追踪 | P0 | 新建 `src/governance/safety/taint.py`，修改 `executor_session.py` | 中 |
| 2 | Loop Guard 升级 (结果感知 + ping-pong) | P0 | 修改 `src/governance/stuck_detector.py` | 低 |
| 3 | Context Budget | P0 | 新建 `src/core/context_budget.py`，修改 `executor_session.py` | 低 |
| 4 | 幻觉动作检测 | P1 | 修改 `executor_session.py` | 低 |
| 5 | Tool Policy deny-wins 引擎 | P1 | 修改 `src/governance/safety/immutable_constraints.py` | 中 |
| 6 | 子 agent 深度限制 | P1 | 修改 `agent_semaphore.py` | 低 |
| 7 | Blueprint 增强 (fallback chain + profile) | P1 | 修改 `blueprint.yaml` schema + `executor.py` | 中 |
| 8 | Prompt 注入扫描器 | P2 | 新建 `src/governance/safety/injection_scanner.py` | 中 |

---

## 五、15.6K Stars 的秘密

1. **Rust 性能碾压**: 冷启动 180ms vs LangGraph 2.5s。空闲内存 40MB vs OpenClaw 394MB。这不是优化，是语言选择的结构性优势。

2. **Agent OS vs Agent Framework**: 框架给你积木让你搭，OS 给你直接能跑的运行时。`openfang start` 一条命令，开箱即用。

3. **HAND = 可分发的自主 agent**: 不是 "prompt + 工具列表"，而是完整的操作手册 + 领域知识 + 安全约束 + 调度配置。可以像 Docker Image 一样分发。

4. **16 层安全 = 信任锚**: 在 2026 年这个 agent 安全事故频发的时期，"安全"本身就是卖点。Merkle 审计链 + 污点追踪 + WASM 沙箱，每一层都有实战背景。

5. **MIT + 单二进制**: 零部署摩擦。`curl | sh` 结束。不需要 Python 虚拟环境、Docker、云服务。

6. **迁移引擎**: `openfang migrate --from openclaw` 一条命令把竞品用户拉过来。虽然只实现了 OpenClaw，但心理效果已经到了。

---

## 六、核心启示

> OpenFang 用 Rust 类型系统做到的安全保证，我们需要用 Python 运行时检查来补。
> 但我们的优势是**热更新** —— 改个 .py 直接生效，不需要编译 14 个 crate。
>
> 最值得偷的不是具体代码，而是**信息流安全思维**：
> - 不只问"这个工具能不能用"（静态黑名单）
> - 要问"这个数据能不能到那里去"（动态污点追踪）
>
> 第二个核心启示：**循环检测要看结果**。
> 同一个工具调了 5 次，如果每次结果不同（轮询），那是正常的；
> 如果每次结果相同，那是 agent 在做无用功。
