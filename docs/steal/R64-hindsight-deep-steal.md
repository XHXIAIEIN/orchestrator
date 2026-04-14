# R64 深度偷师报告：Hindsight 仿生记忆系统

> **来源**: vectorize-io/hindsight
> **日期**: 2026-04-14
> **Round**: R64（深度复扫，基于 2026-04-01 表层报告升级）
> **分支**: steal/round-deep-rescan-r60
> **分析员**: Orchestrator

---

## TL;DR

上次（R28）的报告是架构草图。这次读了实际源代码：`hindsight-api-slim/`（6000+ 行核心引擎）、`hindsight-clients/python/`（HTTP 客户端）、`hindsight-integrations/claude-code/`（原生集成）。

关键发现三条：
1. **三阶段保留流水线**比想象的精密得多——Phase 1（读锁外实体解析）、Phase 2（原子写事务）、Phase 3（事务后异步实体链接），是专门针对并发安全设计的。
2. **Observation（观察）和 Mental Model 是两套不同系统**——前者是自动的 bottom-up 聚合（存在 memory_units 表），后者是用户定义的 top-down 查询（存在 mental_models 表）。初级报告没有区分这两个。
3. **Claude Code 集成是完整的生产级代码**，包含 User-Agent 注入、Cloudflare 绕过、多连接模式、compaction hook 钩入。这套模式完全可以移植到 Orchestrator 的 hook 体系。

---

## 架构全貌（深版）

```
┌──────────────────────────────────────────────────────────────────┐
│                    Hindsight API 入口层                           │
│         HTTP (FastAPI)  ·  MCP (JSON-RPC)  ·  Embedded           │
├──────────────────────────────────────────────────────────────────┤
│                  OperationValidatorExtension                      │
│  validate_retain / validate_recall / validate_reflect / ...       │
│  on_retain_complete / on_recall_complete / ...                    │
├──────────────────────────────────────────────────────────────────┤
│                    MemoryEngine (核心引擎)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐  │
│  │  RETAIN     │  │  RECALL     │  │  REFLECT                 │  │
│  │ 三阶段流水线│  │ 四路并行+   │  │ 工具调用 Agent 循环      │  │
│  │             │  │ RRF+CrossEnc│  │ (search_mental_models→   │  │
│  │ Phase1:实体 │  │             │  │  search_observations→    │  │
│  │ 解析(锁外)  │  │ Semantic    │  │  recall)                 │  │
│  │ Phase2:写事务│  │ BM25        │  │                          │  │
│  │ Phase3:实体链│  │ Graph       │  │                          │  │
│  │ (事务后)    │  │ Temporal    │  │                          │  │
│  └─────────────┘  └─────────────┘  └──────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  CONSOLIDATE (后台任务)                                       │ │
│  │  memory_units(world/experience) → Observation(fact_type=obs)│ │
│  │  Mental Model 是独立的用户定义查询（mental_models 表）       │ │
│  └──────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│              PostgreSQL + pgvector + pg_trgm                      │
│  memory_units  ·  memory_links  ·  entities  ·  unit_entities    │
│  mental_models ·  chunks        ·  audit_log ·  webhooks         │
└──────────────────────────────────────────────────────────────────┘
```

---

## 六维扫描

### 维度 1：安全与治理

#### 1.1 OperationValidatorExtension——代码级拦截器

```python
# hindsight_api/extensions/operation_validator.py

class OperationValidatorExtension(Extension, ABC):
    """
    在每个操作前后都有钩子，不只是 accept/reject，
    还可以修改参数（注入 tags、tag_groups、contents）
    """
    
    @abstractmethod
    async def validate_retain(self, ctx: RetainContext) -> ValidationResult: ...
    
    @abstractmethod  
    async def validate_recall(self, ctx: RecallContext) -> ValidationResult: ...
    
    @abstractmethod
    async def validate_reflect(self, ctx: ReflectContext) -> ValidationResult: ...
    
    # post-operation hooks（可选覆盖）
    async def on_retain_complete(self, result: RetainResult) -> None: pass
    async def on_recall_complete(self, result: RecallResult) -> None: pass
    async def on_reflect_complete(self, result: ReflectResultContext) -> None: pass
    async def on_consolidate_complete(self, result: ConsolidateResult) -> None: pass
    
    # 文件转换专属 hook
    async def on_file_convert_complete(self, result: FileConvertResult) -> None: pass
    
    # mental model 级别细控
    async def validate_mental_model_get(...) -> ValidationResult: ...
    async def validate_mental_model_refresh(...) -> ValidationResult: ...
    
    # bank 列表过滤（多租户隔离核心）
    async def filter_bank_list(self, ctx: BankListContext) -> BankListResult: ...
    
    # MCP tool 可见性过滤（每用户级别）
    async def filter_mcp_tools(self, bank_id, request_context, tools) -> frozenset[str]: ...
```

