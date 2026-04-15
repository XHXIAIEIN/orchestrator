# R67 — MemPalace v3.3.0 深挖报告

> 来源：`D:/Agent/.steal/mempalace/`（已克隆）
> 分析日期：2026-04-14
> 版本：v3.3.0（develop 分支）
> 许可：MIT
> 前次偷师：R44（已过时）

---

## 一、目标概述

MemPalace 是一个针对 AI agent 设计的本地持久化记忆系统。用**宫殿比喻**组织记忆：Wing（翼）= 项目，Room（房间）= 主题，Drawer（抽屉）= 原文块，Closet（壁橱）= 搜索索引。

v3.3.0 相比 R44 是实质性升级：壁橱层从草稿变成了完整实现，BM25 混合搜索落地，Hall 分类系统上线，Cross-wing Tunnel（跨翼隧道）引入了多项目关联。

---

## 二、记忆架构深析

### 2.1 空间隐喻的实现

```
Palace（宫殿）= ChromaDB PersistentClient 实例（~/.mempalace/palace/）
├── Wing（翼）= 项目命名空间，metadata 字段 wing="project_name"
│   ├── Room（房间）= 主题分类，metadata 字段 room="auth-design"
│   │   ├── Drawer（抽屉）= 原文 chunk，~800 字符，存在 mempalace_drawers collection
│   │   └── Closet（壁橱）= 话题索引，格式 "topic|entities|→drawer_id"，存在 mempalace_closets collection
│   └── Hall（走廊）= 内容类型路由，metadata 字段 hall="technical/emotions/family/..."
└── Tunnel（隧道）= 跨翼显式链接，存在 ~/.mempalace/tunnels.json（不在 ChromaDB，跨重建持久化）
```

**两层 ChromaDB collection 并行**：
- `mempalace_drawers`：原文，用于语义检索（`hnsw:space=cosine`）
- `mempalace_closets`：话题指针，用于快速 BM25 提升（格式：`built auth system|Ben;Igor|→drawer_abc123`）

### 2.2 四层记忆栈

来自 `layers.py`，是给 agent 使用的消费接口：

| 层级 | Token 成本 | 触发方式 | 实现 |
|------|-----------|---------|------|
| L0 Identity | ~100 | 每次唤醒 | `~/.mempalace/identity.txt` 纯文本 |
| L1 Essential Story | ~500-800 | 每次唤醒 | 从 palace 抓 top-importance drawers，按 room 分组 |
| L2 On-Demand | ~200-500/次 | 特定 wing/room 被提及时 | ChromaDB `.get()` + wing/room filter |
| L3 Deep Search | 无上限 | 需要深度检索时 | ChromaDB `.query()` 向量检索 |

```python
stack = MemoryStack()
print(stack.wake_up())               # L0 + L1，~600-900 tokens
print(stack.recall(wing="my_app"))   # L2 按需
print(stack.search("pricing change")) # L3 深搜
```

唤醒成本控制在 600-900 tokens，保留 95%+ context window。

### 2.3 存储后端

**主存储**：ChromaDB PersistentClient（SQLite + hnswlib）
- v3.2.0 修复了 BLOB seq_id 迁移 bug（0.6.x → 1.5.x）
- v3.3.0 修复了 `hnsw:space=cosine` 未正确设置导致相似度打分用 L2 距离的 bug（影响所有 0.3.x 之前版本）

**知识图谱**：SQLite（`~/.mempalace/knowledge_graph.sqlite3`）
- WAL 模式，线程安全
- 三元组结构：`subject → predicate → object`，带 `valid_from / valid_to` 时间窗口
- 支持 `as_of` 时间点查询（"2026 年 1 月 Max 的状态是什么"）

**隧道**：JSON 文件（`~/.mempalace/tunnels.json`）
- 不放 ChromaDB，是为了跨 palace 重建持续存在
- 原子写：先写 `.tmp` 再 `os.replace()` + `fsync`

---

## 三、v3.3.0 新增功能（相比 R44 的变化）

### 3.1 壁橱层（Closet Layer）— 最重要的变化

v3.3.0 中壁橱从实验性功能变成了核心搜索路径。

