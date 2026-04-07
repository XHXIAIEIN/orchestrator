# R44 — MemPalace Steal Report

**Source**: https://github.com/milla-jovovich/mempalace | **Stars**: 8,633 | **License**: MIT
**Date**: 2026-04-07 | **Category**: Module (AI Memory System)
**Codebase**: 8,052 LOC Python, 20 files | **Deps**: chromadb + pyyaml only

## TL;DR

**Problem space**: 6 months of daily AI use = 19.5M tokens of decisions, debugging sessions, architecture debates — all gone when sessions end. **Solution pattern**: Store everything verbatim in a spatially-organized hierarchy (Palace/Wing/Hall/Room/Closet/Drawer), then retrieve progressively (600-900 tokens wake-up → on-demand → deep search). Achieves 100% LongMemEval R@5 (hybrid v4 + Haiku rerank, 500/500) with zero cloud dependency. The hierarchy metadata alone delivers +34% retrieval improvement over flat vector search.

## Architecture Overview

```
Layer 4 — MCP Interface (19 tools, AAAK auto-teach, status/search/write)
Layer 3 — 4-Layer Memory Stack (L0 identity → L1 essential → L2 on-demand → L3 deep)
Layer 2 — Storage (ChromaDB vectors + SQLite knowledge graph + Palace graph)
Layer 1 — Ingest (normalize → detect entity/room → chunk → store verbatim)
Layer 0 — Hooks (Stop auto-save every 15 msgs + PreCompact emergency save)
```

**Data flow** (verified from code):
```
Files/Chats → normalize.py(5 formats) → detect_room(path>name>keywords)
  → chunk(800 chars, 100 overlap / exchange-pair for convos)
  → ChromaDB.add(verbatim, {wing, hall, room, source_file, importance})
  → search: L0+L1 wake-up(~600-900 tokens) → L2 filter(wing/room) → L3 semantic
```

## Steal Sheet

### P0 — Must Steal (5 patterns)

| # | Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---|---------|-----------|------------------|------------|--------|
| 1 | **4-Layer Memory Stack** | L0 identity(~100t) + L1 essential(~500-800t) always loaded; L2/L3 on-demand. Wake-up cost: ~600-900 tokens vs loading everything. `MemoryStack.wake_up()` unified interface | boot.md 编译到 ~1.7K tokens 全量加载; memory files 按需读取但无分层优先级 | 将 boot.md 拆为 L0(identity, ~100t) + L1(top-15 moments, ~500t)，L2/L3 保持现有按需读取 | ~3h |
| 2 | **Palace Hierarchy Metadata Filter** | Wing/Hall/Room 三级 metadata 标签存入 vector store，检索时先缩窄搜索范围再做 semantic match → +34% R@10。`where={"wing": wing}` 在所有 Layer 查询中使用 | Qdrant 存储有 collection 但无结构化 metadata 层级 | 为 Qdrant 文档添加 `domain`/`category`/`topic` 三级 metadata；检索时先 filter 再 query | ~4h |
| 3 | **Hook-Driven Auto-Save** | Stop hook 每 15 条消息 block AI 并强制记忆保存；PreCompact hook 在上下文压缩前做紧急保存。`stop_hook_active` 标志防死循环。状态文件 `hook_state/{session}_last_save` | 有 hooks 基础设施但没有自动记忆保存 hook | 新增 `hooks/memory_save_hook.sh`：计数交换次数 → 触发 `/remember` skill → 重置计数器。新增 PreCompact hook 做 emergency save | ~2h |
| 4 | **Temporal Knowledge Graph** | SQLite 三元组(subject, predicate, object) + valid_from/valid_to 时间窗口 + confidence。`query_entity(as_of=)` 时间点过滤。`invalidate()` 标记事实终止。`timeline()` 按时间排列 | events_db.py 存事件但无实体关系图，无时间有效性 | 在 events_db 旁新增 `knowledge_graph.py`：track 用户/项目/工具的关系 + 时间窗口。初期只追踪 project 类记忆 | ~4h |
| 5 | **Hybrid Keyword+Semantic Retrieval** | semantic top-50 → extract keywords(去停用词) → `fused_dist = dist * (1.0 - 0.30 * overlap)` → re-rank。4 个迭代版本(v1→v4)，v4 额外加 temporal boost + quoted phrase boost + person name boost | Qdrant 纯 semantic search，无 keyword boost | 在 qdrant_store.py 的 search 方法中添加 keyword overlap re-ranking 后处理步骤 | ~2h |