**ValidationResult 的参数注入能力**：

```python
@classmethod
def accept_with(cls, *, contents=None, tags=None, tags_match=None, tag_groups=None):
    """
    返回 accept_with(tag_groups=...) 可以在不修改原始请求的情况下
    向 recall 注入额外的过滤规则——多租户数据隔离的正确姿势
    """
    return cls(allowed=True, contents=contents, tags=tags, ...)
```

**与 Orchestrator 对比**：我们的 hook 体系（guard.sh / audit.sh）是 shell 级别的，只能 accept/reject。Hindsight 的 Validator 是代码级的，能修改参数，有前后两个时机，覆盖 12 种操作类型。这不只是"更强"，而是不同的设计哲学——Hindsight 把安全治理做成了可编程中间件。

#### 1.2 多租户 PostgreSQL Schema 隔离

```python
# hindsight_api/engine/memory_engine.py
_current_schema: contextvars.ContextVar[str | None] = ContextVar(...)

def fq_table(table_name: str) -> str:
    schema = get_current_schema()  # 从 async context 获取
    return f"{schema}.{table_name}"  # "tenant_abc.memory_units"
```

每个租户跑在独立的 PG Schema 下，SQL 注入安全（schema 名来自内部控制流，不来自用户输入），数据完全物理隔离。

#### 1.3 Fire-and-Forget 审计日志

```python
# hindsight_api/engine/audit.py
def log_fire_and_forget(self, entry: AuditEntry) -> None:
    """不阻塞用户请求，后台写入审计"""
    if not self.is_enabled(entry.action):
        return
    try:
        asyncio.create_task(self._safe_log(entry))  # 真正的 fire-and-forget
    except RuntimeError:
        pass  # 优雅降级，从不抛出

async def _safe_log(self, entry: AuditEntry) -> None:
    """写失败只警告，不影响主流程"""
    ...
    except Exception as e:
        logger.warning(f"Audit log write failed: {e}")  # 吞掉异常

# 自动清理（按保留天数）
async def _run_sweep(self) -> None:
    """每小时清理过期记录，row-level delete，并发安全"""
```

---

### 维度 2：记忆与学习（核心，深度分析）

#### 2.1 记忆分类体系（四类，不是三类）

初级报告说"三条认知通路"，实际源码是四种 fact_type：

| fact_type | 来源 | 说明 |
|-----------|------|------|
| `world` | LLM 提取 | 客观/外部事实（"Python 3.12 在 2023-10 发布"） |
| `experience` / `assistant` | LLM 提取 | 第一人称行为/观察（"我修改了 X"） |
| `observation` | Consolidation 自动生成 | 从 world+experience 聚合的持久知识 |
| chunk | 原始文本块 | 文件解析后的原始文本，独立表 |

> **注意**：代码中 `assistant` 和 `experience` 是同一个概念的两种历史命名——数据库迁移 `p1k2l3m4n5o6_new_knowledge_architecture.py` 统一过。

#### 2.2 事实提取的结构化格式（5W 格式）

```python
# hindsight_api/engine/retain/fact_extraction.py
class ExtractedFact(BaseModel):
    what: str   # 核心事实（1-2句，但 Verbose 模式要求 NEVER summarize）
    when: str   # 时间信息（'N/A' 仅当完全没有时间上下文）
    where: str  # 地点（'N/A' 仅当完全无位置上下文）
    who: str    # 涉及人物（解引用代词："my roommate" → "Emily, the user's college roommate"）
    why: str    # 情境/重要性（BE VERBOSE—所有细节）
    
    fact_type: Literal["world", "assistant"]
    fact_kind: str  # "event"（有日期）或 "conversation"（无日期）
    occurred_start: str | None  # ISO timestamp，event 专用
    occurred_end: str | None
    entities: list[Entity] | None
    causal_relations: list[FactCausalRelation] | None
    
    def build_fact_text(self) -> str:
        """合并 what + who + why 成单一检索文本"""
        return " | ".join(parts)  # "what | Involving: who | why"
```

**关键细节**：Verbose 模式 vs 普通模式——`ExtractedFactVerbose` 的字段描述要求 LLM 尽量详细，不能省略。普通模式 `ExtractedFact` 允许简洁。这是提取质量的两个档位。

#### 2.3 Consolidation（聚合）Engine——Observation 生成机制

