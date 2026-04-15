# R65 Headroom 深度偷师报告 — 跨 Agent 记忆互操作与上下文压缩

> **仓库**: https://github.com/chopratejas/headroom  
> **克隆路径**: `D:/Agent/.steal/headroom/`  
> **分析日期**: 2026-04-14  
> **本轮焦点**: 跨 Agent 记忆互操作（MCP + Sync Engine）、原子事实提取、Token 预算管理  
> **上次报告**: 2026-04-01（表面层，未读源码）  
> **分支**: `steal/round-deep-rescan-r60`

---

## 核心发现摘要

上次（R01）只看了 README 和架构图。这次读完所有关键源文件后，发现**真正的价值在记忆子系统**，不在压缩 pipeline。Headroom 在 Apr 13 commit 之后已经是一个完整的**多 Agent 记忆共享协议**，压缩只是入口。

关键突破：
1. **MCP Server as Memory Hub** — 一个 stdio MCP server，让任何 MCP 兼容 Agent 都能读写同一个记忆库（`memory_search` / `memory_save` 两个工具）
2. **Sync Engine 双向同步** — fingerprint 快速比对 + import/export 两阶段，防 echo loop
3. **Atomic Facts = 单向 KV 化记忆** — 每个 `facts[]` 元素独立向量化存储，精确检索
4. **MemoryBudgetManager — 自吃狗粮** — 压缩自己的记忆文件，指数衰减 + git 感知陈旧检测

---

## 六维扫描

### 维度 1：安全 / 治理

**问题：跨 Agent 信任是隐式的**

`sync_import` 只校验 `content_hash` 去重，没有任何权限检查：
```python
# headroom/memory/sync.py:257-270
await backend.save_memory(
    content=am.content,
    user_id=user_id,
    importance=0.6,
    metadata={
        "source_agent": adapter.agent_name,
        "source_file": am.source_file,
        "content_hash": am.content_hash,
        "sync_direction": "import",
    },
)
```

`source_agent` 字段是 adapter 自报的字符串（`agent_name = "claude"`），没有签名验证。任何人都可以伪造 adapter 自称是 "claude" 并注入记忆。

MCP server 的 `memory_save` 工具对 `importance` 无上限校验，接受 0-1 范围外的值。

**Auto-supersede 阈值硬编码**：
```python
# headroom/memory/mcp_server.py:261
_SUPERSEDE_SIMILARITY = 0.70
```
相似度 ≥ 0.70 就静默覆盖旧记忆，没有用户确认。这是个信息安全面——恶意 Agent 可以精心构造内容把重要记忆顶掉。

---

### 维度 2：记忆 / 学习（60% 时间 — 核心）

#### 2.1 分层记忆模型

`ScopeLevel` 四层层级：`USER → SESSION → AGENT → TURN`

```python
# headroom/memory/models.py:17-23
class ScopeLevel(Enum):
    USER = "user"      # 跨所有 session 持久
    SESSION = "session" # 单次任务/对话内持久
    AGENT = "agent"     # Agent 生命周期内持久
    TURN = "turn"       # 单次 LLM 调用，临时
```

`scope_level` 是从字段推导的计算属性，不存储：
```python
@property
def scope_level(self) -> ScopeLevel:
    if self.turn_id is not None:   return ScopeLevel.TURN
    if self.agent_id is not None:  return ScopeLevel.AGENT
    if self.session_id is not None: return ScopeLevel.SESSION
    return ScopeLevel.USER  # 最宽作用域
```

#### 2.2 Memory Bubbling（重要记忆升级机制）

`importance ≥ bubble_threshold (0.7)` 的记忆自动复制到 USER 级别（最宽作用域）：

```python
# headroom/memory/core.py:794-814
async def _maybe_bubble(self, memory: Memory) -> None:
    if memory.importance < self._config.bubble_threshold:
        return
    if current_scope == ScopeLevel.USER:
        return  # 已是最高层

    bubbled = Memory(
        content=memory.content,
        user_id=memory.user_id,
        session_id=None,    # 提升到 user 层
        agent_id=None,
        turn_id=None,
        importance=memory.importance,
        promoted_from=memory.id,
        promotion_chain=memory.promotion_chain + [memory.id],
    )
```