**壁橱内容格式**（`palace.py::build_closet_lines()`）：
```
built auth system|Ben;Igor|→drawer_api_auth_a1b2c3,drawer_api_auth_d4e5f6
"we need to ship this before Friday"|Ben|→drawer_api_auth_a1b2c3
```
- 每行一个话题指针，原子不可分割
- 最多 1500 字符/壁橱，超出自动开新壁橱
- 话题提取：动词短语 + 章节标题 + 引用
- 实体提取：正则捕捉大写词（≥2次出现），过滤 200 个常见停用词

**壁橱生命周期**：
1. `mine` 时 → `process_file()` 调用 `build_closet_lines()` + `upsert_closet_lines()`
2. 重新挖掘时 → `purge_file_closets()` 先删干净再重写（防止旧话题残留）
3. `NORMALIZE_VERSION` 升级 → 旧壁橱被视为 stale，下次 mine 自动重建

**可选 LLM 增强**（`closet_llm.py`）：
```python
# 用 Ollama/OpenAI 兼容接口替换 regex 提取，生成更好的话题
regenerate_closets(
    palace_path,
    cfg=LLMConfig(endpoint="http://localhost:11434/v1", model="llama3:8b")
)
```
零强制依赖，纯 stdlib urllib，用户自带 LLM。

### 3.2 BM25 混合搜索（`searcher.py`）

```python
# 搜索路径：drawer 向量检索（基准） + closet 排名提升（信号）
# closet 是 boost，永远不是 gate

CLOSET_RANK_BOOSTS = [0.40, 0.25, 0.15, 0.08, 0.04]  # 按 closet 命中排名
CLOSET_DISTANCE_CAP = 1.5  # 余弦距离 > 1.5 的 closet 不用作信号

# 第一阶段：drawer 向量检索（过量取 n*3）
drawer_results = drawers_col.query(query_texts=[query], n_results=n_results * 3)

# 第二阶段：closet 命中 → 排名提升
for rank, (cdoc, cmeta, cdist) in enumerate(closet_results):
    source = cmeta.get("source_file", "")
    closet_boost_by_source[source] = (rank, cdist, cdoc[:200])

# 第三阶段：effective_distance = raw_distance - boost
effective_dist = dist - boost

# 第四阶段：drawer-grep：对 closet 命中的多 drawer 文件，找关键词最佳块+邻居
# 避免向量搜索选错了同一文件内的 chunk

# 第五阶段：BM25 重排（Okapi-BM25，候选集内相对 IDF）
hits = _hybrid_rank(hits, query)
```

设计原则：**closet 是排名信号，从不封锁 drawer 直接路径**，防止 regex 提取质量差时隐藏结果。

### 3.3 Hall 分类系统

```python
DEFAULT_HALL_KEYWORDS = {
    "emotions": ["scared", "afraid", "worried", "happy", "sad", "love", ...],
    "consciousness": ["consciousness", "aware", "real", "genuine", "soul", ...],
    "memory": ["memory", "remember", "forget", "recall", ...],
    "technical": ["code", "python", "script", "bug", "error", "function", ...],
    "identity": ["identity", "name", "who am i", "persona", "self"],
    "family": ["family", "kids", "children", "daughter", "son", ...],
    "creative": ["game", "gameplay", "player", "app", "design", ...],
}
```

Hall 决定内容类型，Room 决定话题。`detect_hall(content)` 在存入每个 drawer 时打上 `hall` metadata，供 `palace_graph.py` 图遍历时区分边的类型。

### 3.4 Cross-Wing 隧道

v3.3.0 新增两类隧道：

**被动隧道**：同名 room 出现在多个 wing 时自动发现（`palace_graph.py::find_tunnels()`）
```python
# chromadb-setup 同时在 wing_code 和 wing_myproject → 自动创建被动隧道
for room, data in nodes.items():
    if len(data["wings"]) >= 2:  # 被动隧道
        tunnels.append(...)
```

**显式隧道**：agent 手动创建，存 JSON（跨重建持久化）：
```python
create_tunnel(
    source_wing="project_api", source_room="auth-design",
    target_wing="project_database", target_room="schema",
    label="API auth depends on user table schema"
)
```
隧道 ID 对称（A→B 和 B→A 哈希相同），防重复。

