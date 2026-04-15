# R61-R75 深度偷师汇总 — P0 实施计划

**日期**: 2026-04-14
**分支**: steal/round-deep-rescan-r60
**报告总量**: 15份，10,544行，覆盖15个项目的原子级代码分析

## Implementation Status (2026-04-14)

### Tier 1 + Tier 1+ (14/14 完成)

| # | 模式 | 状态 | Commit / 实现文件 |
|---|------|------|--------|
| 1 | 查询污染防护 (query_sanitizer) | ✅ 完成 | `src/storage/query_sanitizer.py` + qdrant_store.search() 集成 |
| 2 | CSO description 规范审计 | ✅ 完成 | `14b3699` 7/9 skills trimmed |
| 3 | Iron Law 代码围栏 | ✅ 完成 | `2153432` verification-gate + systematic-debugging |
| 4 | SUBAGENT-STOP 标签 | ✅ 完成 | `2153432` persona + doctor + prime |
| 5 | 原子写保护 (os.replace + fsync) | ✅ 完成 | `src/core/atomic_write.py` + compiler/synthesizer 集成 |
| 6 | SQLite Unicode casefold (CJK) | ✅ 完成 | `src/storage/pool.py` orch_lower() 注册到每个连接 |
| 7 | python3 atomic JSONL append | ✅ 完成 | `src/core/atomic_write.py` atomic_append_jsonl + _sessions_mixin 集成 |
| 8 | Nonce boundary + HTML strip | ✅ 完成 | `14b3699` boundary_nonce.py |
| 29 | 结构化错误反馈 | ✅ 完成 | `14b3699` guard-redflags.sh 14 patterns |
| 30 | Budget 优雅摘要 | ✅ 完成 | `14b3699` context-threshold-stop.py |
| 31 | Sentinel 完成字符串 | ✅ 完成 | `14b3699` dispatch-gate.sh DONE/PARTIAL/STUCK |
| 32 | LoopCounter 硬性上限 | ✅ 完成 | `14b3699` loop-detector.sh + guard-redflags.sh 双 hook |
| 33 | 子 agent 并行强制 | ✅ 完成 | `14b3699` dispatch-gate.sh PARALLEL MANDATE |
| 34 | API 消除模式 | ⬜ N/A | 当前无库内嵌辅助 LLM 调用，模式记录为设计原则 |

### Tier 2 (9/9 完成)

| # | 模式 | 状态 | 实现文件 |
|---|------|------|---------|
| 9 | 双层循环检测 (Hash+频率) | ✅ 完成 | `src/governance/safety/loop_detection.py` |
| 10 | 三态熔断器 + 指数退避 | ✅ 完成 | `src/core/circuit_breaker.py` |
| 11 | 时间分层记忆合成 | ✅ 完成 | `SOUL/tools/memory_synthesizer.py` (enhanced) |
| 12 | 两阶段时间检索 SQL | ✅ 完成 | `src/storage/temporal_recall.py` |
| 13 | Runtime 对象 DI 注入 | ✅ 完成 | `src/core/runtime.py` + executor/session 迁移 |
| 14 | xxh3 内容寻址缓存 | ✅ 完成 | `src/governance/content_cache.py` |
| 15 | Protected file 三态检查 | ✅ 完成 | `.claude/hooks/config-protect-3state.sh` |
| 16 | Working Path Lock | ✅ 完成 | `src/governance/working_path_lock.py` |
| 17 | Idle Timeout 死锁检测 | ✅ 完成 | `src/governance/safety/idle_timeout.py` |

### Tier 2+ (9/9 完成)

| # | 模式 | 状态 | 实现文件 |
|---|------|------|---------|
| 35 | 三层信号提取 (Regex→Keyword→LLM) | ✅ 完成 | `src/governance/signals/signal_extractor.py` |
| 36 | 信��历史去重 (stagnation detection) | ✅ 完成 | `src/governance/signals/signal_extractor.py` (SignalHistory) |
| 37 | 闲置感知调度 | ✅ 完成 | `src/governance/scheduling/idle_scheduler.py` |
| 38 | 执行引擎三层降级 | ✅ 完成 | `src/core/execution_router.py` |
| 39 | EventWaiter 统一触发器 | ✅ 完成 | `src/core/event_waiter.py` |
| 40 | BlackboardMemory 共享写板 | ✅ 完成 | `src/governance/context/blackboard.py` |
| 41 | 组织文化变量注入 | ✅ 完成 | `src/governance/context/culture_inject.py` |
| 42 | 查询结果回写记忆闭环 | ✅ 完成 | `src/governance/learning/query_writeback.py` |
| 43 | CompactionService 三层阈值 | ✅ 完成 | `src/governance/condenser/context_condenser.py` |