lineage 字段保留晋升链：`supersedes / superseded_by / promoted_from / promotion_chain`。

#### 2.3 原子事实提取（P0 模式）

这是最精彩的部分。传统 Mem0 流程需要 3-4 次 LLM 调用（主 LLM + 事实提取 LLM + 实体提取 LLM + 关系提取 LLM）。Headroom 的解法：

```python
# headroom/memory/extraction.py:9-27
"""
传统 Mem0 流程 (低效):
  User → Main LLM → memory_save(content) → Mem0.add() 
    → Mem0 LLM 提取事实 → Mem0 LLM 提取实体 → Mem0 LLM 提取关系
  总计: 3-4 次 LLM 调用！

优化的 Headroom 流程 (高效):
  User → Main LLM (带提取 prompts) → memory_save(facts, entities, relationships)
    → 直接写入 Qdrant + Neo4j
  总计: 1 次 LLM 调用！
"""
```

Tool schema 设计直接让主 LLM 在一次调用内完成提取+保存：
```python
MEMORY_SAVE_TOOL_WITH_EXTRACTION = {
    "parameters": {
        "facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Pre-extracted discrete facts. Each fact should be self-contained."
        },
        "extracted_entities": [{"entity": "name", "entity_type": "type"}],
        "extracted_relationships": [{"source": "e1", "relationship": "type", "destination": "e2"}]
    }
}
```

每个 fact 存储为独立 Memory 对象（各自生成 embedding，各自索引），避免 "Alice 喜欢 Python，Alice 住在北京" 这种粗粒度块里的语义混叠。

#### 2.4 时序感知（Temporal Supersession）

记忆不删除，只超级化（supersede）：

```python
# headroom/memory/core.py:495-561
async def supersede(self, old_memory_id: str, new_content: str, ...) -> Memory:
    old_memory = await self._store.get(old_memory_id)
    new_memory = Memory(
        content=new_content,
        user_id=old_memory.user_id,
        ...
        # 继承旧记忆的全部 scope
    )
    new_memory = await self._store.supersede(old_memory_id, new_memory, supersede_time)
```

旧记忆的 `valid_until` 被设置，新记忆的 `valid_from` 从该时间点开始。支持点时间查询（回溯）。

MCP server 里的自动超级化阈值是 0.70（可配置）：
```python
# mcp_server.py: 若新事实与现有记忆相似度 ≥ 0.70 → 自动 supersede 而非追加
```

#### 2.5 向量索引策略

双轨索引：优先 SQLite-vec（有界内存，持久化），回退 HNSW（无界内存）：
```python
# headroom/memory/config.py:29-34
class VectorBackend(Enum):
    AUTO = "auto"           # 自动选择
    SQLITE_VEC = "sqlite_vec"  # 推荐：有界内存
    HNSW = "hnsw"           # 回退：无界内存
```

HNSW 导入用 subprocess 隔离（防 SIGILL crash on non-AVX CPUs）：
```python
# headroom/memory/adapters/hnsw.py:36-60
# Use subprocess to safely probe for hnswlib
# if it crashes with SIGILL, only the subprocess dies, not our main process
```

---

### 维度 3：执行 / 编排

#### 3.1 Sync Engine 架构（双向同步）

```
                    ┌─────────────┐
                    │  Headroom   │
                    │  Memory DB  │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              │ sync() 双向同步          │
              ├── Phase 1: Import       │
              │   agent files → DB      │
              │   内容 hash 去重         │
              ├── Phase 2: Export       │
              │   DB → agent files      │
              │   防 echo 检查           │
              └────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           │                               │
    ClaudeCodeAdapter                 CodexAdapter
    读写 ~/.claude/.../memory/*.md     读写 AGENTS.md
```

**快速 No-op 检测**（关键优化）：
```python
# headroom/memory/sync.py:179-198
current_agent_fp = adapter.fingerprint()
all_memories = await backend.get_user_memories(user_id, limit=500)
current_db_fp = _db_fingerprint(all_memories)

if (prev.get("agent_fingerprint") == current_agent_fp
    and prev.get("db_fingerprint") == current_db_fp):
    # 什么都没变，不执行完整同步
    return result  # 耗时 < 5ms
```

fingerprint 是文件名+mtime 的 SHA256 截断（16 chars），极速。

