# Round 34: Claude Code 基础设施模式 — 构建/测试/缓存/可观测/类型/配置

> **日期**: 2026-04-01
> **来源**: `@anthropic-ai/claude-code` v2.1.88 反编译源码 + npm 包分析 + GitHub Issues + 社区逆向
> **方法**: WebSearch + WebFetch 多源交叉验证
> **范围**: 构建系统 / 测试基础设施 / 错误处理 / 缓存架构 / 可观测性 / 配置管理 / 类型系统 / 性能优化
> **与已有报告的关系**: Round 28 覆盖 Gate Chain/Address Registry/System Prompts，Round 29 覆盖 QueryEngine/Bridge/Memory/Task/Services/Plugin 六大子系统的 84 个实现层模式。本轮专注 **基础设施层** — 即支撑那些子系统运转的"地基"。

---

## 执行摘要

Claude Code 是 ~1,884 个 TypeScript 文件、~512K 行代码的大型 Agent 框架。Round 29 已经把 QueryEngine、Bridge、Memory 等六大子系统拆到骨头了，但有一层被系统性忽略 — **基础设施层**：代码怎么编译打包、怎么测试、怎么处理错误、怎么缓存、怎么收集遥测、怎么管配置、类型系统怎么约束架构边界。

本轮产出 **42 个可偷模式**，按 9 个维度组织。

**最高价值发现**:
1. **Bun Compile-Time Feature Gate** — `feature()` 内联函数 + dead-code elimination，88+ 编译时开关 + 700+ 运行时 GrowthBook 门控，双层特性管理
2. **四层缓存对齐策略** — 从 prompt cache byte-level alignment 到 microcompact 到 session memory 到 plugin version cache，每层有独立失效策略
3. **三层上下文压缩管线** — snip → microcompact → contextCollapse → autocompact，按代价递增依次尝试
4. **Narrow DI (4 deps)** — QueryDeps 接口刻意只暴露 4 个依赖，用 `typeof fn` 保持类型同步，证明 DI 不需要框架
5. **双 sink 遥测架构** — Anthropic 自有 + Datadog，OpenTelemetry 原生支持，无 wrapper

---

## 一、构建与打包系统（6 模式）

### P01: Bun 原生打包 + Source Map 陷阱

**发现**: Claude Code 使用 Bun 的原生 bundler 而非 esbuild/rollup/webpack。Bun bundler 默认生成 source map，且 `bun build` 不需要额外配置就能处理 TypeScript + JSX。最终产物是一个 ~12MB 的 `cli.js` 单文件 bundle。

**细节**:
- 入口: `scripts/build.ts` 调用 `Bun.build()`
- 输出: `./cli`（生产）或 `./cli-dev`（开发）
- 依赖: 192 个 npm 包，全部 bundle 进单文件
- 运行时: 编译目标为 Node.js ≥18（虽然开发用 Bun ≥1.3.5）
- **教训**: Bun bundler 默认开启 source map，一行配置就能关闭，但 Anthropic 没关 → 512K 行源码泄露

**可偷点**: 我们的 Orchestrator 是 Python + Docker，打包问题不直接适用。但 **单文件 bundle 思路** 值得学习 — 如果 Orchestrator 要做分发版，PyInstaller/Nuitka 打单文件 + 注意不要把调试信息打进去。

### P02: Compile-Time Feature Gate

**发现**: `feature()` 函数来自 `bun:bundle`，是编译时常量。Bun bundler 在构建时把 `feature('X')` 替换为 `true`/`false`，然后 dead-code elimination 自动删掉 `false` 分支及其 `require()` 依赖。

```typescript
// 编译时：
if (feature('VOICE_MODE')) {
  const voice = require('./voice/engine');
  // ...
}
// VOICE_MODE=false 时，整个 if 块和 voice/engine 模块都不进 bundle
```

