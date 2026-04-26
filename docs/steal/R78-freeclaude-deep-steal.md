# R78 — FreeClaude Steal Report

**Source**: https://github.com/alexgrebeshok-coder/freeclaude | **Stars**: 2 | **License**: undeclared (README says MIT)
**Date**: 2026-04-17 | **Category**: Specific Module (Claude Code fork; delta is 8 modules)

## TL;DR

个人 Claude Code fork，90% 继承上游；真正可偷的只是 `src/services/` 下几个独立闭环：memory decay+confidence+GC、heartbeat 四维自检、flat-file task protocol、5 条预置安全 hooks。每个模块 100–300 行，结构干净、各自自治——正是我们治理层缺的"小闭环"粒度。

## Architecture Overview

FreeClaude = Claude Code 上游（未偷过的部分不重复分析）+ 下述 fork-specific 层：

```
┌────────────────────────────────────────────────────────────┐
│ src/bootstrap/freeclaude.ts        (provider env injection)│
├────────────────────────────────────────────────────────────┤
│ src/services/tasks/protocol/                               │
│   taskProtocol.ts       (spawn detached + JSONL events)    │
│   taskRunner.mjs        (child process, bundled separately)│
│   taskScheduler.mjs     (cron-like, bundled separately)    │
├────────────────────────────────────────────────────────────┤
│ src/services/memory/                                       │
│   memoryStore.ts        (KV JSON + scope/ttl/category)     │
│   decay.ts              (confidence * (1-0.05)^days + GC)  │
│   consolidation.ts      (key/value similarity merge)       │
│   autoRemember.ts       (regex trigger patterns, RU+EN)    │
│   gbrainClient.ts       (external CLI wrapper + fallback)  │
│   contextEnricher.ts    (GBrain top-K + 4KB cap + LRU 20)  │
├────────────────────────────────────────────────────────────┤
│ src/services/heartbeat/ (4-dim health rollup + PID sweep)  │
│ src/services/cost/      (per-request JSONL cost log)       │
│ src/services/hooks/     (5 bundled default safety hooks)   │
│ src/services/agents/    (agentBridge: env-var inject)      │
├────────────────────────────────────────────────────────────┤
│ ROUTINES_PLAN.md        (20KB plan doc — not implemented)  │
└────────────────────────────────────────────────────────────┘
```

State lives as flat files under `~/.freeclaude/`: `memory.json`, `costs.jsonl`, `heartbeat.json`, `tasks/<id>/{task.json,events.jsonl}`. No SQLite. No service daemon; heartbeat is either on-demand or setInterval inside the CLI process.

## Six-Dimensional Scan