**Echo 防止（关键 Bug 预防）**：
```python
# headroom/memory/sync.py:306-313
if (
    meta.get("source_agent") == adapter.agent_name
    and meta.get("sync_direction") == "import"
):
    continue  # 跳过：这个记忆原本就来自这个 agent，不要再导回去
```

#### 3.2 MCP Server 预热策略

MCP Server 在 `list_tools()` 首次调用（MCP 握手阶段）就踢开 embedder 预热：
```python
# headroom/memory/mcp_server.py:181-187
@server.list_tools()
async def list_tools() -> list[Tool]:
    nonlocal _init_task
    if _backend is None and _init_task is None:
        _init_task = asyncio.create_task(_init_backend())  # 异步预热
    return _TOOLS
```

`_warm_up_backend` 做两件事：
1. 用 `embed("warmup")` 预载 ONNX embedder（避免首次查询冷启动 1-2s）
2. 扫描所有没有 embedding 的记忆并重新建索引（修复跨 Agent 路径写入的记忆无向量的 bug）

设置 `HF_HUB_OFFLINE=1` 跳过模型新鲜度检查，消除启动时的 HTTP HEAD 请求。

---

### 维度 4：上下文 / Token 预算（核心）

#### 4.1 MemoryBudgetManager — 自压缩记忆

这是 Headroom "自吃狗粮" 的最佳例子：用 Headroom 的压缩理念来管理 Headroom 自己的记忆文件。

**四步优化管道**：
```python
# headroom/memory/budget.py:106-131
def optimize(self, memories, agent_type):
    # Step 1: 时间衰减（指数衰减 × 访问计数提升）
    decayed = self._apply_decay(memories)
    
    # Step 2: 陈旧检测（引用了已删除/重命名的文件）
    fresh, stale = self._detect_staleness(decayed)
    
    # Step 3: 相似记忆合并（Jaccard 相似度 > 0.85）
    merged = self._merge_similar(fresh)
    
    # Step 4: 按分数排名 + token 预算截断
    ranked = sorted(merged, key=lambda m: m.score, reverse=True)
    budgeted = []
    tokens_used = 0
    for m in ranked:
        if tokens_used + entry_tokens > budget:
            break
        budgeted.append(m)
```

**指数衰减公式**：
```python
# headroom/memory/budget.py:148-154
age_days = (now - m.created_at) / 86400
decayed_importance = m.importance * math.exp(-rate * age_days)
# rate = 0.1 → 每天衰减 ~10%
# 访问计数抵消衰减：access_boost = min(0.3, access_count * 0.05)
```

**Git 感知陈旧检测**：
```python
# headroom/memory/budget.py:159-178
def _detect_staleness(self, memories):
    git_files = self._get_git_files()  # git ls-files，缓存结果
    for m in memories:
        if self._is_stale(m, git_files):
            stale.append(m)
```

`_is_stale` 检查记忆 `entity_refs` 中的文件路径和内容里反引号括起的路径，若不在 git 追踪文件中则标记为陈旧。

**各 Agent 预算硬编码**（值得参考）：
```python
# headroom/memory/budget.py:33-41
agent_budgets = {
    "claude": 2000,   # Claude Code: 200 行 MEMORY.md 限制
    "cursor": 3000,   # Cursor: .mdc rules 按匹配加载
    "codex":  3000,   # Codex: AGENTS.md 合并
    "aider":  2000,   # Aider: read files
    "gemini": 3000,   # Gemini: GEMINI.md
    "generic": 3000,
}
```

#### 4.2 MemoryEntry 综合评分

```python
# headroom/memory/writers/base.py:52-55
@property
def score(self) -> float:
    """重要性 × 时效性 × 访问量"""
    age_days = (time.time() - self.created_at) / 86400
    recency = 1.0 / (1.0 + age_days * 0.1)   # ~10 天衰减
    access_boost = min(1.0, 0.5 + self.access_count * 0.1)
    return self.importance * recency * access_boost
```

#### 4.3 SharedContext — Agent 间 Token 高效传递