```python
# hindsight_api/engine/consolidation/consolidator.py

class _ConsolidationBatchResponse(BaseModel):
    creates: list[_CreateAction] = []   # 新建 observation
    updates: list[_UpdateAction] = []   # 更新现有 observation
    deletes: list[_DeleteAction] = []   # 删除过时 observation

async def run_consolidation_job(memory_engine, bank_id, request_context, ...):
    """
    后台定时任务，处理未合并的 memory_units
    
    核心逻辑：
    1. 查找 consolidated_at IS NULL 的 world/experience facts
    2. 按 batch_size 分批（默认配置项 consolidation_batch_size）
    3. 对每批：recall 已有 observations → 送 LLM → 得到 creates/updates/deletes
    4. 每批独立 commit（崩溃恢复用）
    5. 按 observation_scopes 控制：per_tag / combined / all_combinations
    """
    
    # Observation 继承源 memory 的时间字段：
    # event_date    = min(所有来源)
    # occurred_start = min(所有来源)  
    # occurred_end   = max(所有来源)
    # mentioned_at   = max(所有来源)
```

**Consolidation Prompt 的核心规则（9 条，均有工程价值）**：

```
1. ONE OBSERVATION PER DISTINCT FACET（一个观察跟踪一个方面）
2. MATCH BY ENTITY/FACET, NOT TOPIC（按实体匹配，不按主题）
3. STATE CHANGES → UPDATE CONCISELY（状态变化 → 更新，不新建）
4. CASCADE TO ALL AFFECTED OBSERVATIONS（级联更新所有受影响的观察）
5. NO COMPUTATION（不做算术推断，只记录明确陈述的数字）
6. SAME FACET → UPDATE, NOT CREATE（同方面 → 更新，不重复创建）
7. PRESERVE HISTORY（有历史价值的事件记录不删除）
8. RESOLVE REFERENCES（具体值 → 替换模糊占位符）
9. NEVER merge unrelated people（不同人的观察不合并）
```

#### 2.4 Mental Model vs Observation 的区别（初级报告误判）

| | Observation | Mental Model |
|--|-------------|--------------|
| 触发方式 | 后台自动 (consolidation_job) | 用户/代码显式请求 |
| 存储位置 | memory_units 表 (fact_type='observation') | mental_models 表（独立） |
| 方向 | Bottom-up（从原始事实提炼） | Top-down（用户定义查询，按需生成） |
| 更新 | 自动（每次 retain 后触发） | 手动（.refresh() 调用） |
| 用途 | Reflect agent 的中间层上下文 | 用户定义的持久化查询/摘要 |

**Reflect agent 的调用层次**：
```
search_mental_models（最高质量，用户定义）
    → search_observations（自动聚合，含 proof_count）
        → recall（原始事实，Ground Truth）
            → done()（结束，返回回答）
```

#### 2.5 proof_count——记忆可信度信号

```python
# hindsight_api/engine/search/reranking.py
proof_count = sr.retrieval.proof_count  # observation 支持的事实数量

if proof_count is not None and proof_count >= 1:
    # 对数归一化：proof_count=1 → 0.5（中性），proof_count=150 → 1.0（最大 +5%）
    proof_norm = min(1.0, max(0.0, 0.5 + (math.log(proof_count) / 10.0)))
else:
    proof_norm = 0.5  # 非 observation 类型中性

proof_count_boost = 1.0 + 0.1 * (proof_norm - 0.5)  # max ±5% 影响
```

这是"记忆可信度"的量化实现——被更多原始事实支持的 observation 在排序中得到轻微加分。

---

### 维度 3：执行与编排

#### 3.1 三阶段保留流水线（事务拆分的精髓）

```python
# hindsight_api/engine/retain/orchestrator.py

# ─── Phase 1：锁外预解析（单独连接，不持有事务） ───
async def _pre_resolve_phase1(pool, entity_resolver, bank_id, ...):
    """
    在独立连接上执行昂贵的读操作：
    - 实体解析：trigram GIN 扫描 + 共现统计 + 打分
    - 语义 ANN：HNSW 索引探查（找相似已有 units）
    
    关键：在事务外做这些，避免锁持有期间的 TimeoutError
    使用 placeholder unit IDs（str(0), str(1)...）因为真实 ID 还没有
    """
    async with acquire_with_retry(pool) as resolve_conn:
        resolved_entity_ids, ... = await entity_processing.resolve_entities(...)
        semantic_ann_links = await compute_semantic_links_ann(...)
    return Phase1Result(entities=..., semantic_ann_links=...)

# ─── Phase 2：原子写事务 ───
async def _insert_facts_and_links(conn, ...):
    """
    在单个 DB 事务内：
    1. INSERT memory_units（获得真实 UUID）
    2. 将 Phase1 的 placeholder IDs 映射到真实 IDs
    3. INSERT unit_entities（FK，必须在事务内）
    4. 创建 temporal links（时间邻近）
    5. 创建 semantic links（使用 Phase1 预计算的 ANN 结果）
    6. 创建 causal links（LLM 提取的因果关系）
    
    注意：entity links（UI 图可视化用）不在这里插入！
    """
    unit_ids = await fact_storage.insert_facts_batch(conn, bank_id, processed_facts)
    # remap placeholder → actual
    remapped_entity_to_unit, ... = _remap_phase1_results(...)
    ...

# ─── Phase 3：事务后异步补充 ───
async def _build_and_insert_entity_links_phase3(pool, entity_resolver, ...):
    """
    事务提交后，在新连接上：
    - 构建 entity links（仅用于 UI 图可视化，检索不依赖它）
    - 最终 ANN pass（批量 retain 模式专用）
    
    best-effort：失败不影响已提交的事实
    """
```