### 3.5 日记摄入（Diary Ingest）

`diary_ingest.py`：专门处理日期命名的 markdown 文件（`YYYY-MM-DD.md`）。
- 每天一个 drawer（完整原文 upsert）
- 按 `## entry` 分割生成壁橱
- 增量处理（state 文件记录上次 entry count，只处理新增条目）
- State 文件写到 `~/.mempalace/state/`，不污染用户日记目录

### 3.6 Agent WAL（写前日志）

MCP server 每次写操作前追加审计日志到 `~/.mempalace/wal/write_log.jsonl`：
```json
{
  "timestamp": "2026-04-14T...",
  "operation": "add_drawer",
  "params": {
    "drawer_id": "drawer_...",
    "wing": "project_api",
    "content_preview": "[REDACTED 342 chars]"  // 内容自动脱敏
  }
}
```
WAL 文件权限 0o600，只有 owner 可读。

---

## 四、六维扫描

### 维度 1：记忆/学习（60% 权重）★★★★★

**最强点**：

1. **原文忠实存储**：所有 drawer 存原文（verbatim），永不摘要。搜索召回 96.6%（benchmark 数据）。这是与 Zep/Mem0 的核心区别——后者在存储时摘要，失去精度。

2. **双轨检索**：向量相似度 + BM25 词频，两者按 6:4 权重融合，解决了纯向量检索在短精确词（代码变量名、人名）上的盲区。

3. **壁橱索引层**：解决了 ChromaDB 大规模时的检索效率问题——先命中小文档（壁橱），再 hydrate 原文。实测壁橱文档 <1500 字符，向量检索快 10x+。

4. **Drawer-grep 上下文**：closet 命中后，不直接返回向量搜索选中的 chunk，而是在该文件内用关键词找最佳块，再返回 ±1 邻居。解决了 chunk 边界切割导致的语义截断问题。

5. **时间知识图谱**：SQLite 存 subject→predicate→object + valid_from/valid_to。支持时间点查询，相当于免费的 Zep 时态图（Zep 收费 $25/mo+，用 Neo4j）。

**弱点**：

- Hall 分类用关键词打分，无语义理解。"I feel so code-happy today" 会被判为 `technical`。
- AAAK 压缩格式（dialect.py）存入 ChromaDB 时降低嵌入质量（压缩代码 `ALC` 的向量和 `Alice` 不同），代码里有 TODO 标注但未修复。

### 维度 2：集成模式 ★★★★☆

MCP 服务器实现完整，工具列表丰富（约 25 个工具）：

| 工具类别 | 工具数 | 备注 |
|---------|--------|------|
| 读取 | 8 | status, search, list_wings, list_rooms, taxonomy, get_drawer, list_drawers, check_duplicate |
| 写入 | 5 | add_drawer, delete_drawer, update_drawer, diary_write, kg_add/invalidate |
| 图遍历 | 6 | traverse, find_tunnels, graph_stats, create/list/delete_tunnel |
| 知识图谱 | 5 | kg_query, kg_add, kg_invalidate, kg_timeline, kg_stats |
| 维护 | 3 | reconnect, hook_settings, memories_filed_away |

支持 Claude Code、Codex CLI、Gemini CLI 三个平台。MCP 服务器通过 inode + mtime 双重检测自动重连（解决外部脚本修改后 HNSW 索引 stale 的问题）。

### 维度 3：安全边界 ★★★★☆

- 输入验证：`sanitize_name()` 阻止路径遍历（`..`、`/`、`\\`），长度限制 128 字符，字符白名单
- 查询净化：`query_sanitizer.py` 检测系统提示污染（Issue #333，89.8% → 1.0% 召回率崩溃）
- WAL 审计：所有写操作前记录，内容自动 REDACT
- 并发安全：`mine_lock()` 跨平台文件锁（Windows 用 msvcrt，Unix 用 fcntl），防止多 agent 并发 mine 产生重复 drawer

### 维度 4：可扩展性 ★★★☆☆

后端抽象层（`backends/base.py` + `backends/chroma.py`）存在但很薄，只有 6 个方法（add/upsert/query/get/delete/count）。替换 ChromaDB 是可行的但需要一定工作量。