**NOTE**: 报告初版列了 AAAK Compression Dialect 为 P0。代码验证后降为 P1 — AAAK 的 30x 压缩声明基于 zettel JSON vs dialect 格式的对比（结构化数据 → 结构化数据），不是 natural language → compressed 的 30x。`dialect.compress()` 对纯文本的实际压缩比取决于文本长度和内容，对短文本可能只有 3-5x。核心价值在 L1 wake-up 的 token 控制思想，但我们用 boot.md compiler 已经在做类似的事。

### P1 — Worth Doing (6 patterns)

| # | Pattern | Mechanism | Adaptation | Effort |
|---|---------|-----------|------------|--------|
| 6 | **AAAK Compression Dialect** | 结构化符号速记 `ZID:ENTITIES\|topics\|"quote"\|WEIGHT\|EMOTIONS\|FLAGS`。20 种情感编码 + 7 种标志。对 zettel JSON ~30x 压缩 | 为 L1 层设计 Orchestrator 专用速记格式（项目状态、采集器状态、最近事件），目标 <200 tokens | ~3h |
| 7 | **Exchange-Pair Chunking** | 对话导入时 Q+A 作为原子单元（`>` turn + AI response = 一个 drawer），而非固定字符切分。`chunk_exchanges()` 检测 `>` 标记数量自动选择策略 | 改进对话类内容的 chunking 策略 | ~2h |
| 8 | **Contradiction Detection** | 新事实对照 knowledge graph 验证：归属冲突、任期错误、过期日期。动态计算而非硬编码 | 在 memory 写入时检查与已有 project/user 记忆的冲突 | ~3h |
| 9 | **Specialist Agent Diaries** | 每个 agent 有独立 wing + AAAK 日记，持久化跨会话。`diary_write/diary_read` MCP 工具 | 为三省六部各部门添加独立记忆 wing | ~4h |
| 10 | **Entity Detection (Person vs Project)** | 多信号分类：对话标记(3x)、动作动词(2x)、代词邻近(2x)、直接称呼(4x)。要求 ≥2 种不同信号类别才确认为 person | 改进 entity_registry 的人/项目分类 | ~3h |
| 11 | **Verbatim-First Storage** | 永不摘要，存原文。语义搜索弥补存储增加。审计可追溯 | memory 文件保留更多原始上下文，不过度压缩 | ~1h（设计理念调整） |

### P2 — Reference Only (4 patterns)

| # | Pattern | Mechanism | Why ref-only |
|---|---------|-----------|-------------|
| 12 | **Format Normalization** | 5 种聊天格式(Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, plain text)统一为 `> user\nassistant` 转录格式 | 我们不导入外部聊天记录，但模式可参考 |
| 13 | **Room Auto-Detection** | 路径 > 文件名 > 内容关键词 三级优先级检测所属 room。`detect_room()` 中 3 层 fallback | 有趣但我们的分类逻辑不同 |
| 14 | **Benchmark-Driven Iterative Optimization** | v1→v4 四代迭代，每代针对特定失败类型添加修复（v2: temporal boost, v3: preference extraction, v4: quoted phrase + person name boost）| 方法论值得学习但需要自建测试集 |
| 15 | **MCP as Memory Interface** | 19 个 MCP 工具暴露 palace 读写/搜索/图谱操作 | 我们已有 MCP 基础设施 |