| Dimension | Finding |
|-----------|---------|
| **Security/Governance** | 5 预置 safety hooks（`prevent-secret-commit`、`prevent-rm-without-trash`、`auto-format-check`、`git-commit-tracker`、`long-task-notify`），全部 shell-level，通过 `exit 2` 物理拦截——不是 prompt 哄劝。Routines 计划里提到 Bearer token + HMAC-SHA256 GitHub webhook 验证，但**只在 plan 文档里，代码未实现**。 |
| **Memory/Learning** | `decay.ts`：confidence 0..1，默认 1.0，`pow(1-0.05, days)` 指数衰减；recall 重置为 1.0 并 ++accessCount；GC threshold 0.1 物理删除。`consolidation.ts`：key 相似度（子串/前缀/长度比） + value 词集 Jaccard，合并 tags、append 到更长 value 尾、保留 confidence 高者。`autoRemember.ts`：5 个 regex 模板（俄+英），"this project" 等短语触发 scope=project + ttlDays=90。 |
| **Execution/Orchestration** | `taskProtocol.ts`：`spawn(node, [runner, id, prompt], {detached:true, stdio:'ignore', env:{...}})` + `runner.unref()`；每 task 一个目录，`task.json` 状态 + `events.jsonl` 追加；cancel 用 `process.kill(pid,'SIGTERM')`；randomUUID().slice(0,8) 作短 ID。`agentBridge.ts`：通过 `OPENAI_BASE_URL/OPENAI_API_KEY/CLAUDE_CODE_USE_OPENAI=1` env 注入把父进程的 provider 配置透传给子 agent——shim 拦截 HTTP 层。 |
| **Context/Budget** | `contextEnricher.ts`：GBrain 搜 top-5 → 过滤 score≥0.5 → buildContextPrompt 截断到 4000 chars（按 entry 累加长度）→ 20 槽 LRU 缓存最近查询（`recentQueries.size > MAX_RECENT` 删 first key）。缓存命中用"子串双向包含"判断相似 query——粗糙但零依赖。 |
| **Failure/Recovery** | `heartbeat.ts::checkTasks`：扫 `~/.freeclaude/tasks/*.json`，对每个 `status:'running'` + 有 pid 的，用 `process.kill(pid, 0)` 探活；死进程 → 写 `status:'failed', error:'Process died unexpectedly'` + updatedAt。`checkProviders`：对每个 provider `GET {baseUrl}/models` + `AbortController` 5s 超时，超时归类为 `timeout` vs `error`。**无 doom-loop 检测、无 backoff**——provider 失败就 fallback，不做指数退避。 |
| **Quality/Review** | `costTracker.ts`：每请求 append `{provider, model, inputTokens, outputTokens, latencyMs, estimatedCost}` 到 `costs.jsonl`；`getCostSummary(since)` 线性扫全文件聚合。`heartbeat.overallHealth` 三档分类（healthy/degraded/critical）规则：部分 provider 挂=degraded，全挂=critical，memory.json 不可读=critical，有 stale tasks=至少 degraded。**无 eval 循环、无 adversarial probe**。 |

## Depth Layers (per-module trace)

| Layer | 核心发现 |
|-------|--------|
| **调度层** | `setInterval(runHeartbeat, 5*60*1000)` + `_intervalId` guard 防重复；task protocol 用 `detached:true + unref()` 让父进程退出后 runner 继续；没有 queue/DAG——每个 task 独立进程，互不感知。 |
| **实践层** | Decay 公式：`c = c * (1-0.05)^days`（每日复利衰减，不是 `exp(-rate*t)`）；Consolidation 用朴素成对比较 O(n²)，阈值 key=0.7/value=0.8；5 位短 ID 从 UUID slice 而来，依赖概率不碰撞（8 个十六进制=4B 空间）。 |
| **消费层** | `--json` 统一开关：`json ? printJson(value) : printText(summary)`；events.jsonl 对 tail / jq 友好；`heartbeat.json` 单文件单快照（覆盖写），非追加——外部进程读快照需容忍"写时读到半文件"。 |
| **状态层** | 全部 flat file；没有 schema migration、没有锁；`memory.json` 整读整写（load→mutate→save），并发写会丢数据；`events.jsonl` append-only 是唯一真正"安全并发"的文件。 |
| **边界层** | 大量 `try {...} catch { /* swallow */ }`——provider 探测、config 解析、GBrain import 全部失败静默；fetch+AbortController 5s 超时；`process.kill(pid, 0)` 做 liveness。**静默失败策略很激进**——假设 CLI 环境对用户无害，生产环境会丢故障信号。 |

## Path Dependency Speed-Assess

- **Locking decisions**:
  - 选 flat-file JSON/JSONL 而非 SQLite → 用户/桌面 UI 可直读，无需驱动；但无并发安全、无索引、全文件聚合成本 O(n)。
  - 选 OpenAI-compat shim (`CLAUDE_CODE_USE_OPENAI=1`) → 一键接 200+ OpenAI-compat provider；代价是永远无法用 Anthropic 原生 API 的能力（vision、tool use 的独特格式等）。
  - 继承 Claude Code 的 agent/swarm/tool 基础设施 → 受益于上游质量，但 fork merge 成本长期累积。
- **Missed forks**: 若选 SQLite + migrations，heartbeat/consolidation/eviction 都能用 SQL 表达；若做原生 multi-provider 客户端（不走 shim），能抽象出 provider capability 层（我们的 `capability_registry.py` 就是这条路）。
- **Self-reinforcement**: OpenAI-compat 生态越来越大（OpenRouter 聚合），shim 路径只会更强；ROUTINES_PLAN 显示作者在向 self-hosted Anthropic Routines 对标演化。
- **Lesson for us**: 学他们的**小闭环粒度**（每个模块单文件、100–300 行、自洽），不学他们的**存储选型**（我们已深度绑定 SQLite 且有 mixins，不倒退）。我们的维护 jobs 需要从 `dry_run=True` 走向物理执行——这是他们领先我们的点。