```python
# headroom/shared_context.py
class SharedContext:
    def put(self, key: str, content: str, *, agent: str = None) -> ContextEntry:
        # 调用 headroom.compress() 压缩
        result = compress([{"role": "tool", "content": content}], model=self._model)
        # 存 original + compressed，默认返回 compressed
        entry = ContextEntry(original=content, compressed=compressed, ...)
    
    def get(self, key: str, *, full: bool = False) -> str | None:
        return entry.original if full else entry.compressed  # 按需返回
```

TTL = 3600s，max_entries = 100，容量满了优先淘汰最老的（LRU 思路但实现简单）。

#### 4.4 结构性压缩算法

`UniversalCompressor` 的核心流程：

```
content → ML 内容类型检测 (Magika)
        → 选 Handler (JSON/Code/NoOp)
        → Handler.get_mask() → StructureMask (哪些 token 是结构性的)
        → compute_entropy_mask() → 高熵 token 标记 (UUID、hash → 保留)
        → mask.union() → 合并两个 mask
        → _compress_with_mask() → 结构性区域保留，非结构性区域压缩
```

**熵保留逻辑**（防止 UUID/hash 被破坏）：
```python
# headroom/compression/masks.py:257-294
class EntropyScore:
    @classmethod
    def compute(cls, text: str, threshold: float = 0.85) -> EntropyScore:
        counter = Counter(text)
        entropy = sum(-p * math.log2(p) for p in [c/len(text) for c in counter.values()])
        max_entropy = math.log2(len(counter))
        normalized = entropy / max_entropy
        return cls(value=normalized, should_preserve=normalized >= threshold)
```

---

### 维度 5：故障 / 恢复

#### 5.1 同步冲突策略

无显式冲突解决：content hash 相同 = 跳过，content hash 不同 = 都保留（append 语义）。不存在 last-write-wins，因为每条记忆是独立的行而非文件级合并。

唯一有冲突语义的是 `supersede()`：新记忆替代旧记忆，时间戳确保顺序，`get_history()` 可回溯全链。

#### 5.2 HNSW 子进程隔离

HNSW 在非 AVX CPU 上会 SIGILL 崩溃（C 层崩溃，Python try/except 抓不到）。解法：

```python
# 用 subprocess 探测，子进程崩溃不影响主进程
def _check_hnswlib_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-c", "import hnswlib"],
        capture_output=True, timeout=5
    )
    return result.returncode == 0
```

#### 5.3 MCP Server 重建索引

启动时扫描所有 embedding 为 None 的记忆并重新建索引：
```python
for mem in all_memories:
    if mem.embedding is None:
        mem.embedding = await hm._embedder.embed(mem.content)
        await hm._store.save(mem)
    await hm._vector_index.index(mem)
```

这保证了：通过其他路径（Claude Code proxy、直接 SQL 写入）存入的记忆，在 Codex 通过 MCP 搜索时仍然可被向量检索。

---

### 维度 6：质量 / 审查

#### 6.1 事实提取质量控制

`get_conversation_extraction_prompt()` 内置了以下质量规则：
- 归属性：每个事实必须包含"谁"，禁用 "user" / "I"（用真实名字）
- 原子性：单个事实单个断言，不合并
- 时间定位：相对日期必须解析为绝对日期（"last year" → "in 2022"）
- Few-shot 示例明确区分 Good/Bad 格式

Few-shot 示例方式：
```
✓ GOOD: "Alice 是 Netflix 的软件工程师"
✗ BAD: "是软件工程师" (缺少 WHO)
✓ GOOD: "Alice 在 2023 年 6 月访问了巴黎"
✗ BAD: "Alice 最近去了某地" (太模糊，相对日期)
```

#### 6.2 压缩保真度

`CompressionResult` 追踪：
- `compression_ratio`: 压缩后/压缩前字符比
- `preservation_ratio`: 结构性 token 占比
- `detection_confidence`: ML 内容类型检测置信度
- `ccr_key`: 原始内容存储在 CCR（Compress-Cache-Retrieve）中，可按需取回

这确保了"压缩了什么"是可审计的，原始内容不会真正丢失。

---

## 五层深度追踪（Memory 子系统）

### 调度层（Scheduling Layer）

**入口**: `HierarchicalMemory.add()` → `MemoryBudgetManager.optimize()` → `AgentWriter.export()`