## 总览

| Round | 项目 | 类型 | 行数 | P0数 | 核心发现 |
|-------|------|------|------|------|----------|
| R61 | Codex CLI | 完整框架 | 743 | 6 | 自适应流式渲染、Guardian增量Cursor、消息语义区分 |
| R62 | DeerFlow | 完整框架 | 933 | 4 | 双层循环检测、三态熔断器、DanglingToolCall修复 |
| R63 | Archon | 完整框架 | 681 | 3 | Working Path Lock、Idle Timeout死锁检测、Provider能力位 |
| R64 | Hindsight | 记忆模块 | 898 | 4 | 四种记忆类型、三阶段事务、两阶段时间检索SQL |
| R65 | Headroom | 上下文压缩 | 728 | 4 | MCP Memory Hub、双向Sync防回声、Git感知陈旧检测 |
| R66 | yoyo-evolve | 自进化系统 | 824 | 6 | 三层时间压缩记忆合成、Checkpoint-Restart、层边界自知 |
| R67 | MemPalace | 记忆模块 | 636 | 4 | 查询污染防护(89.8%→1.0%)、原子写保护、时态KG |
| R68 | LangGraph | 完整框架 | 778 | 3 | Runtime DI注入、图回调钩子、xxh3内容寻址缓存 |
| R69 | Memos | 特定模块 | 600 | 2 | CEL→SQL编译器、SQLite Unicode CJK搜索 |
| R70 | Superpowers | 技能系统 | 775 | 6 | CSO description规范、Iron Law围栏、借口表 |
| R71 | Hermes Agent | 完整框架 | 416 | 2 | pre_tool_call阻断+结构化错误反馈、Budget耗尽优雅摘要 |
| R72 | Evolver | 自进化系统 | 576 | 4 | 三层信号提取、信号历史去重防修复循环、闲置感知调度 |
| R73 | MachinaOS | 完整框架 | 767 | 4 | 执行引擎三层降级、EventWaiter统一触发器、CompactionService |
| R74 | ChatDev | 完整框架 | 718 | 4 | Sentinel完成判断、LoopCounter硬性上限、BlackboardMemory |
| R75 | Graphify | 特定模块 | 471 | 3 | 查询结果回写记忆闭环、API消除模式、子agent并行强制规则 |

**合计**: P0 = 59个模式，P1 ≈ 35个，P2 ≈ 20个

---

## P0 优先级排序（按 ROI 从高到低）

### Tier 1 — 立即执行（< 2h/项，收益极高）

| # | 模式 | 来源 | 工时 | 解决什么问题 |
|---|------|------|------|-------------|
| 1 | **查询污染防护 (query_sanitizer)** | R67 MemPalace | 0.5天 | 系统提示前缀污染向量搜索，召回率89.8%→1.0% |
| 2 | **CSO description 规范审计** | R70 Superpowers | 2h | skill description 含 workflow 摘要导致 LLM 跳过正文 |
| 3 | **Iron Law 代码围栏 + 借口表** | R70 Superpowers | 2h | 纪律型规则用 monospace 围栏 + rationalization table |
| 4 | **SUBAGENT-STOP 标签** | R70 Superpowers | 1h | 防止 subagent 读到 orchestrator-only 内容 |
| 5 | **原子写保护 (os.replace + fsync)** | R67 MemPalace | 2h | 防 crash 时数据文件损坏 |
| 6 | **SQLite Unicode 函数注册** | R69 Memos | 1h | CJK 大小写不敏感搜索，10行代码 |
| 7 | **python3 heredoc 原子写 JSONL** | R66 yoyo-evolve | 1h | experiences.jsonl 写入安全 |
| 8 | **Nonce boundary + HTML comment strip** | R66 yoyo-evolve | 1h | Telegram/WeChat 外部输入防注入 |

### Tier 2 — 本周执行（2-4h/项，架构级改进）