## Steal Sheet

### P0 — Must Steal (2 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Memory Physical GC with Confidence Decay** | `confidence = c * (1-0.05)^days`；recall → reset 1.0 + `accessCount++`；`gcMemories(threshold=0.1)` 物理删除；`getMemoryStats` 分 healthy/stale/dying 三档。 | 我们有 `stale_detector.py`（R65 Headroom）做**评分**但不删；`memory_hygiene` job 用 `apply_half_life(dry_run=True)`——扫到过期只 **报告**不删。Memory 文件长期只增不减。 | 在 `src/governance/memory/` 下新增 `memory_gc.py`：读 `SOUL/private/` 下 `*.md` frontmatter 的 `last_access_at` + `access_count`，计算 confidence，低于 0.1 移动到 `.trash/memory-gc/<date>/`（遵守"垃圾房"规则）。把 `maintenance.py::memory_hygiene` 从 dry_run 改为生产。同时在 recall 路径（memory 读取 API）写回 `last_access_at`。 | ~3h |
| **Cross-cutting Heartbeat Health Snapshot** | 单次调用扫 4 维：providers（HTTP ping+AbortController 5s）、memory（JSON readable+entry count）、tasks（`kill(pid,0)` sweep+mark failed）、disk；rollup 到 `overallHealth: healthy/degraded/critical`；覆盖写 `heartbeat.json` 快照。 | 我们有 per-module `health_check()`（channels/agent_bridge 等）但**无统一 snapshot**。`dispatch_lock.py` 用了 `os.kill(pid,0)` 但只在持锁路径；无周期性 task 表扫荡，僵尸 task 会永远停在 `status:running`。 | 新增 `src/jobs/health_snapshot.py`：复用现有 per-module health_check 输出 + `os.kill(pid, 0)` 扫 `tasks` 表 pid 字段 + 查 `~/.claude`/SOUL 磁盘占用；rollup 规则抄 `heartbeat.ts::runHeartbeat` 第 249–254 行；写入 `SOUL/public/heartbeat.json`。挂到 `scheduler.py` 5min cron。 | ~2h |

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Flat-file Task Protocol (JSONL events)** | `spawn(..., {detached:true, stdio:'ignore'})` + `unref()`；每 task 单目录 `task.json` + `events.jsonl` append；`process.kill(pid, 'SIGTERM')` cancel；`--json` 统一 CLI 开关。 | 我们 task 存 SQLite，外部工具要读必须接 DB。可考虑：scheduler 在写 tasks 表时**同时** append 一行到 `tmp/events/<task_id>.jsonl`，便于桌面 UI / `tail -f` 调试。保留 SQLite 作真相源，JSONL 作只读观测流。 | ~3h |
| **Pre-bundled Default Safety Hooks** | 5 条 shell hook 打包进 CLI（`prevent-secret-commit`、`prevent-rm-without-trash` 等），注册到 PreToolUse/PostToolUse；`exit 2` 物理拦截。 | 我们 `.claude/hooks/` 已经有 `block-protect.sh`、`dispatch-gate.sh`、`guard-rules.conf`。可补 `prevent-rm-without-trash.sh`（已在 CLAUDE.md 声明但未实装为 hook），把"删除=移 `.trash/`"规则从 prompt 级提升到 hook 级硬约束。 | ~1.5h |
| **AutoRemember Regex Trigger Matrix** | 5 个 regex 模板（`remember that X`、`my name is X`、`I prefer X` 等），match 后 `extract()` 生成 key/value；"this project/repo" 触发 scope=project + ttl=90d。 | 我们 `proactive/signals.py` 做被动检测。Regex 触发器可作为 proactive 层**显式 opt-in** 快路径——user 主动说"记住 X"时快速落盘，不等 LLM 提炼。加到 `src/proactive/signals.py` 或新文件 `explicit_memory_triggers.py`。 | ~2h |
| **ROUTINES_PLAN.md Stage Doc Format** | 开头 benchmark table（自己 vs Anthropic）→ use-case 矩阵 → stage 列表每个带 effort 标签 + 文件路径 + test 数量目标 + 安全考量。 | 对标 `SOUL/public/prompts/plan_template.md`：加两个章节头——"Benchmark vs X"（列已有方案对比）+ 每个 Stage 末尾显式 "Test count target: N+"。Plan 文档质量立增。 | ~1h（改模板） |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **GBrain binary resolver cascade** | 5-step fallback: env var → PATH (`which`) → `node_modules/.bin` → `npm root -g` → `npx`；首次解析缓存到闭包变量 `_resolvedBin`。 | 我们用 Python + 本地 venv，binary 解析场景基本不存在；级联 fallback 思路可在需要调外部 CLI 时借鉴。 |
| **Cost Tracker (per-request JSONL)** | 每请求 append `{provider, model, inTok, outTok, latency, estCost}` + 按 model prefix 匹配 cost 表。 | 我们不是 LLM 代理层，不直接计费；governance/budget 已有另一套。仅作格式参考。 |
| **Consolidation via key/value similarity** | 成对 O(n²) 比较 key（子串/前缀）+ value（词集 Jaccard），阈值 0.7/0.8，保留 confidence 高者合并 tags。 | 我们 `dedup.py` 用内容 hash，语义合并用 KB retrieval。朴素 Jaccard 对中文效果差，不直接适配。 |
| **Context Enricher w/ LRU** | GBrain 搜 → 4KB cap（entry 累加截断）→ 20 槽 query LRU 用"子串双向包含"做模糊命中。 | 我们 `governance/context/` 已有更复杂的 context budgeting；这个太粗糙。 |