## Code Evidence (P0 Patterns)

### P0#1 — 4-Layer Memory Stack (`layers.py`)

```python
# layers.py:360-408 — MemoryStack unified interface
class MemoryStack:
    def __init__(self, palace_path=None, identity_path=None):
        self.l0 = Layer0(identity_path)      # ~100 tokens, always loaded
        self.l1 = Layer1(palace_path)         # ~500-800 tokens, always loaded
        self.l2 = Layer2(palace_path)         # on-demand, wing/room filter
        self.l3 = Layer3(palace_path)         # full semantic search

    def wake_up(self, wing=None) -> str:
        """L0 + L1. ~600-900 tokens. Inject into system prompt."""
        parts = [self.l0.render(), "", self.l1.generate()]
        return "\n".join(parts)
```

L1 关键机制：从 ChromaDB 拉全部 drawers → 按 importance 降序 → 取 top 15 → 按 room 分组 → 硬上限 3200 chars (~800 tokens)。

```python
# layers.py:83-84 — L1 hard caps
MAX_DRAWERS = 15    # at most 15 moments in wake-up
MAX_CHARS = 3200    # hard cap on total L1 text (~800 tokens)
```

### P0#3 — Hook-Driven Auto-Save (`hooks/mempal_save_hook.sh`)

```bash
# 核心防死循环机制：
# Stop hook 第一次触发 → block + reason → AI 执行保存 → 再次 Stop → stop_hook_active=true → 放行
if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"   # 放行，防止无限循环
    exit 0
fi

# 计数人类消息
EXCHANGE_COUNT=$(python3 -c "..." 2>/dev/null)
SINCE_LAST=$((EXCHANGE_COUNT - LAST_SAVE))

# 达到阈值 → block AI，注入保存指令
if [ "$SINCE_LAST" -ge "$SAVE_INTERVAL" ]; then
    echo "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"
    cat << 'HOOKJSON'
    {"decision": "block", "reason": "AUTO-SAVE checkpoint. Save key topics..."}
    HOOKJSON
fi
```

PreCompact hook 更简单 — **始终 block**，因为 compaction = 必须保存：

```bash
# hooks/mempal_precompact_hook.sh — 无条件 block
cat << 'HOOKJSON'
{"decision": "block", "reason": "COMPACTION IMMINENT. Save ALL topics..."}
HOOKJSON
```

### P0#4 — Temporal Knowledge Graph (`knowledge_graph.py`)

```python
# knowledge_graph.py:57-85 — SQLite schema
CREATE TABLE entities (
    id TEXT PRIMARY KEY, name TEXT, type TEXT DEFAULT 'unknown',
    properties TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE triples (
    id TEXT PRIMARY KEY,
    subject TEXT, predicate TEXT, object TEXT,
    valid_from TEXT, valid_to TEXT,           -- 时间窗口
    confidence REAL DEFAULT 1.0,             -- 可信度
    source_closet TEXT, source_file TEXT,     -- 溯源
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject) REFERENCES entities(id),
    FOREIGN KEY (object) REFERENCES entities(id)
);

# knowledge_graph.py:169-180 — invalidate() 标记事实终止
def invalidate(self, subject, predicate, obj, ended=None):
    ended = ended or date.today().isoformat()
    conn.execute(
        "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
        (ended, sub_id, pred, obj_id),
    )

# knowledge_graph.py:186-241 — as_of 时间点查询
def query_entity(self, name, as_of=None, direction="outgoing"):
    query += " AND (t.valid_from IS NULL OR t.valid_from <= ?) AND (t.valid_to IS NULL OR t.valid_to >= ?)"
```

### P0#5 — Hybrid Keyword+Semantic (`benchmarks/longmemeval_bench.py`)

**重要发现**：hybrid search 只存在于 benchmark 代码中（v1-v4 四个版本），**未集成进生产 `searcher.py`**。`searcher.py` 仍是纯 ChromaDB semantic search。