**88+ 编译时开关**，包括:
| 开关 | 用途 |
|------|------|
| ULTRAPLAN | 远程多 Agent 规划 |
| ULTRATHINK | 深度思考增强 |
| VOICE_MODE | 语音输入 |
| BRIDGE_MODE | IDE 远程控制 |
| AGENT_TRIGGERS | 本地 cron 自动化 |
| BASH_CLASSIFIER | 分类器辅助 bash 权限 |
| CACHED_MICROCOMPACT | 缓存微压缩状态 |
| EXTRACT_MEMORIES | 事后记忆提取 |

**可偷点**: Orchestrator 可以用 Python 版本的编译时特性门控 — 环境变量 + `if TYPE_CHECKING` 模式，或者更激进地用 `__debug__` flag（`python -O` 时移除 `assert` 和 `if __debug__:` 块）。关键是要有 **双层分离**: 编译时决定模块图边界，运行时决定行为变体。

### P03: 构建变体系统

**发现**: `scripts/build.ts` 支持多种构建变体:
- `bun run build` → 生产版（仅 VOICE_MODE）
- `bun run build:dev` → 开发版（实验 GrowthBook key）
- `bun run build:dev:full` → 全开版（45+ 实验特性）
- `bun run build --feature=ULTRAPLAN --feature=ULTRATHINK` → 自定义组合

**可偷点**: Orchestrator 的 Docker Compose 可以用类似思路 — `docker compose --profile dev up` vs `docker compose --profile prod up`，不同 profile 启用不同服务集合。

### P04: Vendor Stubs 隔离原生模块

**发现**: `vendor/` 目录放的是原生模块的 stub/shim，让 bundle 在缺少原生依赖时也能运行。这解决了 Node.js native addon 的跨平台打包问题。

**可偷点**: Python 里遇到类似问题 — 比如 `cv2` 在无 GPU 环境安装失败。可以用 conditional import + stub pattern:
```python
try:
    import cv2
except ImportError:
    cv2 = None  # 或一个 stub 对象
```

### P05: MACRO.VERSION 编译注入

**发现**: `Bun.build()` 脚本通过 plugin 把 `MACRO.VERSION` 替换为当前版本号，类似 C 的 `#define`。这让版本信息在编译时烧入 bundle，运行时零开销查询。

### P06: preload.ts 运行时 Polyfill

**发现**: `bunfig.toml` + `preload.ts` 注册 Bun plugin，在运行时解析 `import { feature } from 'bun:bundle'`，让开发模式不需要完整 build 就能运行。生产 build 由 bundler 在编译时替换，开发模式由 preload 在运行时解析 — 同一套代码，两种解析路径。

---

## 二、测试基础设施（5 模式）

> ⚠️ **重要空白**: Claude Code 的反编译源码中 **没有包含测试文件**。npm 包不含测试，source map 不映射测试目录。这是本次研究中最大的信息盲区。以下基于间接证据推断。

### P07: 测试文件不打包（推断）

**发现**: 512K 行源码中没有任何 `*.test.ts`、`*.spec.ts` 或 `__tests__/` 目录。这不意味着没有测试 — 而是测试文件被 build 过程排除（source map 只映射 bundle 中包含的代码）。

**推断**: Anthropic 内部大概率使用 Vitest（基于 Bun 生态的流行选择）或 Jest（TypeScript 项目的传统选择）。192 个依赖中可能有测试框架，但被标记为 devDependency 不进入生产 bundle。

### P08: Narrow DI 促进可测试性

**发现**（来自 Round 29 P06）: `QueryDeps` 只有 4 个依赖 — `callModel`、`microcompact`、`autocompact`、`uuid`。注释明确说 "Scope is intentionally narrow (4 deps) to prove the pattern."

**测试含义**: 4 个 mock 就能完整测试 QueryEngine 的核心逻辑。`callModel` mock 返回预设的流式响应，`uuid` mock 返回确定性 ID → 测试完全可复现。

