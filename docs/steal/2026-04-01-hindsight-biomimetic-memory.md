# Steal Report: vectorize-io/hindsight — 仿生记忆系统

> **Source**: https://github.com/vectorize-io/hindsight
> **Date**: 2026-04-01
> **Round**: 23 P1 (补充)
> **Category**: Memory Architecture / Retrieval / Graph

---

## TL;DR

Hindsight 是一个 **LongMemEval SOTA** 的 agent 记忆系统。不是又一个 RAG——它把记忆分成三条认知通路（世界事实/经验事实/心智模型），用图谱连接（因果/时序/语义/实体），检索时四路并行 + RRF 融合 + Cross-Encoder 重排。

跟 Orchestrator 的对标点：events.db 是我们的记忆体，SOUL 是我们的心智模型，但我们缺图谱层和多路检索。

---

## 架构概览

```
┌─────────────────────────────────────────────┐
│                 Hindsight API                │
├─────────┬──────────┬───────────┬────────────┤
│ RETAIN  │  RECALL  │  REFLECT  │ CONSOLIDATE│
│ (存储)  │  (检索)  │  (推理)   │ (合成)     │
├─────────┴──────────┴───────────┴────────────┤
│              Memory Engine                   │
├─────────┬──────────┬───────────┬────────────┤
│ Facts   │ Entities │  Links    │ Mental     │
│ (事实)  │ (实体)   │  (图谱)   │ Models     │
├─────────┴──────────┴───────────┴────────────┤
│     PostgreSQL + pgvector + pg_trgm          │
└─────────────────────────────────────────────┘
```

### 三条记忆通路

| 通路 | 类型 | 对标 Orchestrator |
|------|------|-------------------|
| World Facts | 通用知识（"Python 3.12 发布日期"） | — |
| Experience Facts | 交互记录（"用户说过偏好 X"） | events.db |
| Mental Models | 合成理解（"用户的工作习惯模型"） | SOUL/memory/ |

---

## 可偷模式清单

### P0 — 直接可用

#### 1. 四路并行检索 + RRF 融合

```
Query
  ├─ [1] Semantic: pgvector HNSW 向量搜索
  ├─ [2] BM25: PostgreSQL tsearch 关键词搜索
  ├─ [3] Graph: 图谱遍历（链接扩展 or MPFP）
  └─ [4] Temporal: 时间邻近搜索

  → asyncio.gather() 并行执行
  → Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank(d)), k=60
  → Cross-Encoder 重排
  → Token budget 截断
```

**为什么要偷**: 我们的 recall 现在是单路向量搜索。四路并行 + RRF 是检索质量的结构性提升——向量搜索擅长语义，BM25 擅长精确匹配，图遍历能找到间接关联，时间搜索处理"上周说的那个"类查询。四路互补，RRF 融合成本极低（只是排名算术）。

**适用场景**: Orchestrator 记忆检索、SOUL 上下文召回、Construct 3 RAG

---

#### 2. Retain-Time Link Bounding（存储时限边）

```python
# 传统做法：查询时 LIMIT fan-out
# Hindsight 做法：存储时就绑定链接上限

# 语义链接：每个 fact 只连 top-5 相似（sim >= 0.7）
# 实体共现：每个 entity 只保留 top-K 共现
# 因果链接：LLM 提取时显式标注
```

**为什么要偷**: 查询时限边是被动防御——图越大，查询越慢。存储时限边是主动治理——图始终保持有界。这让图算法在 O(bounded) 而不是 O(N) 上运行。

**适用场景**: 任何需要图遍历的模块。我们的 memory link 如果未来加图谱，必须从一开始就限边。

---

#### 3. Per-Task Entity Accumulation（批量实体统计无锁刷新）

```python
# 问题：N 个 fact 引用同一 entity → N 次 UPDATE → 行锁竞争 + 死锁
# 方案：
_pending_stats: dict[task_id, list[EntityStat]]  # 按任务隔离
_pending_cooccurrences: dict[task_id, list[CooccurrencePair]]

# 事务提交后：
# 1. 按 entity_id 聚合（sum counts）
# 2. 按 entity_id 排序（统一锁序 → 无死锁）
# 3. 单次 UPSERT
```