**为什么这么分**：

| 关注点 | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|
| 连接数 | 1个独立连接 | 1个事务连接 | 1个新连接 |
| 是否持锁 | 不持锁 | 持锁（短） | 不持锁 |
| 失败影响 | 重做 Phase1 | 全部回滚 | 部分失败可接受 |
| 放的东西 | 慢读操作 | 必须原子的写 | 可以异步的写 |

#### 3.2 Worker 异步流水线

```python
# hindsight_api/worker/stage.py

# 每个 worker task 绑定一个 StageHolder 到 ContextVar
_current_holder: ContextVar[StageHolder | None] = ContextVar(...)

def set_stage(name: str) -> None:
    """
    引擎代码在每个阶段边界调用：
    set_stage("retain.phase1.resolve")
    set_stage("retain.phase2.insert_facts")
    set_stage("retain.phase3.entity_links")
    
    在 HTTP 上下文调用是 no-op（ContextVar 未绑定）
    Worker poller 周期性读取，输出到 WORKER_STATS 日志
    """
    holder = _current_holder.get()
    if holder is None:  # no-op 在非 worker 上下文
        return
    holder.stage = name
    holder.updated_at = time.monotonic()
```

这是诊断 stuck task 的利器——每个任务暴露自己当前在哪个阶段，不需要线程 dump。

#### 3.3 连接预算管理（防止连接池耗尽）

```python
# hindsight_api/engine/db_budget.py

class ConnectionBudgetManager:
    """
    每个操作（recall/retain/...）分配一个 semaphore，
    限制该操作最多并发使用多少个连接
    """
    
    @asynccontextmanager
    async def operation(self, max_connections=None) -> BudgetedOperation:
        op_id = f"op-{uuid.uuid4().hex[:12]}"
        self._operations[op_id] = OperationBudget(op_id, budget)
        yield BudgetedOperation(self, op_id)  # 释放时自动清理

class BudgetedPool:
    """
    把普通 pool 包装成 BudgetedPool，透明传给下层函数
    下层调 pool.acquire() 会自动受 semaphore 约束
    """
    def __getattr__(self, name):
        return getattr(self._pool, name)  # 代理所有其他属性
```

---

### 维度 4：上下文与预算

#### 4.1 四路并行检索（实际代码）

```python
# hindsight_api/engine/search/retrieval.py

async def retrieve_all_fact_types_parallel(pool, query_text, query_embedding_str, ...):
    """
    实际实现：不是四个独立连接，而是 2 个连接
    （优化：减少连接开销）
    
    连接1：semantic + BM25 + temporal（合并成一个 CTE 查询）
    连接2*N：graph（每个 fact_type 一个 asyncio task，并行）
    
    Step 1: 提取时间约束（CPU，无 DB）
    Step 2: 单连接执行 semantic_bm25 + temporal（若有时间约束）
    Step 3: asyncio.gather() 并行执行所有 fact_type 的 graph 检索
    """
    
    # Semantic + BM25 合并成 UNION ALL 的单个查询
    # 每个 fact_type 一个 semantic arm + 一个 bm25 arm
    # HNSW 过取 5x（min 100），Python 侧截断到 limit
    
    graph_tasks = [run_graph_for_fact_type(ft) for ft in fact_types]
    graph_results_list = await asyncio.gather(*graph_tasks)
```

**BM25 三种后端**：

```python
if config.text_search_extension == "vchord":
    # vChord 扩展：BM25 语义评分
    bm25_score_expr = "search_vector <&> to_bm25query(..., 'llmlingua2')"
elif config.text_search_extension == "pg_textsearch":
    # pg_textsearch 扩展
    bm25_score_expr = "-(text <@> to_bm25query(...))"
else:  # native PostgreSQL tsearch
    bm25_score_expr = "ts_rank_cd(search_vector, to_tsquery('english', $4))"
```

#### 4.2 两阶段时间检索（防止全表嵌入距离计算）