ChromaDB 本身限制：
- 每次 query 前重新生成嵌入（无嵌入缓存）
- HNSW 在 100k+ drawer 时内存占用显著
- SQLite WAL 在高并发写入时仍有争用

### 维度 5：可观测性 ★★★☆☆

- `mempalace status`：wing/room/drawer 统计
- `mempalace_graph_stats`：图拓扑统计
- WAL 文件提供审计轨迹
- 缺少：drawer 访问频率、搜索命中率、cold/hot 分层统计

### 维度 6：开发体验 ★★★★☆

- 零强制 API key，本地优先
- `uv` 管理依赖
- 8 种语言 i18n 支持（zh-CN, zh-TW 已有）
- 85% 测试覆盖率（v3.1.0 之前是 20%）
- Claude Code / Codex / Gemini 三平台插件一键配置

---

## 五、五层深度分析（核心模块）

以 **搜索路径** 为核心展开（这是整个系统最复杂的实现）：

### 调度层（Dispatch Layer）

```
MCP tool call: mempalace_search(query, wing, room, limit)
    ↓
tool_search() in mcp_server.py
    ↓ query sanitization (query_sanitizer.py)
    ↓ wing/room validation (sanitize_name)
    ↓
search_memories(query, palace_path, wing, room, n_results, max_distance)
    in searcher.py
```

### 实践层（Implementation Layer）

`search_memories()` 五阶段流程：

```
阶段1 Drawer 向量检索（floor，永远运行）
    → drawers_col.query(n_results=n_results*3)  # 过量取，为重排留空间

阶段2 Closet 命中收集（可选 boost）
    → closets_col.query(n_results=n_results*2)
    → 按 source_file 分组，每个文件取最佳 closet
    → 记录 (rank, distance, preview) 三元组

阶段3 Boost 计算
    → effective_dist = raw_dist - CLOSET_RANK_BOOSTS[closet_rank]
    → closet_dist > 1.5 的不用（太弱不算信号）

阶段4 Drawer-grep 精炼（仅 closet 命中的多 drawer 文件）
    → 取该 source_file 所有 drawers
    → 关键词匹配找最佳 chunk
    → 返回 best_idx ± 1 邻居合并文本

阶段5 BM25 混合重排
    → _hybrid_rank(hits, query)
    → 向量相似度 * 0.6 + BM25归一化分 * 0.4
```

### 消费层（Consumer Layer）

```python
# MCP 工具消费
result = tool_search("pricing change", limit=5, wing="project_api")
# 返回结构：
{
    "query": "pricing change",
    "results": [
        {
            "text": "...",           # 可能是原始 chunk 或 drawer-grep 扩展文本
            "wing": "project_api",
            "room": "billing",
            "similarity": 0.847,
            "distance": 0.153,
            "effective_distance": 0.003,  # 经 closet boost 后
            "closet_boost": 0.150,
            "matched_via": "drawer+closet",
            "closet_preview": "pricing system|Alice;Bob|→drawer_...",
            "drawer_index": 2,
            "total_drawers": 5,      # 仅 drawer-grep 扩展时有
        }
    ]
}
```

### 状态层（State Layer）

```
ChromaDB 持久化（主存储）：
    ~/.mempalace/palace/chroma.sqlite3
    HNSW 索引（内存中 + SQLite 持久化）

Knowledge Graph（辅助存储）：
    ~/.mempalace/knowledge_graph.sqlite3
    WAL 模式，entities + triples 两张表

Tunnels（跨重建持久化）：
    ~/.mempalace/tunnels.json
    原子写（os.replace）

Write-Ahead Log（审计）：
    ~/.mempalace/wal/write_log.jsonl

Entity Cache（内存缓存）：
    _ENTITY_REGISTRY_CACHE（mtime-gated，按需刷新）

MCP Server 缓存：
    _client_cache + _collection_cache（inode + mtime 双重失效）
    _metadata_cache（5 秒 TTL）
```

### 边界层（Boundary Layer）