## Comparison Matrix (P0 patterns)

### P0.1 Memory Physical GC with Confidence Decay

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Time decay scoring | `c * (1-0.05)^days`（复利） | `importance * exp(-0.1 * age_days)`（连续） | Small — 数学等价量级 | Keep ours |
| Access boost on recall | 重置 confidence → 1.0 + `++accessCount` | `min(1.0, 0.5 + access_count * 0.1)`，**不 reset confidence** | Small — 公式不同但概念一致 | Keep ours |
| Physical removal | `gcMemories(threshold=0.1)` 真删除 | `apply_half_life(dry_run=True)` **只报告** | **Large** | **Steal**：改 dry_run=False 并遵循"垃圾房"规则移到 `.trash/memory-gc/` |
| Recall 路径写回 | `recordAccess(key)` 每次 recall 调用 | 未在 recall 路径写回 `last_access_at` | Medium | **Steal**：memory 读 API 加 hook |
| 三档健康分类 | healthy/stale/dying by confidence | 我们不分 | Small | Enhance：getMemoryStats 等价函数加到 stale_detector |

### P0.2 Cross-cutting Heartbeat Health Snapshot

| Capability | Their impl | Our impl | Gap | Action |
|-----------|-----------|---------|-----|--------|
| Provider reachability | `fetch(/models)+AbortController 5s`，分 ok/error/timeout | 无 LLM provider；可对等为"channel adapter 健康" | N/A | Skip provider ping，但保留 **pattern**（超时细分类） |
| Task PID sweep | 遍历 tasks 目录，`kill(pid,0)` → 死就 mark failed + 写回 | `dispatch_lock.py` 用 `kill(pid,0)` **只**做锁释放，tasks 表**无** sweep | **Large** | **Steal** |
| 统一 JSON snapshot | `heartbeat.json` 单文件覆盖写 | 无全局 snapshot（per-module health_check 各自返回） | **Large** | **Steal** — 写 `SOUL/public/heartbeat.json` |
| Overall health rollup | 三档分类规则（第 249–254 行）| 无 | **Large** | **Steal** |
| Disk usage tally | `statSync` 递归遍历，返回 MB | `boot.md compiler` 报 `[db] 59M` 已有类似片段 | Small | Enhance — 扩到 `SOUL/` 总占用 |

### Triple Validation Gate

