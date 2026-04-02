# Vector Memory Layer — Qdrant + Ollama Embedding

**Date:** 2026-04-03
**Status:** Approved
**Phase:** Orchestrator 演进路线 Phase 3.7

## Summary

将 Orchestrator 的向量检索从 SQLite bag-of-chars fallback 全迁移到 Qdrant，使用本地 Ollama 的 Qwen3-Embedding 模型。5 个 collection 覆盖 learnings / experiences / structured memory / run logs / file index，实现语义检索替代硬编码规则匹配。

## Motivation

当前状态：
- `vector_db.py` 使用 256 维字符频率向量（`_simple_embed`），**无语义能力**
- `dedup.py` 用 `SequenceMatcher` 做文本去重，精度有限
- `structured_memory.py` 6 维记忆系统，**纯文本存取**
- `memory_tier.py` hot/extended 分层，**按规则分类，不语义**
- Qdrant 容器已运行 13+ 小时，只服务 C3 RAG 的 10 个 collection，Orchestrator 零引用

目标：
- 所有管道已挖好（6 维记忆、hotness 分层、dedup 管道、CAFI 文件索引），**接上向量水**
- 为 Phase 4（Agent 发现层）和自主执行闭环提供语义记忆基础

## Architecture

### Embedding Stack

```
Qwen3-Embedding (Ollama, localhost:11434)
    ↓ /api/embed
QdrantStore (src/storage/qdrant_store.py)
    ↓ qdrant-client
Qdrant (localhost:6333, Docker volume 持久化)
```

- **模型**: `qwen3-embedding`（Ollama 本地，4.7 GB，4096 维）
- **容器内访问**: `host.docker.internal:11434`（Ollama）+ `host.docker.internal:6333`（Qdrant）
- **依赖**: `qdrant-client>=1.9.0` + `httpx`（async Ollama 调用）

### Core Module: `src/storage/qdrant_store.py`

```python
class QdrantStore:
    """Orchestrator 向量记忆层 — Qdrant + Ollama Embedding."""

    def __init__(self, qdrant_url, ollama_url, model="qwen3-embedding"):
        self.client = QdrantClient(url=qdrant_url)
        self.ollama_url = ollama_url
        self.model = model

    # Embedding
    async def embed(self, texts: list[str]) -> list[list[float]]

    # Collection management
    def ensure_collection(self, name: str, dim: int = 4096)

    # Write
    async def upsert(self, collection: str, doc_id: str, text: str, metadata: dict)
    async def upsert_batch(self, collection: str, items: list[dict])

    # Search
    async def search(self, collection: str, query: str, top_k: int = 5,
                     filters: dict = None) -> list[dict]

    # Health
    def is_available(self) -> bool
```

Key properties:
- **Async-first**: 和 Governor async 风格一致
- **Idempotent upsert**: 用 SQLite 原始 ID 做 Qdrant point ID
- **Batch embed**: 每批 32 条，避免 Ollama 超时

### Point ID Mapping

Qdrant point ID 是 UUID 或 uint64。策略：用 `collection_prefix + sqlite_rowid` 的确定性 UUID：

```python
import uuid
def make_point_id(collection: str, sqlite_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"orch.{collection}.{sqlite_id}"))
```

这样同一条 SQLite 记录永远映射到同一个 Qdrant point，重跑迁移不会产生重复。`orch_memory` 的 6 维表各自独立编号，用 `dimension + rowid` 拼接避免碰撞。

## Collections

| Collection | Source | Payload Fields | Search Use Case |
|---|---|---|---|
| `orch_learnings` | `events.db → learnings` | pattern_key, area, rule, context, department, status, recurrence, hotness_tier | "这类任务有什么已知坑？" |
| `orch_experiences` | `events.db → experiences` | date, type, summary, detail, instance | "上次这种情况怎么处理的？" |
| `orch_memory` | `memory.db → 6 维表` | dimension, confidence, tags, + 维度特有字段 | "主人对这个话题的偏好？" |
| `orch_runs` | `events.db → run_logs` | department, task_id, summary, status, duration_s, files_changed | "类似任务哪个部门干得好？" |
| `orch_files` | `events.db → file_index` | path, routing_hint, tags | "修改推送逻辑该找哪个文件？" |

### `orch_memory` Filter Strategy

`dimension` 字段做 Qdrant payload filter，不混搜 identity 和 activity：
```python
await qdrant.search("orch_memory", query, filters={"dimension": "preference"})
```

## Integration Points

### Write Path (4 injection points)

