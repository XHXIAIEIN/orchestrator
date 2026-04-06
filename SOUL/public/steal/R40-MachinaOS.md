# Round 40 — MachinaOS (trohitg/MachinaOS)

- **Date**: 2026-04-07
- **Source**: https://github.com/trohitg/MachinaOS
- **License**: MIT
- **Stars**: ~新项目（npm 发布，DeepWiki badge）
- **体量**: Python 1.9M + TypeScript 1.5M + JS 69K
- **定位**: "N8N + OpenClaw mashup" — Personal AI Assistant/Co-Employees，self-hosted
- **Tags**: ai, assistant, own-your-data, personal, secure, self-hosted, co-employees

## 项目概览

MachinaOS 是一个 **可视化 AI Agent 编排平台**，核心特征：
- 96 个 workflow 节点（21 类别）
- 10 个 LLM 提供商（Native SDK + LangChain 混合架构）
- 15 个专用 AI Agent（团队化编排）
- 89 个 WebSocket handler（几乎全 WS 通信）
- 49 个内置 Skill（10 类别，SKILL.md 格式）
- 三种执行模式（Temporal 分布式 → Redis 并行 → 顺序回退）

## 偷师模式清单

### P0 — 高优先级（直接可用）

#### 1. Continuous Scheduling（连续调度）⭐⭐⭐
**来源**: `server/services/execution/executor.py:293-458`

传统层执行（Layer-by-Layer）等所有同层节点完成才进入下一层。MachinaOS 用 `asyncio.wait(FIRST_COMPLETED)` 实现连续调度 — 任何节点完成立即检查并启动依赖节点。

```python
# 核心模式
done, pending_tasks = await asyncio.wait(
    pending_tasks, return_when=asyncio.FIRST_COMPLETED
)
for task in done:
    node = task_to_node[task]
    newly_ready = self._find_ready_nodes(ctx)  # 立即发现可启动的依赖
    for ready_node in newly_ready:
        create_node_task(ready_node)  # 不等其他节点
```

**价值**: Cron3(5s) 完成 → WS3 立即启动，不需要等 Cron1(20s)。真正的 DAG 并行。
**Orchestrator 适用**: 替换当前的层执行逻辑，提升多步 workflow 吞吐量。

#### 2. Conductor Decide + 分布式锁 ⭐⭐⭐
**来源**: `server/services/execution/executor.py:226-248`

Netflix Conductor 的 `decide()` 模式 + Redis `SETNX` 分布式锁：
```python
async with self.cache.distributed_lock(
    f"execution:{ctx.execution_id}:decide", timeout=60
):
    await self._decide_iteration(ctx, enable_caching)
```

**价值**: 防止并发 decide 竞争，同时允许真正的分布式执行。

#### 3. ExecutionContext 隔离 ⭐⭐⭐
**来源**: `server/services/execution/models.py`

每次 workflow 执行创建独立 `ExecutionContext`，不用全局 flag：
- `execution_id`: UUID
- `node_executions: Dict[str, NodeExecution]`: 每节点状态
- `outputs: Dict[str, Any]`: 结果缓存
- `checkpoints: List[str]`: 完成节点列表
- `errors: List[Dict]`: 错误记录

**价值**: 支持并发执行多个 workflow，状态可持久化/恢复。

#### 4. Null Object + Factory 模式（DLQ）⭐⭐
**来源**: `server/services/execution/dlq.py`

DLQ 用 Protocol + NullObject 实现优雅的可选功能：
```python
class NullDLQHandler:  # 禁用时 no-op
    async def add_failed_node(...) -> bool: return True

class DLQHandler:  # 启用时 Redis 存储
    async def add_failed_node(...) -> bool: ...

def create_dlq_handler(cache, enabled=bool):
    return DLQHandler(cache) if enabled else NullDLQHandler()
```

**价值**: 零开销的可选功能，不需要到处 `if dlq_enabled`。

#### 5. Model-Aware Compaction 阈值 ⭐⭐⭐
**来源**: `server/services/compaction.py:91-198`

三级阈值策略 + 原生 API 集成：
```
优先级: per-session custom_threshold > model_context_length × ratio > global default (100K)
```