```python
# longmemeval_bench.py:485-628 — hybrid v1 核心
def build_palace_and_retrieve_hybrid(entry, granularity="session", n_results=50, hybrid_weight=0.30):
    # Stage 1: semantic search
    results = col.query(query_texts=[query], n_results=n_results, ...)

    # Stage 2: keyword overlap re-ranking
    query_keywords = extract_keywords(query)  # 去停用词
    scored = []
    for rid, dist, doc in zip(result_ids, distances, documents):
        overlap = keyword_overlap(query_keywords, doc)
        fused_dist = dist * (1.0 - hybrid_weight * overlap)  # 核心公式
        scored.append((idx, fused_dist))
    scored.sort(key=lambda x: x[1])  # 重新排序

# v4 额外增加：
# - temporal boost: fused_dist *= (1.0 - 0.40 * proximity_factor)
# - quoted phrase boost: fused_dist *= (1.0 - 0.60 * q_boost)
# - person name boost: fused_dist *= (1.0 - 0.40 * n_boost)
```

这意味着我们偷这个模式时，可以直接做成生产级 — 比原项目领先。

## Triple Validation Gate (P0 Patterns)

| Pattern | Cross-domain | Generative Power | Exclusivity | Score |
|---------|:---:|:---:|:---:|:---:|
| **4-Layer Memory Stack** | MemPalace + Zep(temporal layers) + 我们的 boot.md compiler 都在做分层 | 能预测任何新的记忆系统应该如何分层：identity → essential → on-demand → deep | 具体的 MAX_DRAWERS=15, MAX_CHARS=3200 硬上限是非通用的阈值选择 | 3/3 ✓ |
| **Palace Hierarchy Metadata** | ChromaDB metadata filter + Qdrant payload filter + Elasticsearch 都用结构化 filter | 对任何 vector store 检索，能预测"先 filter 后 search"优于"纯 search" | +34% 提升数据来自特定 benchmark，但原理是排除噪声，具有结构排他性 | 3/3 ✓ |
| **Hook-Driven Auto-Save** | Claude Code hooks + git hooks + CI/CD webhooks 都用 event-driven 自动化 | 能预测任何 AI 编码助手的记忆衰减点：context compaction 和 session end | `stop_hook_active` 防死循环 + `{"decision":"block","reason":"..."}` 模式是 Claude Code 特有的 | 2/3 ✓ (排他性部分 — 通用 hook pattern) |
| **Temporal KG** | Zep(GraphRAG) + Mem0(graph memory) + Wikipedia(temporal facts) 都有时间维度 | 对任何事实追踪，能预测何时需要 `as_of` 查询 vs 当前状态查询 | SQLite triples + `invalidate()` 是对 Neo4j 的极简替代，零成本，这个简化选择有排他性 | 3/3 ✓ |
| **Hybrid Keyword+Semantic** | ElasticSearch BM25+vector, Pinecone hybrid, Weaviate hybrid 都做 keyword+semantic | 能预测何时纯 semantic 会 miss：专有名词、具体数字、引用短语 | `fused_dist = dist * (1 - w * overlap)` 是最简实现，但 v1→v4 的渐进迭代方法论有独特性 | 2/3 ✓ (排他性部分 — 业界标准做法) |

## Knowledge Irreplaceability Assessment (P0 Patterns)

| Pattern | Pitfall Memory | Judgment Heuristics | Hidden Context | Failure Memory | Unique Behavior | Score |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| **4-Layer Stack** | | ✓ MAX_DRAWERS=15 是调参经验 | ✓ 600-900t 不是 170t | | ✓ wake_up() 统一接口 | 3 |
| **Palace Hierarchy** | | ✓ +34% 来自 metadata filter | | | ✓ detect_room() 三级 fallback | 2 |
| **Hook Auto-Save** | ✓ 不防死循环会无限触发 | ✓ 15 条消息是经验阈值 | ✓ stop_hook_active 是 Claude Code 特有 | ✓ PreCompact = emergency save | | 4 |
| **Temporal KG** | | ✓ invalidate() 比 delete 更安全 | ✓ valid_to IS NULL = 当前有效 | | ✓ SQLite 替代 Neo4j | 3 |
| **Hybrid Search** | ✓ 纯 semantic 会 miss 专有名词 | ✓ weight=0.30 是调参经验 | ✓ 只在 benchmark 中，未进生产 | ✓ v1→v4 每代修复特定失败类型 | | 4 |