```sql
-- hindsight_api/engine/search/retrieval.py
WITH date_ranked AS MATERIALIZED (
    -- Phase 1: 只用日期过滤，利用日期索引，不算嵌入距离
    -- 每个 fact_type 最多 50 个候选（ROW_NUMBER partition）
    SELECT id, fact_type, ROW_NUMBER() OVER (
        PARTITION BY fact_type ORDER BY occurred_start DESC
    ) AS rn
    FROM memory_units WHERE bank_id = $2 AND fact_type = ANY($3)
    AND (occurred_start <= $5 AND occurred_end >= $4) OR ...
),
sim_ranked AS (
    -- Phase 2: 只对 ≤50×len(fact_types) 行计算嵌入距离
    SELECT mu.*, 1 - (mu.embedding <=> $1::vector) AS similarity,
           ROW_NUMBER() OVER (PARTITION BY mu.fact_type ORDER BY embedding <=> $1) AS sim_rn
    FROM date_ranked dr JOIN memory_units mu ON mu.id = dr.id
    WHERE dr.rn <= 50 AND similarity >= $6
)
SELECT * FROM sim_ranked WHERE sim_rn <= 10
```

**价值**：时间范围查询如果先算嵌入距离，可能扫描数千行。两阶段把嵌入计算限制在 `50 × N` 行（N = fact_type 数量）。

#### 4.3 重排序公式（三信号乘法组合）

```python
# hindsight_api/engine/search/reranking.py
# RRF → 先融合，再用 Cross-Encoder 重排
combined_score = CE_normalized * recency_boost * temporal_boost * proof_count_boost

# 各信号设计：
# recency_boost    = 1 + 0.2 * (recency - 0.5)     # max ±10%，365天线性衰减
# temporal_boost   = 1 + 0.2 * (temporal - 0.5)    # max ±10%，时间查询专用
# proof_count_boost= 1 + 0.1 * (proof_norm - 0.5)  # max ±5%，log 归一化

# Passthrough 退化检测（无 Cross-Encoder 时不变成纯 recency 排序）
if is_passthrough_reranker and scored_results:
    # 从 RRF rank 推导伪 CE 分数，保持排序有意义
    sr.cross_encoder_score_normalized = 1.0 - (0.9 * new_rank / denom)
```

---

### 维度 5：故障与恢复

#### 5.1 Consolidation 故障恢复（每批独立 commit）

```python
# hindsight_api/engine/consolidation/consolidator.py
# 每个 memory 独立处理 + 独立 commit，而不是一个大事务
for memory in unconsolidated_memories:
    try:
        result = await _process_one_memory(...)
        await conn.execute(
            "UPDATE memory_units SET consolidated_at = $1 WHERE id = $2",
            utcnow(), memory["id"]
        )  # ← 单独 commit，崩溃后重启只重处理未标记的
    except Exception as e:
        # 失败的记录标记 consolidation_failed_at，不阻塞其他记录
        await conn.execute(
            "UPDATE memory_units SET consolidation_failed_at = $1 WHERE id = $2",
            utcnow(), memory["id"]
        )
```

`consolidated_at IS NULL AND consolidation_failed_at IS NULL` 是恢复的幂等查询。

#### 5.2 数据库连接重试（非线性退避）

```python
# hindsight_api/engine/db_utils.py（推断自使用模式）
async def acquire_with_retry(pool, max_retries=3):
    """带重试的连接获取，避免池满时立即失败"""
```

#### 5.3 实体解析并发安全（锁序统一）

```python
# hindsight_api/engine/retain/link_utils.py
async def _bulk_insert_links(conn, links, bank_id, chunk_size=5000):
    """
    按 (from_unit_id, to_unit_id) 排序后批量 INSERT
    
    原因：统一锁顺序 → 消除循环等待 → 无死锁
    单个 INSERT ... SELECT FROM unnest() → 1 次往返 vs N 次
    chunk_size=5000：防止超大 unnest 导致查询超时（1亿行的表上验证过）
    """
    links_sorted = sorted(links, key=lambda l: (str(l[0]), str(l[1])))
    for i in range(0, len(links_sorted), chunk_size):
        chunk = links_sorted[i:i + chunk_size]
        # INSERT FROM unnest(arrays...)
```

---

### 维度 6：质量与评审

#### 6.1 图检索的三信号合并（LinkExpansionRetriever）

```python
# hindsight_api/engine/search/link_expansion_retrieval.py
"""
三条并行扩展路径（单 CTE 查询，一个连接槽）：

1. Entity links：self-join through unit_entities
   - 共享 entity 越多，score 越高
   - per_entity_limit（默认 200）防止高扇出实体爆炸
   
2. Semantic links：预计算 kNN 图（存储时建立）
   - 每个 fact 最多连 top-5 相似（similarity >= 0.7）
   - 双向查询（图不对称）
   
3. Causal links：LLM 提取的因果链
   - 最高质量信号：score = weight + 1.0（额外加分）
   - causes / caused_by / enables / prevents
"""
```

#### 6.2 semantic link 的存储时限边（Retain-Time Link Bounding）

```python
# hindsight_api/engine/retain/link_utils.py

MAX_TEMPORAL_LINKS_PER_UNIT = 20  # 每个 unit 最多 20 条时间链接

def _cap_links_per_unit(links, max_per_unit=20):
    """
    按 from_unit_id 分组，每组保留 weight 最高的 N 条
    
    这是主动治理，不是被动防御——图从诞生起就有界
    查询时不需要 LIMIT fan-out，因为图本身就是有界的
    """
```