直接调用提供商原生压缩 API：
- Anthropic: `compact-2026-01-12` beta + `input_tokens` trigger
- OpenAI: `context_management.compact_threshold`
- 其他: 客户端摘要 fallback

**价值**: 我们的 compaction 是手动的，MachinaOS 用模型感知阈值 + 原生 API 自动触发。

#### 6. 细粒度成本追踪 ⭐⭐⭐
**来源**: `server/services/pricing.py`, `server/services/compaction.py:137-198`

```python
@dataclass
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float    # Anthropic
    reasoning_per_mtok: float     # OpenAI o-series

# 匹配策略: 精确 → 前缀 → 包含 → provider default → 全局 fallback
```

Session 累计追踪:
```python
return {
    "total": new_total,           # 累计 tokens
    "total_cost": new_total_cost, # 累计美元
    "cost": cost,                 # 本次明细
    "threshold": threshold,       # 压缩阈值
    "context_length": context_length,
    "needs_compaction": bool      # 是否该压缩了
}
```

**价值**: Orchestrator 目前没有 per-session 成本追踪，这是 dashboard 的重要数据源。

#### 7. Connection-Based Agent Composition ⭐⭐
**来源**: `server/services/handlers/ai.py:17-299`

Agent 的能力通过图边（edge）发现，不是静态配置：
```
Agent ← [input-memory]    ← simpleMemory
      ← [input-skill]     ← skill/masterSkill
      ← [input-tools]     ← tool/androidTool/aiAgent
      ← [input-main]      ← 任意节点(auto-prompt)
      ← [input-task]       ← taskTrigger(委派结果)
```

支持嵌套发现：child agent 的 tools 也可被探测。

**价值**: 动态 agent 组合，比硬编码配置灵活得多。

#### 8. Skill 渐进式加载 ⭐⭐
**来源**: `server/services/skill_loader.py:49-88`

```python
scan_skills()       # 仅元数据 (~100 tokens/skill)
load_skill(name)    # 完整内容 (~5000 tokens max)
```

三源优先级: `server/skills/` > `.machina/skills/` > Database

DB 是最终真相源 — 用户编辑保存到 DB，filesystem 仅做初始 seed。

**价值**: 我们的 skill 是全量加载的，渐进式可以显著减少 context 使用。

### P1 — 中优先级（参考设计）

#### 9. Agent Teams — 共享任务池 + 消息系统
**来源**: `server/services/agent_team.py:31-247`

```python
create_team(team_lead_node_id, teammate_node_ids, workflow_id, config)
add_task(title, created_by, priority, depends_on)
claim_task(task_id, agent_node_id)      # agent 抢单
send_message() / broadcast()            # 点对点 + 广播
get_claimable_tasks()                   # 依赖已满足的任务
is_team_done()                          # 团队完成检测
```

支持 parallel/sequential/hybrid 模式。

**参考点**: 我们的三省六部是角色固定、制度驱动。MachinaOS 是动态组队、任务驱动。两种范式各有优势。

#### 10. delegate_to_* 自动工具注入
**来源**: README, `server/services/handlers/ai.py`

Team lead 节点自动为每个连接的 teammate 生成 `delegate_to_<type>` 工具。不需要手动配置 — 连线即生成。

**参考点**: 我们的派单是 Governor 中心化分发。MachinaOS 是去中心化的 — lead 自行决定何时 delegate。

#### 11. 三执行模式 + 自动降级
**来源**: `server/services/workflow.py:188-250`

```
Temporal (分布式, per-node activities + retry)
  → 不可用则降级
Redis Parallel (Conductor decide + fork/join)
  → 不可用则降级
Sequential (拓扑排序遍历)
```

**参考点**: 我们只有 Docker 内的顺序执行。Temporal 集成是未来方向。