## Comparison Matrix (P0 Patterns)

| Capability | MemPalace impl | Our impl | Gap | Action |
|-----------|---------------|---------|-----|--------|
| **Context budget on wake-up** | ~600-900 tokens (L0+L1), 硬上限 3200 chars | ~1,700 tokens (boot.md 全量) | **2x 过大** | Steal: 拆分 L0/L1 层，boot.md 瘦身到 ~800t |
| **Memory hierarchy** | Wing/Hall/Room 三级 metadata filter，验证 +34% | Qdrant collection 无结构化 metadata | **Large** | Steal: 添加 domain/category/topic metadata |
| **Auto-save mechanism** | Stop hook (每15条) + PreCompact hook (总是)，bash 状态机 | 无自动记忆保存 | **Large** | Steal: 新增两个 hook |
| **Temporal fact tracking** | SQLite triples + valid_from/to + invalidate() + as_of 查询 | events_db 无时间有效性 | **Large** | Steal: 新增 knowledge_graph 模块 |
| **Retrieval quality** | Hybrid keyword+semantic, 100% R@5 (v4+rerank), 但只在 benchmark 代码中 | Pure semantic, 未测量 | **Medium** | Steal: 添加 keyword re-rank，直接做成生产级 |

**NOTE on wake-up tokens**: 初版报告写 170 tokens 是错的。`layers.py` docstring 明确写 "~600-900 tokens (L0+L1)"，L0 ~100t + L1 up to 800t (MAX_CHARS=3200, ~800 tokens)。与我们的 1.7K 差距是 ~2x 不是 10x，但分层思想的价值不变。

## Gaps Identified

| Dimension | MemPalace | Orchestrator | Gap |
|-----------|-----------|-------------|-----|
| **Memory/Learning** | 4-layer stack, AAAK compression, dedup check, importance scoring, temporal KG | Flat memory files, Qdrant for embeddings, manual memory management | **Large**: 无分层加载、无压缩、无时间有效性 |
| **Execution/Orchestration** | CLI + MCP server, hook-driven auto-save | Agent SDK + 三省六部, hooks infra | **Small**: 我们的编排更强，但缺自动记忆保存 |
| **Context/Budget** | 600-900 tokens wake-up, progressive disclosure, MAX_CHARS hard cap | ~1.7K tokens boot.md | **Medium**: wake-up 成本 ~2x 高，无硬上限 |
| **Quality/Review** | Contradiction detection, dedup via semantic similarity | 无矛盾检测，无 dedup | **Medium**: 记忆质量无门禁 |
| **Failure/Recovery** | PreCompact emergency save, graceful degradation（collection 不存在返回友好消息） | 无 context 丢失保护 | **Medium**: 上下文压缩时可能丢失重要记忆 |
| **Security/Governance** | Local-only, no API keys for core | Local + optional cloud | **None**: 我们也是 local-first |

## Adjacent Discoveries