硬性限制：
- Drawer 大小：800 字符/chunk，100 字符 overlap
- Closet 大小：1500 字符/壁橱
- 文件大小上限：10 MB
- entity metadata 上限：25 个实体/drawer
- MCP search 结果上限：100（`_MAX_RESULTS`）
- 日记抽屉：每 wing+day 一个（upsert 不新增）
- ChromaDB `.get()` 无 limit 时隐式截断 10k —— mcp_server 通过分页解决

---

## 六、路径依赖分析

### 决策一：ChromaDB 作为唯一向量存储

锁定点是 `hnsw:space=cosine` metadata、BLOB seq_id 修复代码、以及 inode+mtime 缓存失效逻辑，这些都深度绑定 ChromaDB 内部实现。替换代价约 1-2 周。

理由：零配置本地启动。在 embedded 模式下不需要独立服务进程，适合 agent 开机即用的场景。

**Orchestrator 影响**：我们用不到 ChromaDB（没有向量搜索），但其"壁橱+抽屉分离"的两集合架构值得借鉴，用于现有的 SOUL 文件索引。

### 决策二：原文存储，永不摘要

MemPalace 的核心立场：摘要发生在读取时（L1 Essential Story 由 agent 在上下文窗口里生成），不在写入时。写入时只存原文。

这与 Mem0/Zep 的在线摘要派（写入时压缩）是对立的设计哲学。代价是存储量大，但召回率保持 96.6%。

### 决策三：两集合分离（drawers + closets）

不把话题索引和原文混在一个集合里，而是分离为两个 ChromaDB collection。好处：
- 壁橱扫描快（文档小）
- 原文内容不受索引质量影响（closet 弱不会让原文丢失）
- 独立 purge/rebuild 无干扰

### 决策四：WAL 先于写入

所有写操作记录 WAL 后再执行，内容自动脱敏（REDACT）。这是对"memory poisoning"攻击的防线——外部 agent 写入时有完整审计轨迹。

---

## 七、可偷模式（Pattern Extraction）

### P0 — 立刻能用，无需基础设施

---

#### P0.1 查询净化器（Query Sanitizer）

**描述**：AI agent 有时把整个 system prompt 前缀到搜索 query。这导致嵌入向量被 2000+ 字符的提示词淹没，实测召回率从 89.8% 崩到 1.0%。MemPalace 的四步净化策略：
1. ≤200 字符 → 直接通过
2. 找包含 `?` 的最后一句 → 提取为 query
3. 找最后一个非空段落 → 用作 query
4. 截取最后 250 字符 → 兜底

**代码**（`query_sanitizer.py`，可直接迁移）：
```python
def sanitize_query(raw_query: str) -> dict:
    if original_length <= SAFE_QUERY_LENGTH:  # 200
        return {"clean_query": raw_query, "was_sanitized": False, "method": "passthrough"}
    
    # 找最后一个问句
    for seg in reversed(raw_query.split("\n")):
        if _QUESTION_MARK.search(seg) and len(seg) >= MIN_QUERY_LENGTH:
            return {"clean_query": seg, "was_sanitized": True, "method": "question_extraction"}
    
    # 截尾兜底
    return {"clean_query": raw_query[-MAX_QUERY_LENGTH:], "was_sanitized": True, "method": "tail_truncation"}
```

**与 Orchestrator 现状对比**：

| 项目 | MemPalace | Orchestrator 现状 |
|------|-----------|-----------------|
| 搜索 query 净化 | 四步净化，量化 89.8%→70%+ | 无净化逻辑 |
| 污染检测 | 自动，基于长度+问号 | 无 |
| 降级策略 | 四步梯度 | 无 |

**三重验证**：
1. `query_sanitizer.py` 有 42 个回归测试（Issue #335）
2. Issue #333 记录了真实召回率崩溃案例（1.0%）
3. 代码逻辑简单，无外部依赖，可直接 copy

**知识不可替代性**：这个问题在没有实测的情况下不会意识到。MemPalace 用 benchmark 量化了 query 污染的影响程度——89.8% 到 1.0%，不是"可能有点影响"，是"几乎完全失效"。这个数据本身就是知识。

**适配方案**：
1. 把 `query_sanitizer.py` 复制到 `SOUL/tools/` 或相关搜索模块
2. 在任何调用向量搜索的地方（memory_tier 等）前置净化
3. 加日志记录哪些 query 被净化、用了哪种方法，建立基线

