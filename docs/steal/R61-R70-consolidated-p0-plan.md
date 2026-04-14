# R61-R70 深度偷师汇总 — P0 实施计划

**日期**: 2026-04-14
**分支**: steal/round-deep-rescan-r60
**报告总量**: 10份，7,596行，覆盖10个项目的原子级代码分析

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

**合计**: P0 = 42个模式，P1 ≈ 25个，P2 ≈ 15个

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

### Tier 3 — 本轮执行（4-8h/项，系统级改进）

| # | 模式 | 来源 | 工时 | 解决什么问题 |
|---|------|------|------|-------------|
| 18 | **Guardian Transcript Cursor** | R61 Codex | 4h | guardian 重审只传增量，不重传完整历史 |
| 19 | **QueueOnly vs TriggerTurn 通信** | R61 Codex | 3h | sub-agent 消息精确区分"入队不触发"和"立即唤醒" |
| 20 | **DanglingToolCall 修复** | R62 DeerFlow | 3h | wrap_model_call 在正确位置插入合成 ToolMessage |
| 21 | **原子事实分拆存储** | R65 Headroom | 4h | 对话→原子事实，单次 LLM 调用提取 |
| 22 | **Git 感知陈旧记忆检测** | R65 Headroom | 3h | git ls-files 检查记忆引用的文件是否还存在 |
| 23 | **三阶段事务拆分** | R64 Hindsight | 4h | 锁外解析→原子写入→事务后补充，并发安全 |
| 24 | **CEL→SQL 编译器** | R69 Memos | 4h | 用户 CEL 表达式编译成参数化 SQL，消除注入 |
| 25 | **OperationValidator 双向钩子** | R64 Hindsight | 3h | pre/post 操作钩子，governor pipeline 扩展点 |
| 26 | **Checkpoint-Restart 协议** | R66 yoyo-evolve | 4h | 语义checkpoint + 机械checkpoint 两种断点续传 |
| 27 | **图回调钩子 (GraphCallbackHandler)** | R68 LangGraph | 2h | interrupt/resume 生命周期类型化钩子 |
| 28 | **MCP Memory Hub** | R65 Headroom | 6h | 跨 Agent 共享 SQLite 记忆库(memory_search/memory_save) |

### 需要重新审视的现有实现

| 现有组件 | 问题 | 来源 | 建议 |
|----------|------|------|------|
| `env-leak-scanner.sh` | 与 Archon 已删除的方案走同一条错误路线 | R63 | 转向结构性防护：stripCwdEnv() + --no-env-file |
| `guard.sh` regex 检查 | 只做 regex 匹配，不如 Codex Guardian 的 sub-agent+cursor 模式 | R61 | 评估是否升级为 sub-agent 审计 |
| `configurable` dict 裸传 | 无类型、无 IDE 补全、容易拼错 key | R68 | 迁移到 Runtime dataclass |
| `agent_cache.py` 用随机 task_id 做 key | 同 prompt 两次调用不命中缓存 | R68 | 改为 xxh3 内容寻址 |

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