#### 6.3 HNSW 分 fact_type 的局部索引

```sql
-- 三个局部 HNSW 索引（而不是一个全表索引）：
CREATE INDEX idx_mu_emb_world ON memory_units USING hnsw (embedding vector_cosine_ops)
    WHERE fact_type = 'world';
CREATE INDEX idx_mu_emb_observation ON memory_units USING hnsw (embedding vector_cosine_ops)
    WHERE fact_type = 'observation';  
CREATE INDEX idx_mu_emb_experience ON memory_units USING hnsw (embedding vector_cosine_ops)
    WHERE fact_type = 'experience';
```

**工程价值**：每个局部索引体积 = 全表索引 / N。HNSW 的近似召回率与索引密度正相关——分类型索引比全表混合索引精度更高，体积更小。配合 `ef_search=200` 全局设置，在稀疏图上改善召回。

---

## 五深度层分析：保留流水线（核心模块）

### 调度层（Dispatch）
`worker/poller.py` → 异步任务队列 → `retain_batch_async()` → `worker/stage.py` 阶段标记

### 实践层（Execution）
```
retain_batch_async()
├── LLM: fact_extraction.extract_facts()  # 5W 结构化提取
├── Embedding: embedding_processing.generate_embeddings()  # 批量向量化
├── Phase1: _pre_resolve_phase1()  # 锁外实体解析 + ANN
├── Phase2: async with conn.transaction(): _insert_facts_and_links()
│   ├── fact_storage.insert_facts_batch()
│   ├── entity_resolver.link_units_to_entities_batch()  # 必须在事务内
│   ├── link_creation.create_temporal_links_batch()
│   ├── link_creation.create_semantic_links_batch()
│   └── link_creation.create_causal_links_batch()
└── Phase3: _build_and_insert_entity_links_phase3()  # 事务后，best-effort
```

### 消费层（Consumer）
`retrieval.retrieve_all_fact_types_parallel()` 消费 memory_units + memory_links

### 状态层（State）
```sql
memory_units.consolidated_at IS NULL   -- 待合并
memory_units.consolidation_failed_at  -- 合并失败（不重试）
memory_links.link_type IN             -- 四种链接类型
    ('temporal', 'semantic', 'entity', 'causes', 'caused_by', 'enables', 'prevents')
```

### 边界层（Boundary）
- `MAX_TEMPORAL_LINKS_PER_UNIT = 20`（链接上界）
- `HNSW ef_search = 200`（近似召回质量上界）
- `semantic_link threshold >= 0.7`（语义相似下界）
- `entity per_entity_limit = 200`（实体扇出上界）

---

## Pattern 提取

### P0（直接可用）

#### P0-1：三阶段事务拆分模式

**核心代码**：

```python
# Phase 1（锁外）：entity resolution + ANN search
# 在独立连接上，不持有事务锁
async with acquire_with_retry(pool) as resolve_conn:
    entities = await resolve_entities(resolve_conn, ...)
    ann_links = await compute_semantic_links_ann(resolve_conn, ...)

# Phase 2（事务内）：原子写入
async with conn.transaction():
    unit_ids = await insert_facts_batch(conn, ...)
    # remap placeholder IDs → actual IDs
    await link_units_to_entities_batch(unit_entity_pairs, conn=conn)
    await create_temporal_links_batch(conn, ...)
    await create_semantic_links_batch(conn, ..., pre_computed_ann_links=ann_links)

# Phase 3（事务后）：best-effort 补充
async with acquire_with_retry(pool) as conn:
    await build_entity_links(...)  # 失败不影响已提交数据
```

**为什么 P0**：我们的 events.db 写入有并发安全问题（多个 collector 同时写）。这个三阶段分离可以直接用在 collector 写入层，特别是 Phase1（锁外）+ Phase2（原子）的分法。

**比较矩阵**：
| 指标 | 三阶段 | 传统单事务 |
|------|--------|-----------|
| 死锁概率 | 低（锁时窗短） | 高（长事务持锁） |
| 并发吞吐 | 高 | 低 |
| 实现复杂度 | 中（ID 映射需仔细） | 低 |
| 部分失败 | Phase3 可重试 | 全部回滚 |

**不可替代性**：这个模式是专门针对"先读后写"操作（entity resolution 需要读，fact insertion 需要写）的并发安全设计。用传统加锁方式解决同一问题代价高 3-5x。

**Orchestrator 适配点**：collector 的 `flush_batch()` → 先在锁外做关联查询，再事务写入。

---

#### P0-2：OperationValidatorExtension——可编程中间件模式

**核心代码**：