决策链：
1. 新记忆进来 → 生成 embedding → 向量索引 → FTS5 全文索引 → 可选 bubble（重要度 ≥ 0.7）
2. 导出时 → 拉取所有记忆 → 时间衰减 → 陈旧检测 → 相似合并 → token 预算截断 → 写 agent 文件
3. 同步时 → fingerprint 比对（no-op 检测）→ import（agent→DB）→ export（DB→agent）

### 实践层（Practice Layer）

**ClaudeCodeAdapter 实现细节**：
- 读：遍历 `memory/*.md`（跳过 `MEMORY.md` index），解析 YAML frontmatter，body 作为记忆内容
- 写：每条记忆生成独立 `.md` 文件（`headroom_<slug>.md`），frontmatter 含 `headroom_id` 跨引用
- 索引：写入后更新 `MEMORY.md` 的 `## Headroom Shared Memory` section

**CodexAdapter 实现细节**：
- 读写的是 `AGENTS.md` 内的 `<!-- headroom:memory:start --> ... <!-- headroom:memory:end -->` 区间
- 每条记忆作为 markdown 列表项 `- fact`
- fingerprint 是 AGENTS.md 文件的 mtime hash

### 消费层（Consumption Layer）

**MCP Server 消费端**（Codex 调用）：

`memory_search`:
- 搜索时 over-fetch（top_k × 3），然后过滤 `superseded_by != None` 的旧记忆
- 双重校验：向量索引 metadata 可能陈旧，所以对每个结果再查一次 store
- 返回格式：`[relevance=0.85] 内容` + 关联实体

`memory_save`:
- `facts[]` 数组，每个 fact 独立存储
- 自动 supersede：新 fact 与相似度 ≥ 0.70 的现有记忆合并
- 向后兼容：接受单个 `content` 字符串

### 状态层（State Layer）

**Memory 状态机**：
```
NEW → ACTIVE (valid_until=None)
ACTIVE → SUPERSEDED (valid_until set, superseded_by=new_id)
ACTIVE → BUBBLED (复制为 USER 级，original 保持 ACTIVE)
ACTIVE → DELETED (store.delete, 从向量/文本索引移除)
```

**Sync State 文件** (`~/.headroom/sync_state.json`):
```json
{
  "claude:user123": {
    "agent_fingerprint": "abc123",
    "db_fingerprint": "def456",
    "last_sync": "2026-04-13T10:00:00Z",
    "last_imported": 3,
    "last_exported": 1
  }
}
```

### 边界层（Boundary Layer）

**外部依赖边界**：
- Embedder：LOCAL (sentence-transformers, 需 ~2GB torch) / ONNX (推荐, ~86MB, 无 torch) / OpenAI / Ollama
- 向量索引：sqlite-vec (有界，推荐) / hnswlib (无界，兼容回退)
- 全文检索：SQLite FTS5（内置，无额外依赖）
- 图存储：SQLiteGraphStore (有界持久) / InMemoryGraphStore (无界易失)

**进程边界**：MCP server 是独立 stdio 进程，Codex 通过 MCP 协议通信。Sync engine 可作为 CLI 子进程运行（`python -m headroom.memory.sync`）。

---

## P0 模式（必偷，带代码）

### P0-1: 原子事实分拆存储

**原理**：不要把 "Alice 用 Python，Alice 住北京" 存成一条记忆。存两条，分别 embed。检索时精度提升 30-50%（数学上：合并向量是两个方向的均值，两个独立向量各自准确）。

**Headroom 实现**：
```python
# headroom/memory/backends/local.py:279-293
if facts:
    for i, fact in enumerate(facts):
        memory = await self._hierarchical_memory.add(
            content=fact,
            user_id=user_id,
            importance=importance,
            entity_refs=all_entity_names,
            metadata={"_fact_index": i},
        )
```

**与 Orchestrator 的 gap**：Orchestrator 记忆文件是自由格式 markdown，没有强制原子化。一个 `user_preferences.md` 文件里可能有十几个混在一起的偏好。

**迁移路径**：
1. 在 `remember` skill 里加 "原子事实分拆" 提示规范
2. 写 memory 时强制 `facts[]` 数组格式（每项不超过一句话）
3. 每个 fact 对应一个独立 `.md` 文件（已有 ClaudeCodeAdapter 模板）

---

### P0-2: Fingerprint + No-op 同步