**可偷点**: Orchestrator 的 Agent 层如果要写单测，应该效仿这种 narrow DI — 不注入整个 `Services` 对象，只注入 agent loop 真正需要的 3-4 个函数。

### P09: Feature Gate 测试隔离（推断）

**发现**: 编译时 `feature()` + 运行时 GrowthBook 的双层门控天然支持测试隔离:
- 编译时: 用 `preload.ts` 在测试环境注入全 `true` 或全 `false` → 测试不同特性组合
- 运行时: mock GrowthBook 返回特定 flag 值 → 测试运行时行为分支

**可偷点**: Orchestrator 可以学这个模式 — 测试时通过环境变量控制特性开关，而不是在测试代码里打 monkey patch。

### P10: Lazy React Import 避免测试副作用

**发现**（来自 Round 29 P11）: `const messageSelector = () => require('src/components/MessageSelector.js')` — 用函数包装 require，避免 `bun test` 环境中 React/Ink 的初始化副作用（React 在 import 时会检查 DOM 环境）。

**可偷点**: Python 等效: 把 `from tkinter import *` 换成函数内 `import tkinter`，避免 headless CI 环境报错。

### P11: Transcript Write Asymmetry 的可测试性含义

**发现**（来自 Round 29 P09）: assistant 消息 fire-and-forget，user 消息 await。这种非对称设计让测试可以只等 user 消息的写入完成就断言，不需要等异步的 assistant transcript。

---

## 三、错误处理哲学（7 模式）

### P12: 错误分类三元组 — Retryable / Fatal / User-Error

**发现**: HTTP 状态码驱动的错误分类:
- **Retryable**: 429 (rate limit), 500, 502, 503, 504 (server errors)
- **Fatal (不重试)**: 401, 403 (auth errors)
- **User-Error**: 400 系列（除 429）

**参数**:
| 参数 | 默认值 |
|------|--------|
| max_retries | 3（SDK）/ 11（CLI 内部） |
| retry_codes | [429, 500, 502, 503, 504] |
| base_delay | 1.0s |
| max_delay | 60.0s |
| jitter | 0-30% 随机化 |

**退避公式**: `delay = min(base_delay × 2^retry_count, max_delay) × (1 + random(0, 0.3))`

**可偷点**: Orchestrator 对 Anthropic API 的调用应该实现完全相同的分类。目前我们的重试逻辑可能太简单 — 需要检查是否区分了 429 和 500。

### P13: Withheld Error + 3-Layer Recovery

**发现**（Round 29 P02 的基础设施视角）: 流式响应中遇到 `prompt-too-long` 或 `max_output_tokens` 错误时，**不立即暴露给调用方**。而是设置 `withheld = true`，流结束后按优先级尝试恢复:
1. `contextCollapse.recoverFromOverflow()` — drain staged collapses
2. `reactiveCompact.tryReactiveCompact()` — full summary
3. max_output_tokens 递增重试（上限 3 次）

**设计哲学**: "Yielding early leaks an intermediate error to SDK callers that terminate the session on any `error` field." — 面向 SDK 的 API 设计中，暴露中间错误等于让调用方过早放弃。

**可偷点**: Orchestrator 的 Agent SDK 调用层应该学这个 — API 返回错误时先在内部尝试恢复（压缩上下文、减少输出要求），恢复失败才暴露给上层。

### P14: Connection Pool 状态清理缺陷

**发现**: GitHub Issue #23081 揭示了一个真实 bug — HTTP/2 连接池在网络中断后不重建。11 次重试全部复用同一个 stale connection，全部失败。

**根因**: 重试机制复用 HTTP client 实例，其中包含:
- HTTP/2 连接池（死连接）
- TLS session cache（指向旧路径）
- DNS cache（旧 IP）

**正确做法**: 每次重试前 destroy + recreate HTTP client → flush DNS → clear TLS cache。