---

#### P0.2 文件级锁（mine_lock）防并发重复

**描述**：多个 agent 同时 mine 同一文件时，delete+insert 操作序列会交错，产生重复 drawer。MemPalace 用跨平台文件锁解决：

```python
@contextlib.contextmanager
def mine_lock(source_file: str):
    lock_path = os.path.join(lock_dir, sha256(source_file)[:16] + ".lock")
    lf = open(lock_path, "w")
    try:
        if os.name == "nt":
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lf, fcntl.LOCK_EX)
        yield
    finally:
        # 解锁 + 关闭
```

**双重检查**（lock 内再次检查，防止等锁期间另一 agent 已完成）：
```python
with mine_lock(source_file):
    if file_already_mined(collection, source_file, check_mtime=True):
        return 0, room  # 另一 agent 已完成，直接返回
    # ... 正式写入
```

**与 Orchestrator 现状对比**：我们的 hook 系统在多 agent 并发写 memory 时没有协调机制，可能产生竞态写入。

**适配方案**：在任何多 agent 写共享状态（`experiences.jsonl`、`memory/` 文件）的路径加类似的文件锁保护。Windows 兼容版本（msvcrt）对我们的环境特别有用。

---

#### P0.3 原子写 + fsync 持久化模式

**描述**：MemPalace 的所有重要 JSON 文件写入都用原子模式：
```python
def _save_tunnels(tunnels):
    tmp_path = _TUNNEL_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(tunnels, f, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())  # 不支持时静默失败
        except OSError:
            pass
    os.replace(tmp_path, _TUNNEL_FILE)  # 原子替换
```

**与 Orchestrator 现状对比**：我们的 memory 文件写入用普通 `open().write()`，crash 时可能产生半写文件。

**适配方案**：给 `experiences.jsonl`、`identity.md` 等关键 memory 文件写入加原子写保护。尤其是 Stop hook 在对话结束时写入，这个时机最容易被中断。

---

#### P0.4 NORMALIZE_VERSION 模式（无缝 schema 升级）

**描述**：每个存储对象携带 `normalize_version` 字段。系统升级时只需增加版本号，旧版本对象自动被视为 stale，下次运行时静默重建——用户无感知。

```python
NORMALIZE_VERSION = 2  # 版本号

def file_already_mined(collection, source_file, check_mtime=False):
    results = collection.get(where={"source_file": source_file}, limit=1)
    stored_version = stored_meta.get("normalize_version", 1)  # 默认旧版本
    if stored_version < NORMALIZE_VERSION:
        return False  # 触发重建
    # ...
```

**适配方案**：给 `experiences.jsonl` 的每条记录加 `schema_version` 字段。升级 memory 格式时不需要手动迁移，只需增加版本号。

---

### P1 — 需要额外基础设施或工作量

---

#### P1.1 壁橱+抽屉双集合索引架构

**描述**：将内容索引（话题指针）与原文内容分离为两个存储集合。搜索时先命中小文档（壁橱，<1500 字符），再 hydrate 原文（抽屉）。

**适配方案**：
- 为现有的 SOUL memory 文件建立话题指针索引（类 closet 格式）
- 搜索时先扫描话题索引（关键词匹配），再加载对应 md 文件
- 不需要 ChromaDB，用 JSONL 存话题指针即可

**所需工作**：约 1 天，建立 `SOUL/index/closets.jsonl` 和对应的构建/搜索逻辑。

---

#### P1.2 BM25 + 向量混合重排

**描述**：`searcher.py` 的 `_bm25_scores()` + `_hybrid_rank()` 实现了标准 Okapi-BM25，不依赖任何外部库，纯 Python 约 50 行。

```python
def _bm25_scores(query, documents, k1=1.5, b=0.75):
    # 标准 Okapi-BM25
    idf = {term: math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1) 
           for term in query_terms}
    # ...
    return scores  # 与 documents 等长的分数列表

def _hybrid_rank(results, query, vector_weight=0.6, bm25_weight=0.4):
    bm25_norm = normalize(bm25_scores)
    final_score = vector_weight * vec_sim + bm25_weight * bm25_norm
```