1. **ChromaDB 的 all-MiniLM-L6-v2 默认 embedding** — 不需要外部 API 就能做 semantic search，100% R@5 准确率（v4+rerank）证明了 small embedding models + 好结构的能力。我们用 Qdrant，可以考虑在无 GPU 环境下 fallback 到本地 embedding
2. **Zep/Graphiti 的 SQLite 替代** — MemPalace 用 SQLite 替代 Neo4j 实现时态知识图谱，功能够用且零成本。我们的 events_db 也用 SQLite，可以直接扩展
3. **LongMemEval benchmark** — 500 题标准测试集，可复现。如果我们要量化记忆系统改进，这是现成的工具
4. **"Block then teach" hook pattern** — hook 返回 `{"decision": "block", "reason": "..."}` 让 AI 看到 reason 作为系统消息执行操作。这个模式在我们的 hook 体系里可以广泛应用（不只记忆 — 任何需要强制 AI 行为的场景）
5. **Benchmark code 与 production code 分离** — MemPalace 的最佳检索算法（hybrid v4）只在 benchmark 中，未进主库。这是一个常见的开源项目模式：研究级代码和生产级代码脱节。我们偷的时候可以直接合并

## Meta Insights

### 1. 结构 > 算法

MemPalace 最大的洞察不是技术性的，而是认知性的：**34% 的检索提升来自组织结构（Wing/Hall/Room metadata filter），不是来自更好的 embedding 模型或更复杂的算法。** 这颠覆了 "用更强的模型解决一切" 的思路。我们的 Qdrant 虽然是更好的 vector store，但如果文档没有结构化 metadata，检索质量上限就被卡死了。

### 2. 极简依赖 = 可靠性

整个系统只依赖 `chromadb` + `pyyaml`。8,052 行代码。没有 LangChain，没有 LlamaIndex，没有 OpenAI SDK。纯正则 + 启发式 + ChromaDB 就打到 100%（v4+rerank）。这是对 "需要 AI 来管理 AI 记忆" 的有力反驳 — **不需要，好的数据结构就够了。**

### 3. Hook 是 Agent Memory 的心跳

MemPalace 最巧妙的设计不是 Palace 结构，而是 **Stop + PreCompact 双 hook** 构成的自动记忆心跳。没有这两个 hook，再好的记忆系统也依赖用户手动 "记一下"。这把记忆从 "被动工具" 变成了 "主动习惯"。核心技巧是 `stop_hook_active` 防死循环 — 一个 boolean 标志就解决了 hook 递归问题。

### 4. 渐进迭代 > 一次性设计

hybrid v1→v4 的演进路径是教科书级的工程方法：
- v1: 基础 keyword overlap（`fused_dist = dist * (1 - 0.30 * overlap)`）
- v2: + temporal boost（时间接近 → 距离缩减 40%）
- v3: + preference extraction（偏好类查询特殊处理）
- v4: + quoted phrase boost + person name boost（针对最后 3 个 miss）

每个版本精确定位剩余 failure cases，**不是重新设计，而是在现有基础上叠加针对性修复**。这比我们常见的 "推倒重来" 模式高效得多。

### 5. 记忆系统的真正竞争不是准确率，是使用摩擦

Mem0 收 $19-249/月，Zep 收 $25/月+，但 MemPalace 免费 + 本地 + 100% 准确率。这些商业产品输的不是技术，是**摩擦** — 需要 API key、需要注册、需要信任第三方。MemPalace 赢在零摩擦。我们的 Orchestrator 记忆系统也应该追求零摩擦的自动化路线 — **P0#3 的 hook auto-save 就是降低摩擦的关键一步**。

## Implementation Priority

基于 P0 模式的依赖关系和 ROI，建议实施顺序：

1. **Hook-Driven Auto-Save** (P0#3, ~2h) → 最高 ROI，立即可用，零依赖
2. **Hybrid Keyword+Semantic** (P0#5, ~2h) → 现有 Qdrant 搜索直接增强，且能做成生产级（原项目只在 benchmark 中）
3. **4-Layer Memory Stack** (P0#1, ~3h) → 依赖 boot.md 重构
4. **Palace Hierarchy Metadata** (P0#2, ~4h) → 依赖 Qdrant schema 修改
5. **Temporal Knowledge Graph** (P0#4, ~4h) → 独立模块，可并行

Total P0 effort: ~15h