**可偷点**: 这是个反面教材。Orchestrator 如果用 `httpx`/`aiohttp` 做 API 调用，需要在重试时检查连接池是否健康。简单做法: 重试 3 次仍失败就新建 client。

### P15: Stop Hooks Death Spiral Protection

**发现**（Round 29 P08）: API 错误消息直接跳过 stop hooks。注释: "error → hook blocking → retry → error → … death spiral"。

**可偷点**: 任何 hook/middleware 管线都需要一个"紧急旁路" — 当核心路径出错时，不能让 hook 链再引入更多错误。

### P16: Orphan Tool Result 协议修复

**发现**（Round 29 P10）: 流式中断时，已 yield 的 `tool_use` 缺少 `tool_result` → API 协议不合法。解法: 遍历所有 assistantMessages，合成 `is_error: true` 的 tool_result。

**设计原则**: 协议完整性优先于错误精确性。给一个"我出错了"的假 result 比让协议断裂好。

### P17: Streaming Tool Executor Discard

**发现**（Round 29 P04）: 工具在 model 还在流式输出时就并行执行（乐观执行）。Fallback 触发时调用 `discard()` 丢弃所有中间结果 → 重建新 executor → 防止 orphan tool_result 污染 retry。

**可偷点**: 并行执行+回滚 pattern 适合 Orchestrator 的多 Agent 场景 — 多个 agent 同时跑，一个失败就 discard 全部中间结果。

### P18: Circuit Breaker — Compact 失败后停止重试

**发现**: compact 失败后有 circuit breaker 阻止反复尝试。具体实现是跟踪 compact 尝试次数，超过阈值就停止 — 避免在已经 context-too-large 的情况下还反复调 API 做压缩（压缩请求本身也消耗 context）。

---

## 四、缓存架构（6 模式）

### P19: Prompt Cache Byte-Level Alignment

**发现**: 子 agent 继承父 agent 的 system prompt + tool definitions 前缀 → 与 Anthropic API 的 prompt cache 对齐。关键: cache 命中需要 **字节级前缀匹配**，所以系统 prompt 中动态内容（如日期）被刻意移除。

**成本影响**: 200K token 会话的 compact 请求，如果前缀（~18K tokens）命中 cache → 从 cache 读取 $0.009 vs 重新处理 $0.09（10x 差距）。

**可偷点**: Orchestrator 的多 Agent 调用应该确保所有 agent 共享相同的 system prompt 前缀 → 最大化 prompt cache 命中率。不要在 system prompt 里放时间戳等动态内容。

### P20: FILE_UNCHANGED_STUB 去重缓存

**发现**: Read tool 对同一文件的重复读取返回 ~30 word 的 stub 而非完整内容。内部标记文件 hash，内容未变就返回 "file unchanged since last read"。

**可偷点**: Orchestrator 的文件读取工具可以实现同样的去重 — 用 SHA256 跟踪已读文件，重复读取返回摘要。

### P21: GrowthBook Feature Flag Aggressive Cache

**发现**: `getFeatureValue_CACHED_MAY_BE_STALE()` 函数名直接说明了策略 — 特性值可以是过期的，因为实时性不重要，避免阻塞主循环更重要。

**轮询频率**: 每小时从 Anthropic 服务器拉一次配置。700+ 运行时门控用这种 "eventual consistency" 模式。

**可偷点**: Orchestrator 的配置管理应该区分 "必须实时" vs "最终一致" — agent 的行为参数可以缓存 1 小时，安全策略变更应该立即生效。

### P22: Plugin Version Cache

**发现**: Plugin 缓存路径: `~/.claude/plugins/cache/marketplace/plugin/version/` — 三级目录结构（marketplace → plugin → version）确保不同版本不互相污染。

### P23: Skill Description 250 字符截断

**发现**: Skill 列表中每个 skill 的描述被截断到 250 字符 → 减少初始 context 消耗。完整描述只在 skill 被选中后加载。