**适配方案**：直接复制 `_bm25_scores()` 和 `_hybrid_rank()`，用于现有的任何搜索场景（无需 ChromaDB）。

---

#### P1.3 时态知识图谱（SQLite + valid_from/valid_to）

**描述**：`knowledge_graph.py` 用三张 SQLite 表实现了 Zep 的核心功能：
- 实体节点（entities）
- 时间限定三元组（triples）：`subject → predicate → object`，带 `valid_from` / `valid_to`
- `as_of` 时间点查询："2026-01-15 时 Max 的状态是什么"

```python
kg.add_triple("Max", "child_of", "Alice", valid_from="2015-04-01")
kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
kg.query_entity("Max", as_of="2026-01-15")  # 找到在这个时间点有效的事实
kg.invalidate("Max", "has_issue", "sports_injury", ended="2026-02-15")  # 标记结束
```

**与 Orchestrator 现状对比**：我们的 `memory/` 文件存关系事实，但没有时间维度。一个人换了工作、一个项目关闭了，我们无法记录"这个事实在某时间点失效"。

**适配方案**：在 `SOUL/` 下加 `knowledge_graph.sqlite3`，复制 `knowledge_graph.py`（约 300 行），在 MCP server 中暴露 kg_add/kg_query/kg_invalidate 工具。

---

### P2 — 参考设计，不直接迁移

---

#### P2.1 宫殿隐喻的完整层次结构

Wing→Room→Hall 三级分类系统适用于真正拥有大量多项目记忆的场景。对于 Orchestrator 当前规模（单项目），过于重型。

可学习的是 **Hall 的设计思路**：不是对话题分类，而是对内容类型分类（情感 / 技术 / 家庭 / 身份认同），用来支持跨项目的图遍历（同一"情感"内容跨不同项目相连）。

#### P2.2 AAAK 压缩方言

有意思的尝试，但代码里自己也承认嵌入质量下降（`ALC` vs `Alice`）。对 Orchestrator 没有引入价值——我们的 memory 是结构化文件，不需要自定义压缩格式。

#### P2.3 LLM-driven 壁橱生成

`closet_llm.py` 的设计（bring-your-own LLM，OpenAI-compatible，零强制依赖）很干净。但前提是你需要大量 memory 且 regex 提取质量不够。当前暂时不适用。

---

## 八、执行建议（优先级排序）

| 优先级 | 模式 | 工作量 | 收益 |
|--------|------|--------|------|
| **P0 立刻** | Query 净化器（P0.1） | 0.5 天 | 防止搜索召回率灾难性崩溃 |
| **P0 立刻** | NORMALIZE_VERSION 模式（P0.4） | 2 小时 | 无缝 memory schema 升级 |
| **P0 立刻** | 原子写保护（P0.3） | 2 小时 | 防止 crash 产生半写文件 |
| **P0 立刻** | 文件级锁（P0.2） | 4 小时 | 多 agent 并发写安全 |
| **P1 近期** | BM25 混合重排（P1.2） | 0.5 天 | 提升精确词检索质量 |
| **P1 近期** | 时态知识图谱（P1.3） | 2 天 | 解决事实失效/更新问题 |
| **P1 观察** | 壁橱架构（P1.1） | 1 天 | memory 索引加速 |

---

## 九、总体评估

MemPalace v3.3.0 的工程成熟度显著高于 R44 时的状态。三个核心工程决策值得记录：

1. **"closet 是 boost，不是 gate"**：壁橱只能提升排名，直接向量检索永远是基准。这个设计防止了 regex 提取质量差导致的检索退化。

2. **"verbatim is sacred"**：写入时永不摘要，在上下文窗口里做摘要。代价是存储大，收益是不损失精度。

3. **原文 + 索引分离为两个集合**：drawers 存内容，closets 存指针。搜索先过小文档，再 hydrate 大内容。简单的架构决策带来了明显的检索效率提升。

查询净化器（P0.1）的量化数据（89.8% → 1.0%）是这次偷师最不可替代的知识——没有自己踩到这个坑并量化它，不会意识到问题的严重性。

---

*分析分支：`steal/round-deep-rescan-r60`*
*分析时间：2026-04-14*