| # | 模式 | 来源 | 工时 | 解决什么问题 |
|---|------|------|------|-------------|
| 9 | **双层循环检测 (Hash+频率)** | R62 DeerFlow | 3h | tool call 循环检测：order-independent md5 hash + 按类型累计 |
| 10 | **三态熔断器 + 指数退避** | R62 DeerFlow | 3h | LLM API 调用保护：closed/open/half_open + Retry-After |
| 11 | **时间分层记忆合成 (synthesize)** | R66 yoyo-evolve | 4h | MEMORY.md 膨胀问题：Recent全文/Medium摘要/Old按主题 ≤200行 |
| 12 | **两阶段时间检索 SQL** | R64 Hindsight | 2h | 先日期索引缩范围再计算嵌入距离，防全表扫描 |
| 13 | **Runtime 对象 DI 注入** | R68 LangGraph | 3h | 替代 configurable dict 裸传，有类型、有 IDE 补全 |
| 14 | **xxh3 内容寻址缓存** | R68 LangGraph | 1.5h | 同 prompt 两次调用命中缓存，改 cache key 生成逻辑 |
| 15 | **Protected file 三态检查** | R66 yoyo-evolve | 2h | committed+staged+unstaged 三层检查，比单次 guard 强 |
| 16 | **Working Path Lock** | R63 Archon | 2h | DB 行级分布式锁 + older-wins tiebreaker |
| 17 | **Idle Timeout 死锁检测** | R63 Archon | 1.5h | Symbol sentinel + Promise.race 转 clean return |

### Tier 3 (11/11 完成)

| # | 模式 | 状态 | 实现文件 |
|---|------|------|---------|
| 18 | Guardian Transcript Cursor | ✅ 完成 | `src/governance/guardian/transcript_cursor.py` |
| 19 | QueueOnly vs TriggerTurn 通信 | ✅ 完成 | `src/core/agent_message.py` |
| 20 | DanglingToolCall 修复 | ✅ 完成 | `src/governance/pipeline/dangling_tool_fix.py` |
| 21 | 原子事实分拆存储 | ✅ 完成 | `src/governance/learning/atomic_fact_splitter.py` |
| 22 | Git 感知陈旧记忆检测 | ✅ 完成 | `src/governance/memory/stale_detector.py` |
| 23 | 三阶段事务拆分 | ✅ 完成 | `src/governance/transaction/three_phase.py` |
| 24 | CEL→SQL 编译器 | ✅ 完成 | `src/governance/filter/cel_compiler.py` |
| 25 | OperationValidator 双向钩子 | ✅ 完成 | `src/governance/operation_validator.py` |
| 26 | Checkpoint-Restart 协议 | ✅ 完成 | `src/governance/checkpoint_recovery.py` (enhanced) |
| 27 | 图回调钩子 (GraphCallbackHandler) | ✅ 完成 | `src/core/lifecycle_hooks.py` (+on_interrupt/on_resume) |
| 28 | MCP Memory Hub | ✅ 完成 | `src/mcp/memory_server.py` (+memory_save, shared scope) |

### Tier 1+ — Batch 3 新增立即执行项

| # | 模式 | 来源 | 工时 | 解决什么问题 |
|---|------|------|------|-------------|
| 29 | **pre_tool_call 阻断 + 结构化错误反馈** | R71 Hermes | 1h | guard-redflags.sh 只有 exit code，缺让模型看到结构化错误的反馈环 |
| 30 | **Budget 耗尽优雅摘要** | R71 Hermes | 1h | agent max_turns 耗尽时加 graceful summary path 而非直接截断 |
| 31 | **Sentinel 完成字符串** | R74 ChatDev | 1h | `<INFO> Finished` 比自然语言完成判断可靠 100 倍 |
| 32 | **LoopCounter 硬性上限** | R74 ChatDev | 1h | critic-revise 循环当前无硬性上限是明确缺陷 |
| 33 | **子 agent 并行强制规则** | R75 Graphify | 0.5h | SKILL.md 写死"逐个读文件 forbidden，必须并行派遣" |
| 34 | **API 消除模式** | R75 Graphify | 2h | 辅助性 API 调用权上移给 orchestrator，库保持零依赖 |

### Tier 2+ — Batch 3 新增架构级改进

