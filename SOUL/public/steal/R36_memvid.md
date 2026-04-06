# R36 — memvid 偷师报告

**来源**: https://github.com/memvid/memvid
**本质**: Rust 单文件 AI 记忆引擎（名字有误导，跟视频无关）
**日期**: 2026-04-06

---

## 一句话

把文档 + embedding + BM25 索引 + HNSW 向量索引 + WAL 全部打包进一个 `.mv2` 文件，像 SQLite 一样零依赖、单文件、可便携。

---

## 核心架构

```
.mv2 文件布局:
Header (4KB) → WAL (1-64MB) → Data Segments → Lex Index → Vec Index → Time Index → TOC (Footer)
```

关键设计决策：
- **单文件铁律** — 没有 `.wal`、`.shm`、`.lock`，用 `ensure_single_file()` 强制
- **内嵌 WAL** — WAL 在文件内部（byte 4096 起），环形缓冲区，75% 触发 checkpoint
- **Footer 扫描恢复** — TOC 写在文件末尾，带 `MV2FOOT!` magic trailer，崩溃时用 `memrchr` 反向扫描找最后一个 hash 校验通过的 footer
- **Frame 不可变** — 一旦 commit 不修改，只能 tombstone，保证 append-only 语义

---

## 偷师清单

### P0 — 直接可偷

| 模式 | 原理 | 怎么适配到 Orchestrator |
|------|------|------------------------|
| **三层搜索漏斗** | SimHash sketch (32B/doc) → BM25 (Tantivy) → HNSW 向量搜索。Sketch 层亚毫秒过滤 90%+ 无关文档 | Construct3-RAG 的检索管线可以加 SimHash 预过滤层，成本极低（每文档 32-96 字节 sketch），在 Qdrant 向量搜索前先砍掉明显不相关的 |
| **自适应检索截断** | 5 种策略：AbsoluteThreshold / RelativeThreshold / ScoreCliff / Elbow / Combined。根据 score 分布动态决定返回数量，不用固定 top_k | RAG 查询用 Elbow detection 或 ScoreCliff 替代硬编码 top_k=5，score 分布平坦时多返回，分布陡峭时少返回 |
| **Doctor 计划-执行分离** | `doctor_plan()` 扫描生成修复计划 → 用户审核 → `doctor_execute()` 执行 | 我们的 /doctor 目前是直接执行。改成两步：先输出诊断报告和修复计划，再执行 |
| **SimHash 实现** | ~30 行核心代码：token BLAKE3 hash → 按 bit 加权累加 → 阈值二值化。Term filter 是 3-hash Bloom filter (128-512 bit) | 可用于 events.db 的快速去重/相似度检测，比完整 embedding 便宜 100x |

### P1 — 值得学习

| 模式 | 原理 | 启发 |
|------|------|------|
| **Atomic Commit** | commit 时 copy 到临时文件 → 修改 → 原子替换。IO 翻倍但 crash-safe | 我们的 SQLite 已经有 WAL，但 JSONL 日志文件可以用这个模式 |
| **锁升降级** | 读操作 Shared lock → 写操作升级 Exclusive → commit 后 downgrade_to_shared() | 多进程访问 events.db 时参考 |
| **Drop 自动 commit** | Rust 的 `Drop` trait 在对象销毁时自动 flush 脏数据 | Python 的 `__del__` 不可靠，但 `atexit` + context manager 可以做类似保障 |
| **PII 查询时 masking** | 原始数据不动保持可搜索，只在发给 LLM 时 regex 替换 | 我们发给 Claude 的上下文可以加 PII masking 层 |
| **规则引擎提取记忆卡** | regex 模式匹配 + capture group 模板做实体提取，不需要 LLM | 采集器的结构化信息提取可以先用 regex 做一遍低成本过滤，只把不确定的交给 LLM |
| **Footer 反向扫描** | 用 `memrchr` 从文件末尾找 magic bytes，比从头扫描快 | append-only 文件（experiences.jsonl）的快速尾部定位 |

### P2 — 知道就好

| 模式 | 说明 |
|------|------|
| 单文件数据库 | 概念很美但我们已经有 SQLite + Qdrant，切换成本太高 |
| 内嵌 WAL | 有趣但实现复杂度高，SQLite 已经做了 |
| HNSW 自动切换 | <1000 暴力搜索，>1000 切 HNSW — Qdrant 已经做了类似的 |
| Product Quantization | 向量压缩，Qdrant 也支持 |

---

## 依赖选型参考

| 依赖 | 用途 | 为什么选它 |
|------|------|-----------|
| blake3 | 哈希 | 比 SHA-256 快 15x，SIMD |
| tantivy | 全文索引 | Rust 原生 Lucene |
| zstd | 压缩 | 高压缩比 + 快速解压 |
| bincode | 序列化 | 零拷贝二进制，比 JSON 快 100x |
| memmap2 | 内存映射 | 大文件不用全加载 |
| memchr | 字节搜索 | SIMD 加速，footer 反向扫描用 |

---

## Chunking 策略

```
DEFAULT_CHUNK_CHARS = 1200
CHUNK_MIN_CHARS = 2400 (低于此不分块)
```

- **结构感知分块** — 检测到 Markdown 表格/代码块时启用，表格在行间切分并传播表头
- **朴素分块** — 句号/段落边界附近切分，slack = chunk_size/5

对比我们的 RAG：C3-RAG 的 chunking 目前是固定 token 数，没有结构感知。表格传播表头这个 trick 值得加。

---

## 核心算法速写

### SimHash (Locality-Sensitive Hashing)
```
for each token in doc:
    h = blake3(token)  # 64-bit hash
    w = tf_idf_weight(token)
    for bit_i in 0..63:
        if h[bit_i] == 1: accumulator[bit_i] += w
        else:             accumulator[bit_i] -= w
fingerprint = [1 if acc > 0 else 0 for acc in accumulator]
```
两个文档的 hamming distance ≈ 余弦距离的近似。32 bytes 搞定。

### Reciprocal Rank Fusion (Hybrid Search)
```
rrf_score(doc) = Σ 1/(k + rank_i)  where k=60
```
把 BM25 排名和向量搜索排名合并成一个分数，简单粗暴但效果好。

### Adaptive Retrieval — Elbow Detection
找 score 曲线的拐点：连续两个 gap 超过 mean_gap * 1.5x 时截断。避免返回一堆低分噪音。