**可偷点**: Orchestrator 的 SOUL/public/prompts/ 目录下有大量 prompt 文件。可以学这个 — system prompt 里只放 250 字符摘要，触发相关功能时再加载完整 prompt。

### P24: MCP Tool Deferred Loading

**发现**: MCP tool 描述在超过阈值时自动延迟加载。初始只加载 tool 名称（~5K tokens），完整 schema 在 tool 被调用前才拉取。社区实测: 从 108K → 5K tokens 初始消耗（95% 减少）。

**可偷点**: 这对 Orchestrator 的 tool 注册系统直接适用 — 工具多了以后不要全部塞进 system prompt，先放名称列表，按需展开。

---

## 五、可观测性（5 模式）

### P25: 双 Sink 遥测架构

**发现**: 遥测数据同时发往两个后端:
- **Anthropic 自有后端**: 产品分析、安全审计
- **Datadog**: 运维监控、性能指标

两个 sink 独立运行，一个挂了不影响另一个。

### P26: OpenTelemetry 原生集成

**发现**: Claude Code 内置 OpenTelemetry 支持，不是第三方 wrapper:
- Metrics 走 OTLP 时间序列协议
- Events 走 OTLP logs/events 协议
- 支持 gRPC 和 HTTP 两种传输
- 兼容 Logfire、Sentry、Honeycomb、Grafana、Datadog

**配置**: 环境变量控制:
```bash
CLAUDE_CODE_ENABLE_TELEMETRY=1
OTEL_EXPORTER_TYPE=otlp  # otlp | prometheus | console | none
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc  # grpc | http
```

**Sentry 集成**: span 包含 `gen_ai.*` 属性 → 出现在 Sentry 的 AI Performance 面板中。

**可偷点**: Orchestrator 当前的日志是 Python logging 模块 → 应该迁移到 OpenTelemetry。不需要一步到位，先用 `opentelemetry-api` 打 span，后端可以对接 Grafana 或 Sentry。

### P27: 隐私保护遥测

**发现**: 用户 prompt 内容 **默认不收集** — 只记录 prompt 长度。用户邮箱只在 OAuth 认证时包含在遥测属性中。`OTEL_LOG_TOOL_DETAILS=1` 才会收集完整 tool 输入。

**可偷点**: Orchestrator 如果要加遥测，**必须**默认不收集 prompt 内容。这是合规底线。

### P28: Session ID Header

**发现**: 每个 API 请求附带 `X-Claude-Code-Session-Id` header → 代理网关可以据此做会话级聚合。

**可偷点**: Orchestrator 的 API 调用应该携带 session ID → 方便追踪一次对话的所有 API 请求。

### P29: Cost Tracker — Token 粒度计费

**发现**: `cost-tracker.ts` 追踪:
- 每个 model 的费用
- Cache 命中率
- Token 分解（input/output/cache_read/cache_write）
- 代码变更统计

**可偷点**: Orchestrator 已经有 token tracking，但可以加 cache 命中率追踪 — 这是优化的基础。

---

## 六、配置管理（5 模式）

### P30: 多层配置覆盖

**发现**: 配置从 5 个层次合并（优先级从高到低）:
1. **CLI 参数** — `--max-turns 5`
2. **项目 CLAUDE.md** — 仓库根目录
3. **用户 CLAUDE.md** — `~/.claude/CLAUDE.md`
4. **Team 配置** — `~/.claude/teams/{team-name}/config.json`
5. **远程配置** — 每小时轮询 Anthropic 服务器

**可偷点**: Orchestrator 目前用 `.env` + `docker-compose.yml` + SOUL 系统。应该明确文档化配置优先级链，避免"为什么这个配置没生效"的调试地狱。

### P31: 远程配置推送 + Kill Switch

**发现**: Anthropic 服务器可以通过小时轮询推送配置变更:
- 激活/停用特性（GrowthBook flag）
- 6+ kill switch 控制权限、语音模式、分析
- **危险变更触发阻断性对话框** — 拒绝则退出应用