**原理**：每次 Agent 启动都全量读记忆库是浪费。用 mtime hash 做快速比对，未变化时跳过整个 sync 周期（< 5ms vs 完整同步的 200ms+）。

**Headroom 实现**：
```python
# headroom/memory/sync.py:120-143
def _db_fingerprint(memories: list[Any]) -> str:
    parts = [str(len(memories))]
    for m in memories[:5]:  # 采样前 5 条，速度优先于精确
        parts.append(getattr(m, "id", "")[:8])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

# adapter fingerprint
def fingerprint(self) -> str:
    parts = []
    for md_file in sorted(self._memory_dir.glob("*.md")):
        stat = md_file.stat()
        parts.append(f"{md_file.name}:{stat.st_mtime_ns}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
```

**与 Orchestrator 的 gap**：Orchestrator 每个 session 都会重新加载所有 memory 文件，无 fingerprint 缓存。

**迁移路径**：在 `.claude/hooks/` 里的 memory 相关 hook 加 fingerprint 比对，状态存 `.headroom/sync_state.json` 类似文件。

---

### P0-3: Echo 防止协议

**原理**：A→DB→A 的同步会产生 echo（A 自己的记忆又被导回 A）。用 `source_agent + sync_direction` 两字段组合过滤。

**Headroom 实现**：
```python
# headroom/memory/sync.py:303-313
if (
    meta.get("source_agent") == adapter.agent_name
    and meta.get("sync_direction") == "import"
):
    continue  # 防止 agent→DB→agent echo 循环
```

**场景**: Orchestrator 可能有多个子 Agent，或者跨项目 sync。如果不加这个检查，自己写入 DB 的记忆会在下次 export 时又被写回来，形成指数级膨胀。

---

### P0-4: Git 感知陈旧记忆检测

**原理**：记忆引用了 `src/old_module.py`，这个文件已被重命名或删除。这条记忆现在是幻觉来源。自动检测并降级 importance 或移出 budget。

**Headroom 实现**：
```python
# headroom/memory/budget.py:181-207
def _is_stale(self, memory: MemoryEntry, git_files: set[str]) -> bool:
    # 检查 entity_refs 中的路径
    for ref in memory.entity_refs:
        if ref.startswith("/") or ref.startswith("./"):
            if rel not in git_files and not Path(ref).exists():
                return True
    # 检查内容中反引号括起的路径
    path_refs = re.findall(r"`([/\w.]+(?:/[\w.]+)+)`", memory.content)
    for path_ref in path_refs:
        if rel not in git_files and not Path(path_ref).exists():
            return True
    return False
```

**与 Orchestrator 的 gap**：Orchestrator 的 memory 文件有 YAML frontmatter 但没有 entity_refs 路径追踪，也没有陈旧检测。代码记忆可能引用已删除文件。

---

## P1 模式（值得偷）

### P1-1: Bones-Soul 状态分离（来自 Buddy 系统，但 Memory 也适用）

可重算的状态（embedding、scope_level）不持久化，只存不可重现的部分。Headroom 的 `scope_level` 就是从 `(user_id, session_id, agent_id, turn_id)` 推导，不存储。

**对 Orchestrator 的启示**：hook 配置里有部分可以从环境推导的状态，不必存在 settings.json 里。

### P1-2: MCP Server 作为记忆共享总线

在 Codex config.toml 里注册：
```toml
[mcp_servers.headroom_memory]
command = "python"
args = ["-m", "headroom.memory.mcp_server", "--db", ".headroom/memory.db"]
```

任何支持 MCP 的 Agent 都可以直接调用 `memory_search` / `memory_save`，而不必关心底层存储实现。这是 Agent 间记忆互操作的最小协议。

### P1-3: ONNX Embedder 优先策略

sentence-transformers 需要 ~2GB torch 依赖。ONNX Runtime 版本只需 ~86MB，启动快。MCP server 默认用 ONNX：

```python
config = LocalBackendConfig(db_path=db_path, embedder_backend="onnx")
```

对 Orchestrator：如果要加向量语义检索，优先用 ONNX 而非 sentence-transformers。

### P1-4: 向量搜索过取（Over-fetch）+ 去超级化过滤