#### 12. RetryPolicy + 错误分类重试
**来源**: `server/services/execution/models.py:50-99`

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 1.0
    backoff_multiplier: float = 2.0
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    retry_on_server_error: bool = True  # 5xx
```

按错误类型决定是否重试（timeout/connection/5xx），不是盲重试。

#### 13. RecoverySweeper — 心跳检测恢复
**来源**: `server/services/execution/recovery.py`

后台循环扫描活跃执行：
- 节点 RUNNING 但无心跳 → 标记 stuck
- 超过 heartbeat_timeout (300s) → 触发 recovery callback
- 启动时 `scan_on_startup()` 恢复中断的执行

#### 14. Template 变量系统 `{{nodeLabel.field}}`
**来源**: `server/services/parameter_resolver.py`

节点输出可通过 `{{label.field}}` 在参数中引用。大小写不敏感，递归解析嵌套对象/数组。

#### 15. Personality Skill 覆盖系统消息
**来源**: `server/services/skill_prompt.py`

以 `-personality` 结尾的 skill 注入完整指令并替换默认系统消息。普通 skill 只注入简要描述。`has_personality` 标志位决定是否丢弃默认 system prompt。

#### 16. ThinkingConfig 统一推理配置
**来源**: `server/services/ai.py:179-194`

```python
@dataclass
class ThinkingConfig:
    enabled: bool
    budget: int = 2048       # Claude, Gemini 2.5
    effort: str = 'medium'   # OpenAI o-series
    level: str = 'medium'    # Gemini 3+
    format: str = 'parsed'   # Groq
```

统一了不同提供商对"推理/思考"的异构 API。

### P2 — 低优先级（灵感库）

#### 17. Pydantic Discriminated Union 路由
`server/models/nodes.py` — O(1) 哈希查找代替 O(n) if-elif 链。

#### 18. 多 Output Handle 存储
节点结果同时写入多个 output key（`output_main`/`output_top`/`output_0`），不同消费者读不同 handle。

#### 19. Android Sub-Node 递归发现
`androidTool` 节点 → 递归扫描连接的 Android services。n8n Sub-Node 模式。

#### 20. 条件路由 18 种操作符
包含 regex match、类型检查、exists/empty，以及"条件边优先、无条件边回退"的决策逻辑。

#### 21. Claude Code Agent 集成模式
`server/services/handlers/claude_code.py` — 把 Claude Code SDK 包装成 workflow 节点，支持 model/cwd/allowedTools/maxTurns/maxBudgetUsd 参数。

#### 22. Deployment Manager — Per-Workflow 部署
每个 workflow 独立部署/取消/查状态。支持 Cron/Start/Event 三种 trigger 类型。

## 模式统计

| 级别 | 数量 | 描述 |
|------|------|------|
| P0 | 8 | 直接可用：连续调度、Conductor decide、ExecutionContext 隔离、Null Object DLQ、Model-Aware Compaction、细粒度成本追踪、Connection-Based 组合、Skill 渐进加载 |
| P1 | 8 | 参考设计：Agent Teams、delegate_to_* 注入、三模式降级、RetryPolicy、RecoverySweeper、Template 变量、Personality Skill、ThinkingConfig |
| P2 | 6 | 灵感库：Discriminated Union、多 Handle、Sub-Node 递归、条件路由、Claude Code 集成、Per-Workflow 部署 |
| **Total** | **22** | |

## 与 Orchestrator 差异对照

| 维度 | MachinaOS | Orchestrator |
|------|-----------|-------------|
| **编排范式** | 可视化 DAG（n8n 风格） | 制度驱动（三省六部） |
| **Agent 组织** | 动态组队 + 任务池抢单 | 固定部门 + Governor 派单 |
| **执行引擎** | Conductor decide + FIRST_COMPLETED | 顺序 + stuck_detector |
| **成本追踪** | per-session 累计 + pricing.json | 无（TODO） |
| **Skill 系统** | SKILL.md + DB 真相源 + 渐进加载 | SKILL.md 全量加载 |
| **内存管理** | 原生 API compaction + model-aware 阈值 | 手动 compaction |
| **前端** | React Flow 画布 + Dracula 主题 | Dashboard（简单展示） |
| **部署** | npm 全局包 + one-liner install | Docker Compose |

## 核心偷师价值

1. **连续调度 + FIRST_COMPLETED** — 这是执行引擎的范式升级，我们的层执行太浪费了
2. **Model-Aware Compaction** — 用模型上下文窗口计算阈值，不是固定值
3. **细粒度成本追踪** — input/output/cache/reasoning 分别计费，session 累计
4. **Skill 渐进加载** — 扫描时只读元数据，使用时才加载全文
5. **Null Object 模式** — 可选功能的零开销实现，比 if-else 优雅得多