**为什么要偷**: 这是一个通用的并发安全模式。我们的 events.db 写入、collector 统计更新都有类似的 N-writes-to-same-row 问题。"按任务累积 → 排序 → 单次刷新" 是个可复用的范式。

**适用场景**: events.db 写入层、collector 统计聚合

---

#### 4. Token Budget 语义分层

```python
# 三种不同的 token budget：

# 1. Recall budget: 返回结果的总 token 上限（累积到阈值就停）
# 2. Extraction budget: LLM 输出的 max_completion_tokens
# 3. Graph traversal budget: 数据库查询次数上限（防止图遍历失控）

# 关键区分：用途不同，budget 独立
```

**为什么要偷**: 我们的 Agent SDK 调用现在 token 管理是粗粒度的。分层 budget 能让我们在不同阶段精确控制成本——召回阶段给够 context，生成阶段控制输出，图遍历阶段限制 DB 负载。

**适用场景**: Agent SDK 执行层、governor 资源管理

---

### P1 — 需要适配

#### 5. MPFP 次线性图遍历

```
Meta-Path Forward Push:
  1. 从 seed 节点出发
  2. 每一跳：只加载 frontier 节点的边（懒加载，不是全图）
  3. 前向推送权重传播
  4. 阈值剪枝：低于激活阈值的节点丢弃
  5. 重复直到 budget 耗尽

四种 meta-path 模式并行：语义/实体/时序/因果
```

**为什么要偷**: 传统图遍历要么全图加载（内存爆），要么递归查询（慢）。MPFP 是中间路线——懒加载 + 预算感知，能在百万节点图上做次线性检索。如果 events.db 规模上去了，这就是必需品。

**适配成本**: 需要先有图谱层（Link 表 + Entity 表）。中等工程量。

---

#### 6. 心智模型合成（Mental Model Consolidation）

```
Mental Model:
  - name, content (合成摘要)
  - trigger_data (标签过滤规则)
  - status: active / stale / archived
  - 版本历史追踪

合成流程:
  1. 按 tag 过滤相关 facts
  2. 加载当前心智模型 + 指令
  3. LLM 生成更新后的摘要
  4. 存储新版本，保留历史
```

**为什么要偷**: 我们的 SOUL/memory/ 是手工维护的。Hindsight 的 mental model 是自动合成 + 定期刷新 + 版本追踪。这跟我们的"三省六部"精神完全契合——不是记住所有事实，而是从事实中提炼理解。

**适配成本**: 需要定义 trigger 规则和合成 prompt。可以先从 SOUL/memory/ 的自动更新开始。

---

#### 7. Disposition System（人格特质影响推理）

```python
disposition: {
  "skepticism": 1-5,    # 怀疑程度
  "literalism": 1-5,    # 字面理解 vs 隐喻理解
  "empathy": 1-5        # 情感考量
}
# 影响 reflect 操作的 prompt 生成和回复风格
```

**为什么要偷**: 我们的 persona 现在是 prompt-level 的——写死在 boot.md 里。Hindsight 把人格参数化了，可以动态调整。"损友模式" skepticism=4, literalism=2, empathy=3？这让人设从文本变成可调的旋钮。

**适配成本**: 低。在 persona prompt 生成时注入参数化特质。

---

#### 8. Extension Triple（三重扩展点）

```python
TenantExtension        # 认证 + 多租户隔离
OperationValidatorExtension  # 操作拦截 + 参数注入
HttpExtension          # HTTP 请求拦截

# OperationValidator 最有趣：
async def validate_retain(ctx) -> ValidationResult:
  # 可以：拒绝操作、修改参数、注入标签、限速
```

**为什么要偷**: 我们的 hook 体系（guard.sh + audit.sh）是 shell 级别的。Hindsight 的 OperationValidator 是代码级别的——可以在操作执行前修改参数，不只是 accept/reject。这对 governor 的派单审批很有参考价值。

**适配成本**: 中等。需要在 governor pipeline 里加 validator 接口。

---

### P2 — 长期参考

#### 9. Schema Context Variable（多租户 SQL 隔离）