1. **`_learnings_mixin.py` → `add_learning()`**: INSERT INTO learnings 后 → `await qdrant.upsert("orch_learnings", ...)`
2. **`events_db.py` → `add_experience()`**: INSERT INTO experiences 后 → `await qdrant.upsert("orch_experiences", ...)`
3. **`structured_memory.py` → `StructuredMemoryStore.add()`**: INSERT INTO dimension table 后 → `await qdrant.upsert("orch_memory", ...)`
4. **Run logger → `log_run()`**: INSERT INTO run_logs 后 → `await qdrant.upsert("orch_runs", ...)`

File index 走定时同步（CAFI 本身是批量的）。

### Read Path (3 consumption points)

1. **Governor 派单前** (`dispatcher.py`):
   - `search("orch_learnings", task_description, top_k=3)` → 注入 "相关历史教训"
   - `search("orch_runs", task_description, top_k=3)` → 注入 "类似任务记录"

2. **Session 启动** (`executor_session.py`):
   - `search("orch_experiences", session_context, top_k=5)` → 语义检索相关经历
   - `search("orch_memory", session_context, top_k=5)` → 检索相关偏好/上下文

3. **Dedup 升级** (`dedup.py`):
   - `search("orch_learnings", new_rule, top_k=3)` → embedding 相似度替代 SequenceMatcher
   - top-1 score > 0.85 → 判定重复 → merge

## Degradation Strategy

```
Qdrant 挂了 → fallback 到 dedup.py 的 text_similarity()（SequenceMatcher）
Ollama 挂了 → embed 失败 → 写入跳过（数据还在 SQLite），检索降级
两个都挂了 → 系统正常运行，只是没有语义检索能力
```

`search_with_fallback()` 统一封装，调用方无感知。

## Migration

### Initial: `scripts/migrate_to_qdrant.py`

One-shot script:
1. 幂等创建 5 个 collection
2. 从 events.db 读 learnings → batch embed (32/batch) → upsert `orch_learnings`
3. 从 events.db 读 experiences → batch embed → upsert `orch_experiences`
4. 从 memory.db 读 6 维表 → batch embed → upsert `orch_memory`
5. 从 events.db 读 run_logs → batch embed → upsert `orch_runs`
6. 从 events.db 读 file_index → batch embed → upsert `orch_files`
7. 打印迁移报告（每 collection 数量 + 耗时 + embed 失败数）

失败容忍：单条 embed 失败记日志不中断，可重跑。

### Ongoing: `src/jobs/sync_vectors.py`

Scheduler 注册，每小时一次：
1. 对比 SQLite MAX(rowid) 和 Qdrant points_count
2. Upsert 增量
3. 清理已删除记录
4. 记日志

## What Doesn't Change

- `events.db` schema — SQLite 仍是权威数据源
- `memory.db` schema — structured_memory 继续独立存储
- `hotness.py` — 热度分层基于访问频率，和语义正交
- `memory_tier.py` — hot/extended 加载策略继续用

## What Gets Retired

- `src/storage/vector_db.py` → `.trash/`（被 `qdrant_store.py` 替代）

## Configuration

```python
# .env or src/core/config.py
QDRANT_URL = "http://localhost:6333"
QDRANT_URL_DOCKER = "http://host.docker.internal:6333"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_URL_DOCKER = "http://host.docker.internal:11434"
OLLAMA_EMBED_MODEL = "qwen3-embedding"
QDRANT_EMBED_DIM = 4096
```

Auto-detect: 容器内用 `_DOCKER` URL，宿主机用 localhost。

## New Dependencies

```
qdrant-client>=1.9.0
httpx
```

## File Map

| Action | File |
|---|---|
| **Create** | `src/storage/qdrant_store.py` |
| **Create** | `src/jobs/sync_vectors.py` |
| **Create** | `scripts/migrate_to_qdrant.py` |
| **Create** | `tests/test_qdrant_store.py` |
| **Modify** | `src/storage/_learnings_mixin.py` |
| **Modify** | `src/storage/events_db.py` |
| **Modify** | `src/governance/context/structured_memory.py` |
| **Modify** | `src/governance/dispatcher.py` |
| **Modify** | `src/storage/dedup.py` |
| **Modify** | `src/scheduler.py` |
| **Modify** | `requirements.txt` |
| **Retire** | `src/storage/vector_db.py` → `.trash/` |

## Testing

```
tests/test_qdrant_store.py:
  - test_embed_single / test_embed_batch (mock Ollama)
  - test_upsert_and_search (Qdrant in-memory mode)
  - test_fallback_when_unavailable (mock connection failure)
  - test_dedup_via_embedding (similar text score > 0.85)

tests/test_migration.py:
  - test_full_migration (SQLite fixture → Qdrant in-memory → count match)
```

Qdrant client supports `QdrantClient(":memory:")` for in-memory testing.