```python
@dataclass
class ValidationResult:
    allowed: bool
    contents: list[dict] | None = None  # 可注入修改后的内容
    tags: list[str] | None = None       # 可注入额外过滤
    tag_groups: list[TagGroup] | None = None

@classmethod
def accept_with(cls, *, tag_groups=None, tags=None, ...):
    """accept，同时注入参数修改——这是关键"""
    return cls(allowed=True, tag_groups=tag_groups, ...)
```

**为什么 P0**：我们的 governor 当前是 shell hook（只能 block/pass）。这个模式让 governor 能修改派单参数——例如自动给高风险操作注入 `requires_approval=True` tag，而不只是阻止它。

**三重验证**：
1. 代码确认：`operation_validator.py` 完整实现，有 12 种操作钩子
2. 测试确认：`tests/test_extensions.py` 有覆盖
3. 生产确认：`hindsight-integrations/claude-code/` 实际使用

**不可替代性**：这个双向钩子（pre + post）+ 参数注入的组合，在 shell hook 中无法实现（shell 只能写 stdout，不能修改 stdin 流）。

---

#### P0-3：两阶段时间检索（防止全表嵌入距离计算）

**核心 SQL**（见维度 4.2）

**为什么 P0**：我们的 events.db 查询"上周的事件"时，如果先算嵌入距离再过滤时间，会扫描全表。这个两阶段方案先用日期索引缩小候选，再算嵌入距离。可以直接适配到 events.db 的 SQL 查询层。

**适配成本**：低。修改 recall 的 SQL，不改接口。

---

#### P0-4：Claude Code 集成模式（含 User-Agent Cloudflare 绕过）

```python
# hindsight-integrations/claude-code/scripts/lib/client.py

USER_AGENT = f"hindsight-claude-code/{_plugin_version()}"

def _headers(self) -> dict:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,  # 绕过 Cloudflare error 1010
    }
```

**为什么 P0**：完整的 Claude Code hook 集成代码，包括：
- `UserPromptSubmit` → recall → `additionalContext` 注入（stdout JSON）
- `Stop` → retain（异步，不阻塞响应）
- `PostCompact` → recall re-inject（compaction 后记忆不丢）
- 多转对话查询组合（取最近 N 轮构建检索 query）
- 零 pip 依赖（纯 stdlib）

这不是参考，是可以直接复用的生产代码结构。Orchestrator 的记忆集成可以完全按这个结构实现。

**具体集成点**：

```python
# recall.py 的核心流程
def main():
    hook_input = json.load(sys.stdin)
    
    # 1. 多轮查询组合
    query = compose_recall_query(prompt, messages[-N:], recall_context_turns)
    query = truncate_recall_query(query, prompt, max_chars=800)
    
    # 2. 调用 recall
    response = client.recall(bank_id=bank_id, query=query, budget="mid")
    
    # 3. 格式化注入
    output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                     "additionalContext": f"<hindsight_memories>...</hindsight_memories>"}}
    json.dump(output, sys.stdout)
    # 关键：不能写 stderr 之外的东西，只能 stdout JSON
```

---

### P1（需要适配）

#### P1-1：Consolidation Prompt 的 9 条规则

**为什么 P1**：规则本身可以直接用，但需要适配到 Orchestrator 的事件/记忆格式。关键规则：
- 不做算术推断（规则 5）—— Orchestrator 的记忆更新经常犯这个错
- 一个观察一个方面（规则 1）—— 防止 memory 合并过度
- 状态变化 → 更新，不新建（规则 3）

**适配成本**：写新的 consolidation prompt，套用这 9 条规则。

#### P1-2：observation_scopes 多粒度合并

```python
# types.py
observation_scopes: Literal["per_tag", "combined", "all_combinations"] | list[list[str]]
```

- `combined`：所有 tag 的事实一起合并（默认）
- `per_tag`：每个 tag 单独跑一遍合并（适合多项目数据隔离）
- `all_combinations`：所有 tag 子集组合（穷举）
- `list[list[str]]`：精确指定哪些 tag 集合各自合并

**适配成本**：中等。需要在 retain 时允许指定 scope，在 consolidation 时按 scope 分组。

#### P1-3：OpenCode 的 `experimental.session.compacting` hook

```typescript
// hindsight-integrations/opencode/src/hooks.ts
'experimental.session.compacting': async (input, output) => {
    // 1. 先 retain（保存压缩前的对话）
    await retainSession(input.sessionID, messages);
    state.lastRetainedTurn.delete(input.sessionID);  // 重置计数器
    
    // 2. 再 recall（把记忆注入压缩上下文）
    output.context.push(recalledContext);
}
```

**为什么 P1**：Orchestrator 已经有 context compaction 的四层防御（R57）。但我们没有"压缩前先存档"的逻辑。这个钩子补充了压缩事件的记忆保存环节。