**可偷点**: Orchestrator 可以实现简化版 — `SOUL/public/config/remote.json` 放在 GitHub 上，agent 启动时拉取。不需要 Anthropic 那么复杂的 kill switch，但 "远程关闭某个危险功能" 的能力值得有。

### P32: Sensitive Config → System Keychain

**发现**: 敏感配置值（API keys 等）路由到系统 keychain，不写磁盘文件。

**可偷点**: Orchestrator 的 `.env` 文件放在 Docker volume 里，相对安全。但如果要做本地模式，应该用 `keyring` Python 库而不是明文 `.env`。

### P33: Settings Schema — strictKnownMarketplaces

**发现**: 企业环境可以锁定到 `strictKnownMarketplaces`，阻止来自不信任源的 plugin。这是通过 settings.json 的 schema 校验实现的。

### P34: Config Snapshot Isolation（Round 29 P05 补充）

**发现**: `buildQueryConfig()` 在每次查询入口调用一次，将所有 GrowthBook gate 快照到 `QueryConfig.gates`。查询执行期间配置冻结 → 避免 mid-flight 配置变更导致行为不一致。

**可偷点**: Orchestrator 的 agent 执行应该在入口 snapshot 一次配置，执行期间不再读配置文件。

---

## 七、类型系统用法（5 模式）

### P35: Zod v4 运行时校验

**发现**: Claude Code 使用 Zod v4 做运行时 schema 校验。所有 tool 参数在执行前通过 Zod schema 校验 → 无效输入在进入 tool 逻辑前被拦截。

**用途**:
- Tool 参数校验
- API 响应校验
- 配置文件校验
- Plugin manifest 校验

**可偷点**: Orchestrator 用 Python，对应物是 `pydantic`（已在用）。但要确保 **每个 tool 的输入都过 pydantic model** — 目前可能有些 tool 直接读 dict。

### P36: 七种 Task Type 判别联合

**发现**: Task 类型用 discriminated union 表示:
- `InProcessTeammate` — 进程内队友
- `LocalAgentTask` — 本地 agent 任务
- `RemoteAgentTask` — 远程 agent 任务
- `LocalShellTask` — 本地 shell 任务
- `DreamTask` — 后台梦境任务
- `LocalWorkflowTask` — 本地工作流任务
- `MonitorMcpTask` — MCP 监控任务

TypeScript 的 exhaustive switch 确保每种类型都被处理。

**可偷点**: Orchestrator 的 Task 类型可以用 Python 的 `Literal` + `Union` + `match` 语句实现同样的穷举检查。

### P37: Tool 继承 + JSON Schema 参数

**发现**: 所有 tool 继承自 `Tool` 基类，参数用 JSON Schema 描述。这让 LLM 能直接看到参数的类型和约束。

### P38: Permission Model 枚举 — ask | bubble | allow

**发现**: 三种权限模式:
- `ask` — 需要用户确认
- `bubble` — 冒泡到 leader agent
- `allow` — 自动批准（在白名单范围内）

加上内部 flag: `auto`（激进分类）和 `bubble`（sub-agent 权限上传）。

**可偷点**: Orchestrator 的审批系统（Claw/TG/WX）已经实现了类似的分级，但缺少 `bubble` — sub-agent 的权限请求应该能自动冒泡到父 agent 或人类。

### P39: `typeof fn` 依赖类型推导

**发现**: `QueryDeps` 接口用 `typeof callModel` 而不是手写函数签名 → 当 `callModel` 的签名变化时，依赖接口自动同步，不需要手动更新两处。

**可偷点**: Python 等效 — 用 `Callable` + `Protocol` 类型约束依赖注入接口，而不是裸的函数参数。

---

## 八、性能模式（5 模式）

### P40: AsyncLocalStorage 隐式上下文隔离