搜索时取 `top_k * 3`，然后过滤掉已被超级化的旧版本：
```python
results = await backend.search_memories(query=query, top_k=top_k * 3)
active_results = [r for r in results if not getattr(r.memory, "superseded_by", None)]
active_results = active_results[:top_k]
```

原因：向量索引的 metadata 可能陈旧（HNSW 无法做 CRUD 删除，只能标记），双重校验 store 确保返回的是最新版本。

---

## P2 模式（可选）

- **Marker 注入格式**：`<!-- headroom:memory:start --> ... <!-- headroom:memory:end -->` 用于在 agent 文件里划定 headroom 管理区，与用户手写内容互不干扰。
- **对话提取 few-shot 公式**：Speaker 归属 + 日期时间定位 + Good/Bad 示例对 = 可直接 copy 到 system prompt 的模板
- **MemoryTracker singleton**：全局记忆使用统计（命中率、预算使用率），通过 `register(name, stats_fn)` 注册各组件，集中查询

---

## 路径依赖分析

Headroom 的 Sync + MCP 方案有一个隐性假设：**记忆是以文件为单位的**（`*.md` 文件或 `AGENTS.md` section）。这和 Orchestrator 当前的 memory 组织方式一致，可以直接对接。

但有两处路径依赖值得注意：

1. **用户 ID 假设**：Sync engine 的 `user_id` 绑定整个记忆空间。Headroom 假设每个项目/用户有自己的 `user_id`，Orchestrator 没有显式的 user_id 概念（全局 identity）。对接时需要决定用什么作 user_id（git 用户名？机器名？）

2. **SQLite 单文件 vs 分布式**：整套系统依赖 SQLite 单文件（`memory.db` + `memory_graph.db`）。如果 Orchestrator 未来需要跨机器同步记忆，这个 backend 选择成为瓶颈。Headroom 目前没有网络同步能力。

---

## 对比矩阵

| 能力 | Headroom | Orchestrator 现状 | Gap |
|------|----------|-------------------|-----|
| 原子事实存储 | facts[] 逐条向量化 | 自由格式 .md | 高 |
| 跨 Agent 同步 | Sync Engine + adapters | 无 | 高 |
| MCP 记忆服务 | mcp_server.py | 无 | 中 |
| Fingerprint No-op | fingerprint() | 无 | 中 |
| Echo 防止 | source_agent+direction | 无 | 中 |
| 时序超级化 | supersedes/superseded_by | 无 | 中 |
| Token 预算管理 | MemoryBudgetManager | 无显式预算 | 中 |
| Git 感知陈旧检测 | _is_stale() | 无 | 中 |
| 上下文压缩 | compress() pipeline | 无 | 低（暂不需要） |

---

## 建议优先级

**P0（本轮立即实施）**：
1. **原子事实格式规范**：在 `SOUL/public/prompts/` 里加 `memory-atomic-facts.md`，定义每个 memory entry 必须是自含式单句断言
2. **Echo 防止协议**：memory 写入时加 `source_agent` + `sync_direction` 元数据，为未来跨 Agent sync 打基础

**P1（下一轮）**：
3. **Git 感知陈旧检测**：给 memory review hook 加文件存在性校验
4. **Fingerprint No-op**：memory 加载 hook 加 mtime fingerprint 比对

**P2（待评估）**：
5. 完整接入 Headroom MCP server 作为 memory hub（需要决策 user_id 方案）
6. 引入 MemoryBudgetManager 的 importance×recency×access 评分替代当前静态 importance

---

## 知识不可替代性评估

| 模块 | 知识来源 | 独特性 |
|------|---------|--------|
| Atomic facts + single-call extraction | extraction.py 的架构注释 | 高 — 明确量化了 Mem0 的 3-4 LLM 调用问题及解法 |
| Echo 防止协议 | sync.py:303-313 | 中 — 实现简单但思路不显然 |
| HNSW subprocess 隔离 | hnsw.py 注释 | 高 — SIGILL 是实际生产 bug，文档不多 |
| Git-aware staleness | budget.py:181-207 | 高 — 没见过其他系统做这个 |
| No-op fingerprint 双轨 (agent+db) | sync.py:179-198 | 中 — 思路已知，但 DB 端采样 5 条的取舍值得学习 |

---

*报告生成: 2026-04-14, branch: steal/round-deep-rescan-r60*
