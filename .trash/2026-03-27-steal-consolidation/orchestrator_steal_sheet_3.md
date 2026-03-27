---
name: orchestrator-steal-sheet-3
description: 2026-03-26 第三轮偷师：Top 5 Agentic Search（Brave/Firecrawl/Exa/Parallel/Tavily）— 6 个模式已实施
type: project
---

## 来源（AIMultiple 2026 Agentic Search Benchmark Top 5）

1. Brave Search (14.89) — 独立索引400亿页、Goggles DSL、LLM Context API token budget
2. Firecrawl (14.58) — 开源爬取+搜索、LLM-ready markdown（待研究完成）
3. Exa AI (14.39) — 神经搜索引擎、link prediction 范式、costDollars 透明计费
4. Parallel Search Pro (14.21) — objective 语义意图、token 相关性排序、warnings 不静默失败
5. Tavily (13.67) — AI Agent 搜索中间件、depth tiers、参数锁死

## 已实施（6 个模式）

### 偷自 Tavily
1. ✅ **Depth Tiers 深度档位** — `src/core/llm_router.py`
   - 4 档与 task_type 正交，generate() 新增 `depth` 参数

2. ✅ **Parameter Locking 参数锁死** — `src/channels/config.py`
   - LOCKED_PARAMS + runtime_override() / runtime_get() / runtime_reset()

3. ✅ **Param Sanitization 参数清洗** — `src/core/params.py`（新文件）
   - sanitize_params() + merge_defaults()

### 偷自 Exa + Parallel
4. ✅ **Cost Metadata 成本元数据** — `src/core/llm_router.py`
   - GenerateResult dataclass: text + model_used + latency_ms + cost_dollars + attempts + warnings
   - generate() 向后兼容返回 str，generate_rich() 返回 GenerateResult
   - _estimate_cost() 基于 MODEL_TIERS.cost 估算美元成本

### 偷自 Parallel
5. ✅ **Warnings 不静默失败** — `src/core/warnings.py`（新文件）
   - WarningCollector: 线程安全、severity 分级、可合并
   - warning_context() 上下文管理器 + get_collector() 全局收集器

### 偷自 Brave
6. ✅ **Context Threshold 语义枚举** — `src/core/llm_router.py`
   - THRESHOLD_MODES: strict(50) / balanced(10) / lenient(3) / disabled(0)
   - generate() 新增 `threshold` 参数，cascade 内部用 min_len 替代硬编码

## 未实施（备忘）

### P1 — 架构级
- **Firecrawl Feature Flag 引擎选择** — 声明式 flag+优先级矩阵选引擎，替代 if-else 链 → llm_router 模型选择
- **Firecrawl Transformer Pipeline** — 18 步纯函数管道（raw→clean→enrich→respond）→ channel 消息处理
- **Firecrawl Job 原子化** — 大任务拆小 scrape job 分布式执行 → 三省六部长任务
- Exa 三角色多智能体（Planner/Task/Observer）→ 三省六部任务编排
- Exa Snippet-first 策略 → Agent 工具调用优化
- Brave Mixed 布局对象（分区存储 + 引用式布局）→ 多源结果聚合
- Parallel objective 语义意图接口 → Governor 派单系统
- Brave Token Budget 多维控制 → RAG context 构建
- Tavily 异步 Research 模式（request_id + 指数退避 + SSE）→ 长任务

### P2 — 产品级
- Firecrawl git-diff 做变更检测 → 内容监控
- Firecrawl Search+Scrape 一体化 → wake channel web search
- Brave Goggles DSL（自定义重排规则）→ 用户搜索偏好
- Exa outputSchema 结构化输出 + 字段级引用 → research 任务
- Exa maxAgeHours 缓存控制 → 内容获取层
- Brave 工具白名单/黑名单 → MCP 多租户
- Tavily Hybrid RAG 双源融合 → Construct3-RAG
- Tavily Prompt Injection 防火墙 → Channel 层

## 详细研究报告
- Firecrawl: `tmp/research-2026-03-26/firecrawl-steal-sheet.md`