| # | 模式 | 来源 | 工时 | 解决什么问题 |
|---|------|------|------|-------------|
| 35 | **三层信号提取** | R72 Evolver | 3h | Regex→加权关键词→LLM语义，分级提取效率最优 |
| 36 | **信号历史去重 (stagnation detection)** | R72 Evolver | 2h | 同一信号8轮≥3次→强制创新，防陷入修复循环 |
| 37 | **闲置感知调度** | R72 Evolver | 2h | 系统闲置>5min触发蒸馏+反思，Win/macOS/Linux三平台 |
| 38 | **执行引擎三层降级** | R73 MachinaOS | 4h | Temporal→Redis→Sequential 按基础设施自动路由 |
| 39 | **EventWaiter 统一触发器** | R73 MachinaOS | 3h | register/wait_for_event/dispatch 原语，新增类型只需3步 |
| 40 | **BlackboardMemory 共享写板** | R74 ChatDev | 3h | sub-agent 间共享状态，角色读写权限分离 |
| 41 | **组织文化变量注入** | R74 ChatDev | 1h | `${ORCHESTRATOR_CONTEXT}` 注入所有 sub-agent 建立统一身份 |
| 42 | **查询结果回写记忆闭环** | R75 Graphify | 2h | 每次 query 结果存为 Markdown 记忆，知识从自身推理中生长 |
| 43 | **CompactionService 三层阈值** | R73 MachinaOS | 3h | per-session > model-aware 50% context > 全局默认 |

### 需要重新审视的现有实现

| 现有组件 | 问题 | 来源 | 建议 |
|----------|------|------|------|
| `env-leak-scanner.sh` | 与 Archon 已删除的方案走同一条错误路线 | R63 | 转向结构性防护：stripCwdEnv() + --no-env-file |
| `guard.sh` regex 检查 | 只做 regex 匹配，不如 Codex Guardian 的 sub-agent+cursor 模式 | R61 | 评估是否升级为 sub-agent 审计 |
| `configurable` dict 裸传 | ~~无类型、无 IDE 补全、容易拼错 key~~ | R68 | ✅ 已迁移到 `AgentRuntime` frozen dataclass |
| `agent_cache.py` 用随机 task_id 做 key | 同 prompt 两次调用不命中缓存 | R68 | 改为 xxh3 内容寻址 |
| `guard-redflags.sh` exit code only | 只有 pass/fail，模型看不到结构化错误原因 | R71 | 加结构化 JSON 错误反馈 |
| critic-revise 无上限 | 循环可能无限进行 | R74 | 加 LoopCounter 硬性上限 |

---

## Meta Insights（跨 10 个项目的战略洞察）

### 1. 记忆系统进入"互操作"时代
Headroom 的 MCP Memory Hub + Hindsight 的 Claude Code hook + MemPalace 的时态 KG —— 三个独立项目同时在做跨 Agent 记忆共享。这不是巧合，是趋势。我们的记忆系统还是单 Agent 封闭的，需要尽快加入 MCP 记忆互操作层。

### 2. "防御性编程"不够，要"结构性防护"
Archon 删掉了 env-leak-scanner（我们还在用的同类方案），转向 stripCwdEnv + --no-env-file。yoyo-evolve 的三态检查比单次 guard 强一个数量级。趋势：从"扫描检测"转向"结构性不可能"。

### 3. Prompt 工程有了工业标准
Superpowers 的 28,000 次对话测试产出的规范（CSO description、Iron Law围栏、借口表、SUBAGENT-STOP）不是风格偏好，是经验证的工程标准。我们的 skills 需要用这套标准审计一遍。

### 4. 循环检测和熔断器是下一代 Agent 必备
DeerFlow 的双层循环检测 + 三态熔断器、Archon 的 Idle Timeout 死锁检测 —— 这些不是"nice to have"，而是 Agent 在生产环境稳定运行的前提。我们的循环检测（loop-detector.sh）还停留在简单计数器阶段。

### 5. 自进化系统的关键不是"更多反思"而是"层边界自知"
yoyo-evolve Day 42 的 meta-insight：反思对意图-执行层有效，对 pipeline 机械层无效。正确响应不是"更多反思"而是"trace the log"。这条原则值得写入 boot.md。

### 6. 执行引擎需要分级降级能力
MachinaOS 的 Temporal→Redis→Sequential 三层降级 + Evolver 的闲置感知调度，揭示了一个趋势：Agent 不能假设运行环境是固定的。基础设施在线就用分布式，离线就退化到本地，但接口不变。

### 7. 信号去重比信号提取更重要
Evolver 的核心洞察：同一问题反复出现3次不是"重要"，是"停滞"。连续 repair ≥3 次应该强制切换策略（创新），而不是继续修。这直接适用于我们的 steal 和 debug 循环。

### 8. "完成"需要机器可判断的标志
ChatDev 的 `<INFO> Finished` sentinel 比让 LLM 用自然语言判断"是否完成"可靠 100 倍。所有 sub-agent 协议都应该有明确的终止 sentinel，而不是依赖语义理解。