```python
_current_schema: contextvars.ContextVar[str | None]

def fq_table(table_name: str) -> str:
  schema = get_current_schema()  # 从 async context 获取
  return f"{schema}.{table_name}"
```

**参考价值**: 如果 Orchestrator 未来支持多实例/多用户，这是干净的隔离方案——不用改表结构，用 PG schema 隔离。

---

#### 10. Fire-and-Forget Audit（非阻塞审计日志）

```python
async def log_fire_and_forget(entry: AuditEntry):
  # 后台写入，不阻塞用户请求
  # 可配置保留天数自动清理
  # 按 action 类型过滤
```

**参考价值**: 我们的 audit.sh 是同步的。如果审计量上去了，fire-and-forget 模式能避免审计拖慢主流程。

---

#### 11. 动态标签过滤（Tag Groups Boolean Logic）

```python
# 简单模式：OR
tags = ["public", "archived"], tags_match = "any"

# 高级模式：布尔组合
tag_groups = [
  TagGroup(required=["internal"], prohibited=["confidential"]),
  TagGroup(required=["q4_planning"])
]
# 匹配：(有 internal 且无 confidential) OR (有 q4_planning)
```

**参考价值**: 我们的事件过滤现在是简单的类型匹配。如果需要复杂的可见性控制（比如"只看 collector 事件但排除敏感数据"），tag groups 是现成方案。

---

#### 12. LLM Per-Operation Config（每操作独立 LLM 配置）

```
RETAIN_LLM_*  → 事实提取（需要结构化输出，用强模型）
REFLECT_LLM_* → 推理（可以用轻量模型）
CONSOLIDATION_LLM_* → 合成（用高效模型）

回退链：操作专用 → 全局配置 → 默认值
```

**参考价值**: 我们的 Agent SDK 调用现在是统一模型。不同任务用不同模型能显著降本——collector 用 Haiku，analyst 用 Sonnet，重要决策用 Opus。

---

## 结构性对比

| 维度 | Hindsight | Orchestrator | 差距 |
|------|-----------|-------------|------|
| 记忆存储 | 三通道 + pgvector | events.db (SQLite) | 🔴 缺图谱层 |
| 检索 | 四路并行 + RRF + CrossEncoder | 单路 | 🔴 结构性短板 |
| 图谱 | 预计算链接 + MPFP | 无 | 🔴 缺失 |
| 合成 | Mental Model + 版本化 | SOUL/memory/ 手工 | 🟡 有基础待自动化 |
| 人格 | 参数化 disposition | prompt-level persona | 🟡 可快速适配 |
| 多模型 | per-operation LLM config | 统一模型 | 🟡 Agent SDK 可加 |
| 扩展性 | 三重 Extension | Hook shell 体系 | 🟡 层级不同 |
| 审计 | Fire-and-forget async | 同步 audit.sh | 🟢 够用 |

---

## 实施建议

### 第一波（低成本高回报）

1. **RRF 融合检索** → 在 Construct 3 RAG 里先试：向量 + BM25 双路 + RRF 合并
2. **Token Budget 分层** → governor 资源管理加入三层 budget
3. **Per-Task Accumulation** → events.db 写入层采用批量刷新
4. **Disposition 参数化** → persona 从纯文本改为 trait 旋钮

### 第二波（需要基建）

5. **图谱层** → events.db 加 Link 表 + Entity 表
6. **Mental Model 自动合成** → SOUL/memory/ 定期从 events 合成
7. **OperationValidator** → governor pipeline 加验证器接口
8. **Per-Operation LLM Config** → Agent SDK 按任务类型选模型

### 第三波（长期演进）

9. **MPFP 图遍历** → 等图谱规模上去再引入
10. **多租户 Schema 隔离** → 等多实例需求出现

---

## 关键学习

> **记忆系统的质量不在于存了多少，而在于连接了什么。**
>
> Hindsight 的核心洞察：事实本身是一维的，但事实之间的关系是多维的（因果/时序/语义/实体）。检索质量的瓶颈不是向量数据库的精度，而是能不能找到"间接相关但高度有用"的记忆。
>
> 这正是我们的 events.db 缺的——有数据，但数据之间没有图谱连接。加了图谱层，同样的数据能产出完全不同级别的召回。