| Pattern | Cross-domain | Generative | Exclusivity | Score | Knowledge categories |
|---------|-------------|-----------|-------------|-------|---------------------|
| P0.1 Memory GC | ✅ (SuperMemory/SM-2/LRU eviction) | ✅ (新类型 memory 同公式适用) | ✅ (confidence + reset + 0.1 阈值组合) | **3/3** | pitfall memory（无限增长）、judgment heuristics（5%/0.1 校准）、hidden context（recall 算 access） |
| P0.2 Heartbeat | ✅ (systemd, k8s liveness, monit) | ✅ (新维度加入 rollup 规则不变) | ✅ (`kill(pid,0)` + 超时细分 + 三档 rollup 特定组合) | **3/3** | failure memory（僵尸 task）、judgment heuristics（健康阈值）、hidden context（signal 0 不 kill 只探活） |

## Gaps Identified

映射到 6 维：

- **Security/Governance**: N/A（freeclaude 这里比我们弱——只 5 条 shell hook，我们的 Gate Functions/block-protect/dispatch-gate 体系更强）。
- **Memory/Learning**: **Gap → P0.1**。我们扫描到过期但不清理，长期内存泄漏风险。
- **Execution/Orchestration**: **Gap → P1** (flat-file events.jsonl 观测流)。我们 SQLite 单点，外部只读观测需要 DB 驱动。
- **Context/Budget**: N/A（我们 `governance/context/` 更成熟）。
- **Failure/Recovery**: **Gap → P0.2**（统一 health snapshot + 僵尸 task sweep）。
- **Quality/Review**: N/A（他们无 eval 我们有 `governance/eval/`，反向可让他们偷）。

## Adjacent Discoveries

- **`unref()` pattern**：Node 的 `child.unref()` 让父进程事件循环忽略子进程，父退出后子仍活。Python 侧等价 `subprocess.Popen(..., start_new_session=True)` + close fd。我们 `scheduler.py` 或 jobs 分叉若需要"父死子不死"可借鉴。
- **`setInterval` + `_intervalId` guard**：防重入 `if (_intervalId) return`——比 boolean lock 省一行，直接用句柄做 guard。
- **18-entry provider registry (`KNOWN_PROVIDER_DEFINITIONS`)**：`slug + baseUrl + models[]` 三元组；`parseProviderQualifiedModel("openrouter/claude-sonnet-4")` 做 provider/model 解析。对我们 `capability_registry` 启发：用 "qualifier/name" 字符串语法比嵌套 dict 简洁。
- **"this project" 多语言检测**：俄+英混合 regex + substring 匹配——非 LLM 的 intent 路由可以很简单。

## Meta Insights

1. **小闭环优于大框架**：FreeClaude 真正有价值的代码是 4 个 100–300 行的独立模块（decay/heartbeat/taskProtocol/consolidation），每个自洽、无外部依赖、单文件。这验证了 R70 superpowers 的观察——**治理能力应按原子单元增长**，不要等"平台就绪"。
2. **scan-report-act 三段缺最后一段**：我们 `maintenance.py` 做 scan + report，`dry_run=True` 是口子；FreeClaude 直接做 act。区别仅一个 boolean。下一轮自治升级应系统审计所有 dry_run 路径，决定哪些升级到 enforce。
3. **Snapshot 覆盖写 vs 事件追加** 是一对正交选择：snapshot（heartbeat.json）适合"当前状态快速读"；事件流（events.jsonl、costs.jsonl）适合"历史审计 + tail"。我们 SQLite 把两者混了——`events_db` 存事件，但无独立 snapshot 文件供外部探测，未来 desktop/dashboard 层会吃这个亏。
4. **Fork 的价值浓度极低**：20 个模块里只 4 个值得偷。偷师一个 fork 的正确姿势是：先 diff 上游，只读 fork 特有文件，忽略继承的 90%。本轮如果从 README 入手会被"v3.0.0 端到端多表面"噪声淹没，直接扫 `src/services/` 才是对的。
5. **Stars=2 不代表价值=2**：本项目 stars 极低但结构清晰。"shallow steal rationalization"里的"This project is too simple to learn from"检查点再次被验证——简单项目的闭环反而更密集。