**发现**: 多 agent 进程内并行运行时，用 Node.js 的 `AsyncLocalStorage` 做隐式上下文传递 — 每个 agent 有自己的 context，不需要显式参数传递。

**可偷点**: Python 等效是 `contextvars`。Orchestrator 如果要在同一进程跑多个 agent，应该用 `contextvars.ContextVar` 而不是全局变量。

### P41: Progressive Disclosure — Skill 按需加载

**发现**: Skill 系统有 `paths` 过滤器 — skill 保持隐藏直到用户触碰匹配的文件。初始只加载 120 tokens/skill 的摘要。社区实测: 从 80K → 52K tokens（35% 减少）。

**可偷点**: Orchestrator 的 SOUL prompt 系统可以学这个 — 不是所有 prompt 都需要在每次对话开头加载。按用户操作动态激活。

### P42: Dynamic Output Cap

**发现**: 默认输出上限 8K tokens，如果触发 max_output_tokens 错误则递增到最高 64K tokens。而不是一开始就设 64K → 避免在大多数短响应场景中浪费 token 预算。

**可偷点**: Orchestrator 的 Agent SDK 调用可以实现同样的动态调整 — 先用小 max_tokens，被截断了再加大重试。

---

## 九、模块架构全景（3 模式）

### P43: 五层分层架构

```
Layer 1: Entrypoints (CLI / Desktop / Web / SDK / IDE)
Layer 2: Runtime (REPL / Query executor / Hook system / State manager)
Layer 3: Engine (QueryEngine / Context coordinator / Model manager / Compact)
Layer 4: Tools & Capabilities (100+ tools / Plugin / MCP / Skill / Agent / Command)
Layer 5: Infrastructure (Auth / Storage / Cache / Analytics / Bridge transport)
```

**关键设计**: 同一个 Engine 层驱动所有 Entrypoint → 一套代码支撑 CLI、桌面应用、网页、SDK、IDE 插件。

**可偷点**: Orchestrator 目前只有 Docker + CLI 入口。如果要加 Web dashboard 的深度集成，应该把 "engine" 从 "entrypoint" 分离 — engine 是纯 Python 逻辑，entrypoint 是 HTTP/CLI/Telegram 等不同外壳。

### P44: src/ 目录结构

```
src/
├── entrypoints/      # CLI 入口
├── main.tsx          # 认证 + feature flags + MCP 初始化
├── QueryEngine.ts    # ~1,295 行 LLM API 编排引擎
├── tools/            # 53 个 tool 实现
├── commands/         # 87 个 slash command
├── services/         # API client, MCP, OAuth, telemetry
├── utils/            # Git, permissions, token budgeting
├── components/       # ~406 React+Ink 终端 UI 文件
├── hooks/            # React hooks (tools, voice, IDE)
├── vim/              # Vim 按键引擎
├── coordinator/      # 多 Agent 编排
├── bridge/           # IDE 双向通信
├── memdir/           # 5 层持久记忆系统
├── state/            # 应用状态管理
├── skills/           # Skill 系统
├── plugins/          # Plugin 系统
├── tasks/            # 后台任务管理
└── voice/            # 语音输入（未发布）
```

### P45: 192 依赖零直接依赖发布

**发现**: `package.json` 声明 192 个依赖，但发布的 npm 包声明 **零依赖** — 全部 bundle 进单文件。这意味着:
- 用户安装只下载一个文件
- 没有 node_modules 地狱
- 依赖版本冻结在编译时

**可偷点**: Python 的 PyInstaller/Nuitka 也能做到类似效果。但更实际的参考是: Orchestrator 的 Docker 镜像应该确保所有依赖锁定版本（`pip freeze` 或 `uv lock`）。

---

## 跨维度综合分析

### 1. "双层门控" 是贯穿全架构的设计哲学

编译时 `feature()` + 运行时 `GrowthBook` 不是两个独立系统，而是同一个设计意图的两种表达:
- **编译时**: 控制 **模块图边界** — 哪些代码进入 bundle
- **运行时**: 控制 **行为分支** — 同一段代码走哪条路