**适配成本**：中等。需要实现 `context_threshold_stop.py` 的扩展版本。

---

### P2（长期参考）

#### P2-1：Bank Mission 双配置（reflect_mission + retain_mission）

```python
# client.py
def set_bank_mission(self, bank_id, mission, retain_mission=None):
    updates = {"reflect_mission": mission}  # Reflect 时的人格
    if retain_mission:
        updates["retain_mission"] = retain_mission  # Retain 时的过滤/提取偏好
```

分离 reflect 和 retain 的指令——Reflect 用于回答时的风格，Retain 用于"重点存什么"的偏好。Orchestrator 的 SOUL/memory/ 可以借鉴这个双配置结构。

#### P2-2：Webhook 系统（事件驱动记忆通知）

```sql
-- alembic: e4f5a6b7c8d9_add_webhooks_tables.py
webhooks 表 + webhook_http_config
```

memory 变化时推送 webhook——适合多智能体协作场景（Agent A 存的记忆触发 Agent B 的行动）。

#### P2-3：文件 Parser 抽象（markitdown + iris）

```python
# hindsight_api/engine/parsers/base.py + iris.py + markitdown.py
```

将文件转为 markdown 后保留——适合 Orchestrator 将文档/代码文件纳入记忆体系。

---

## 路径依赖分析

```
PostgreSQL + pgvector  ← 核心依赖
    ↓
HNSW 局部索引（per fact_type）
    ↓
pg_trgm（实体 trigram 搜索）
    ↓
asyncpg（原生 PG 协议，不支持其他 DB）
```

**Orchestrator 的路径**：events.db 是 SQLite。引入 Hindsight 的核心检索能力需要：
1. 要么迁移到 PostgreSQL（工程量大）
2. 要么只借模式，用 SQLite + sqlite-vec + FTS5 实现简化版

**建议路径**：先偷模式，用 SQLite 实现简化版（semantic + BM25 + temporal 三路，RRF 融合），图谱层暂缓。

---

## 与初级报告的差异

| 点 | 初级报告（R28）| 本次深度分析 |
|----|---------------|-------------|
| 记忆类型 | 三条通路（World/Experience/Mental Model） | 四种 fact_type（含 observation），Mental Model 是独立系统 |
| 合并机制 | 笼统说"mental model 合成" | Consolidation 是独立 Engine，9条 prompt 规则，per-memory commit |
| 检索 | 四路并行 + RRF | 实际是 2 个连接（semantic+BM25 合并 CTE），graph 并行，有两阶段时间优化 |
| Phase 分离 | 未提及 | 三阶段事务拆分是核心并发安全机制 |
| Claude Code 集成 | 未提及 | 完整生产级代码，含 User-Agent、compaction hook、零依赖实现 |
| proof_count | 未提及 | 记忆可信度信号，log 归一化，影响重排序 ±5% |

---

## 实施优先级

### 第一波（4 周内可实现）

1. **两阶段时间检索**（P0-3）→ events.db 查询加时间范围优化
2. **Claude Code hook 格式**（P0-4）→ Orchestrator 记忆注入标准化
3. **User-Agent 注入**（P0-4 子集）→ 所有外部 HTTP 调用统一加 UA，绕过 bot filter
4. **5W 事实提取格式**（P2）→ 标准化 memory 写入格式，提升检索质量

### 第二波（需要基建支持）

5. **Consolidation + Observation**（P0，需要设计 consolidation_job）
6. **OperationValidator 模式**（P0-2）→ governor pipeline 加可编程 validator
7. **三阶段事务拆分**（P0-1）→ collector flush_batch 并发重构
8. **连接预算管理**（P0）→ governor 资源管理加 semaphore 层

### 第三波（长期演进）

9. **图谱层 + HNSW 局部索引**（若迁移 PG）
10. **Webhook 系统**（多智能体事件驱动）
11. **observation_scopes 多粒度合并**（P1-2）

---

## 关键学习

> **三个系统，一个引擎**
>
> Hindsight 真正的价值不在于任何单个功能，而在于三个系统的协同：
>
> 1. **保留（Retain）**：不是存文本，是建图——每次 retain 都在创建实体节点、时间边、语义边、因果边
> 2. **聚合（Consolidate）**：不是压缩，是提炼——把事实聚合成 observation，每个 observation 跟踪一个方面
> 3. **检索（Recall）**：不是查询，是激活——四路并行激活不同维度的关联记忆，RRF 融合，Cross-Encoder 重排
>
> Orchestrator 的 events.db 是一维的——有数据，没有图谱，没有聚合，没有多路激活。加了图谱层，同样的数据能产出完全不同级别的召回；加了 consolidation，同样的检索能返回更高质量的知识而不只是原始事实。
>
> 路径是清晰的：模式可偷，基建可省。先用 SQLite + FTS5 实现三路检索，再逐步加聚合层。