Orchestrator 等效: `docker compose --profile` (编译时 = 启动时) + `SOUL/public/config/` (运行时 = 可热更新)。

### 2. 缓存策略的分层纪律

每层缓存有明确的失效策略:
| 层级 | 缓存对象 | 失效策略 |
|------|----------|----------|
| Prompt Cache | API 前缀 | 字节级匹配，5 分钟 TTL (API 层) |
| Microcompact | 压缩状态 | Token 阈值触发 |
| Session Memory | 会话摘要 | 新 session 时 |
| File Content | 文件 hash | 文件变更时 |
| Plugin Cache | 版本目录 | 版本号变化时 |
| GrowthBook | Feature flags | 1 小时轮询 |
| Config Snapshot | 查询配置 | 每次查询入口 |

### 3. 测试基础设施是最大盲区

512K 行代码、1884 个文件、192 个依赖 — **测试文件一个都没泄露**。这要么说明测试在独立仓库，要么说明 Anthropic 的 monorepo 构建系统在 bundle 时精确排除了测试。对我们来说，这意味着需要从其他来源（如 Anthropic 的工程博客、招聘 JD）推断他们的测试策略。

---

## Orchestrator 行动项

按优先级排序:

| 优先级 | 行动项 | 来源模式 | 预估工时 |
|--------|--------|----------|----------|
| P0 | 实现 Withheld Error + Recovery — API 错误时先内部尝试压缩/重试再暴露 | P13 | 4h |
| P0 | Agent 调用 system prompt 去掉动态内容，最大化 prompt cache | P19 | 1h |
| P0 | 工具输入全部过 pydantic model | P35 | 3h |
| P1 | 添加 OpenTelemetry span 到 agent loop | P26 | 8h |
| P1 | 配置快照隔离 — agent 入口冻结配置 | P34 | 2h |
| P1 | 实现 File Content Dedup Cache — 同一文件重复读返回摘要 | P20 | 3h |
| P1 | 明文文档化配置优先级链 | P30 | 1h |
| P2 | Skill/Prompt 按需加载 — system prompt 只放 250 字符摘要 | P23, P41 | 4h |
| P2 | MCP Tool Deferred Loading | P24 | 6h |
| P2 | Dynamic Output Cap — 先小后大 | P42 | 2h |
| P2 | contextvars 隔离多 agent 上下文 | P40 | 3h |

---

## Sources

- [Claude Code Architecture Deep Dive](https://redreamality.com/blog/claude-code-source-leak-architecture-analysis/)
- [Claude Code Source (sanbuphy)](https://github.com/sanbuphy/claude-code-source-code)
- [Claude Code Source (xorespesp)](https://github.com/xorespesp/claude-code)
- [free-code fork (telemetry removed)](https://github.com/paoloanzn/free-code)
- [Claude Code Monitoring Docs](https://code.claude.com/docs/en/monitoring-usage)
- [OpenTelemetry + Claude Code (SigNoz)](https://signoz.io/blog/claude-code-monitoring-with-opentelemetry/)
- [Context Window & Compaction (DeepWiki)](https://deepwiki.com/anthropics/claude-code/3.3-context-window-and-compaction)
- [Prompt Caching Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Retry Logic (DeepWiki)](https://deepwiki.com/jasonkneen/claude-code-sdk/3.4.4-retry-logic)
- [HTTP/2 Connection Bug (GH #23081)](https://github.com/anthropics/claude-code/issues/23081)
- [Dev.to Source Analysis](https://dev.to/gabrielanhaia/claude-codes-entire-source-code-was-just-leaked-via-npm-source-maps-heres-whats-inside-cjo)
- [Build Infrastructure PR (#41621)](https://github.com/anthropics/claude-code/pull/41621)
- [Compaction API Docs](https://platform.claude.com/docs/en/build-with-claude/compaction)
