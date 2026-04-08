# R45c — graphify Steal Report

**Source**: https://github.com/safishamsi/graphify | **Stars**: 8,250 | **License**: MIT
**Date**: 2026-04-08 | **Category**: Module (Knowledge Graph as Claude Code Skill)

## TL;DR

把任意文件夹变成可查询的知识图谱——核心不在"图"本身，而在 **置信度溯源** 和 **成本分层处理**。每条边都带 EXTRACTED/INFERRED/AMBIGUOUS 标签，代码变更走 tree-sitter 零成本重建，文档变更才触发 LLM。这套"诚实数据 + 分层缓存"哲学直接适用于 MemPalace。

## Architecture Overview

```
detect() → extract() → build() → cluster() → analyze() → report() → export()
   │           │           │          │           │           │          │
   │     ┌─────┴─────┐    │    Leiden/Louvain   │     GRAPH_REPORT.md   │
   │     │  AST      │    │    + auto-split     │     + wiki/          │
   │     │(tree-sitter│   nx.Graph  oversized    │       index.md       │
   │     │ 20 langs) │    │    communities      │                      │
   │     │           │    │                      │              HTML/JSON/SVG
   │     │ Semantic   │    │                     │              GraphML/Obsidian
   │     │(Claude LLM)│   │                     │              Neo4j Cypher
   │     └───────────┘    │                     │
   │           │          │                     │
   │      cache.py        │              analyze.py
   │    SHA256 content    │           god_nodes()
   │    + semantic split  │           surprising_connections()
   │                      │           suggest_questions()
   │                      │           graph_diff()
   │
detect.py                serve.py (MCP stdio, 7 tools)
 .graphifyignore          watch.py (code: instant AST, doc: flag-only)
 sensitive file filter    hooks.py (git post-commit/post-checkout)
 paper heuristic (3+/11)  security.py (SSRF/redirect/path/label sanitize)
```

**核心设计选择**：
- **Pipeline-as-Functions**：每个阶段 = 一个文件的一个函数，输入 dict 输出 dict/nx.Graph，零共享状态
- **无向图 + 方向保留**：NetworkX undirected graph 做结构分析，`_src`/`_tgt` 属性保留原始方向供展示
- **三层去重**：文件内 (seen_ids) → 文件间 (add_node 幂等) → 语义合并 (explicit seen set)

## Six-Dimensional Scan

| Dimension | Findings |
|-----------|----------|
| **Security / Governance** | ✅ SSRF 防护（私有 IP + 云 metadata 端点拦截）、重定向逐跳验证、response body 硬上限 50MB/10MB、标签 XSS 消毒（控制字符 + HTML escape + 256 char cap）、路径遍历防护（resolve + relative_to 校验）、敏感文件正则过滤（.env/.pem/credentials 等 7 类）|
| **Memory / Learning** | ✅ SHA256 内容哈希缓存（文件内容+路径，防碰撞）、AST/语义双层缓存分离、增量 manifest（mtime 对比）、wiki 导出（index.md + 社区文章 + god node 文章）作为持久化知识载体 |
| **Execution / Orchestration** | ✅ Pipeline 线性流水线、watch mode 分层触发（代码即时/文档标记）、git hook 集成（marker 注释干净装卸）、增量模式（detect_incremental + graph_diff）|
| **Context / Budget** | ✅ token_budget 参数贯穿 MCP 查询（3 chars/token 近似、subgraph 截断）、corpus 健康检查（<50K words 警告不需要图、>500K words 警告成本）、benchmark 工具量化压缩比 |
| **Failure / Recovery** | ⚠️ 偏弱——watch rebuild 失败只 print 不重试、validate.py 分离"真错误"和"悬挂边"但无重试/回退机制、无 checkpoint（失败 = 从头来）|
| **Quality / Review** | ✅ 置信度三级标签（EXTRACTED/INFERRED/AMBIGUOUS）、surprise scoring 多因子排序（5 维度 + why 字段）、suggest_questions 从图结构生成审查问题、cohesion score 检测低内聚社区、report 明确标出 Ambiguous Edges + Knowledge Gaps |

## Steal Sheet

### P0 — Must Steal (3 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Confidence-Tagged Relationships** | 每条边必带 `EXTRACTED\|INFERRED\|AMBIGUOUS`，validate.py 硬性校验 | knowledge_graph.py 有时序三元组但**无置信度标签**；memory 有 evidence tier 但仅在记忆本身，不在关系上 | 给 knowledge_graph.py 的 `add_fact()` 和 qdrant_store 的边关系加 confidence 字段；dedup.py 合并时保留高置信度 | ~2h |
| **Surprise Scoring for Non-Obvious Patterns** | 5 因子评分（置信度权重 + 跨类型 + 跨仓库 + 跨社区 + 外围→枢纽），每条 surprise 附带 `why` 可读解释 | profile_analyst 输出 blind_spots 但靠 LLM 自由发挥，无系统性评分 | 在 profile_analyst 加 surprise_score()：跨时段（深夜 vs 白天）、跨项目（A 项目行为出现在 B）、低频→高频突变，每条附 why | ~3h |
| **Content-Hash Incremental Cache** | SHA256(content + path) 跳过未变文件，AST 缓存和语义缓存分离，`--update` 只处理 diff | qdrant_store 每次 consolidation 全量重处理；memory_stack 无内容哈希 | memory consolidation 加 content_hash：hash(text + source) → skip if unchanged；分离"结构变更"（标签/分类）和"内容变更"（正文改写） | ~2h |

### P1 — Worth Doing (5 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Extraction Schema + Hard Validation Gate** | validate.py 强制 `{nodes: [{id, label, file_type, source_file}], edges: [{source, target, relation, confidence, source_file}]}`，构建前校验 | agent 输出（profile_analyst / department blueprints）加 JSON Schema 硬校验，不合规直接拒绝入库而非静默接受 | ~3h |
| **Wiki Export for Agent Navigation** | index.md + 按社区/god-node 生成 [[wikilink]] 文章，agent 先读 index 再按需展开 | SOUL 系统生成 wiki/index.md：按 domain 列出记忆集群摘要，agent 读 index 决定加载哪个层级，替代全量 boot.md | ~4h |
| **MCP Server for Memory Graph** | 7 tools（query_graph/get_node/get_neighbors/get_community/god_nodes/graph_stats/shortest_path），BFS/DFS + token budget 截断 | 把 Qdrant + knowledge_graph 封装成 MCP server，外部 agent 可查询 Orchestrator 的记忆图谱 | ~6h |
| **Watch Mode: Cost-Tiered Trigger** | 代码变更 → tree-sitter 即时重建（零 LLM 成本）；文档变更 → 写 flag 等用户确认 | collector pipeline 区分"结构变更"（配置/代码→自动处理）和"语义变更"（用户文本→排队等 LLM） | ~3h |
| **Graph Diff for Change Tracking** | `graph_diff(G_old, G_new)` → new/removed nodes+edges + summary 一句话 | knowledge_graph 已有时序标记，加 `diff_since(timestamp)` 返回结构化变更摘要 | ~2h |

### P2 — Reference Only (4 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Leiden Community Detection** | graspologic Leiden + Louvain fallback，自动拆分 >25% 的超大社区 | 我们的记忆聚类用 hot/warm/cold + domain tag，结构不同；Leiden 适合图上聚类但我们的记忆图还不够密 |
| **Git Hook Marker Install/Uninstall** | `# graphify-hook-start` / `# graphify-hook-end` 标记注释，append 而非覆盖已有 hook | 我们用 Claude Code hooks（JSON 配置），不是 git hooks；但 marker 模式在需要时可参考 |
| **Token Reduction Benchmark** | 5 个样例问题 × BFS 子图 token vs 全量 corpus token，输出压缩比 | 有趣的度量方式，但我们的 memory_stack 4 层已有隐式压缩，需要时可照搬 benchmark 逻辑 |
| **Paper Detection Heuristic** | 11 个学术信号正则（arxiv/doi/abstract/\cite{}/等），≥3 命中判定为论文 | 我们的 collector 不处理学术论文；如果未来加论文采集可参考 |

## Comparison Matrix (P0 Patterns)

### Confidence-Tagged Relationships

| Capability | graphify | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| Edge confidence label | EXTRACTED/INFERRED/AMBIGUOUS 三级 | knowledge_graph.py: **无** | Large | **Steal** |
| Memory-level evidence | N/A | verbatim/artifact/impression 三级 | None (我们更好) | Keep |
| Validation before storage | validate.py 硬校验 confidence ∈ valid set | output_validator.py 基于 blueprint 但不检查 confidence | Medium | **Enhance** |
| Confidence propagation | 无（每条边独立标记）| 无 | Equal | Skip |

### Surprise Scoring

| Capability | graphify | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| Multi-factor scoring | 5 因子（confidence + type + repo + community + degree） | profile_analyst: LLM 自由输出 blind_spots | Large | **Steal** |
| Explainable "why" | 每条 surprise 附 reasons list | blind_spots 有 evidence 字段但格式不统一 | Medium | **Steal** |
| Cross-domain detection | code↔paper, different top-level dir | 无系统性跨项目关联 | Large | **Steal** |
| Community bridge detection | edge betweenness + community pair dedup | 无 | Large | **Steal** |

### Content-Hash Incremental Cache

| Capability | graphify | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| File content hash | SHA256(content + resolved path) | 无（全量重处理）| Large | **Steal** |
| AST/Semantic cache split | 代码用 AST cache，文档用语义 cache | 无分层 | Medium | **Steal** |
| Incremental manifest | mtime diff → only changed files | redis_cache 有 TTL 但非内容驱动 | Medium | **Steal** |
| Atomic write (tmp → replace) | `os.replace(tmp, entry)` 防崩溃 | 无（直接写入） | Small | **Enhance** |

## Triple Validation Gate (P0 Patterns)

### Confidence-Tagged Relationships

| Check | Pass? | Evidence |
|-------|-------|---------|
| **Cross-domain reproduction** | ✅ | graphify (graph edges), 我们自己的 memory evidence tier (verbatim/artifact/impression), Neo4j best practices (relationship confidence), LangGraph state annotations |
| **Generative power** | ✅ | 给定新场景"agent 从 Telegram 消息推断用户意图"，confidence = INFERRED；"用户直接说了"= EXTRACTED。模式能预测如何标记 |
| **Exclusivity** | ✅ | 不是泛泛的"加个字段"——关键在于 validate.py **硬性拒绝**缺少 confidence 的数据入库，这是门禁而非装饰 |

**Result: 3/3 ✅ — Confirmed P0**

### Surprise Scoring

| Check | Pass? | Evidence |
|-------|-------|---------|
| **Cross-domain reproduction** | ✅ | graphify (graph analysis), Apache Spark anomaly detection (multi-factor scoring), GitHub Copilot "unexpected file changes" alerts |
| **Generative power** | ✅ | 新场景："用户在游戏项目里突然引用了 ML 库"→ cross-type + peripheral→hub → high surprise → 值得报告 |
| **Exclusivity** | ✅ | 不是"找异常"泛模式——具体的 5 因子权重组合 + 强制 why 字段 + community pair dedup 防 god node 刷屏 |

**Result: 3/3 ✅ — Confirmed P0**

### Content-Hash Incremental Cache

| Check | Pass? | Evidence |
|-------|-------|---------|
| **Cross-domain reproduction** | ✅ | graphify, git (SHA-1 content addressing), Docker layers (content-hash caching), Bazel/Buck (content-based invalidation) |
| **Generative power** | ✅ | "用户编辑了 memory 文件但只改了标签没改正文"→ 内容哈希不变 → skip re-embedding → 省 Qdrant 写入 |
| **Exclusivity** | ⚠️ | Content hashing 是通用模式；但 **AST/语义分离** 是 graphify 独有的洞察——区分"可廉价重算"和"需 LLM 的昂贵操作" |

**Result: 2/3 (exclusivity partial) — P0 with caveat: 价值不在 hash 本身而在分层策略**

## Knowledge Irreplaceability Assessment

| Pattern | Pitfall Memory | Judgment Heuristics | Relationship Graph | Hidden Context | Failure Memory | Unique Behavioral | Score |
|---------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Confidence-Tagged Relationships | | ✅ "AMBIGUOUS 比 INFERRED 更值得 surprise" | | ✅ validate.py 硬拒 vs 软日志的选择 | | ✅ 反转直觉：不确定的连接比确定的更有信息量 | 3/6 → P0 |
| Surprise Scoring | | ✅ 5 因子权重是调参经验 | | ✅ community pair dedup 防刷屏（不写不知道） | | ✅ 低度节点→高度节点的连接最"惊奇" | 3/6 → P0 |
| Content-Hash Cache | ✅ "path 必须加入 hash 否则同内容不同文件碰撞" | ✅ AST 廉价 vs LLM 昂贵的分层判断 | | ✅ `os.replace` 原子写防崩溃 | | | 3/6 → P0 |

## Gaps Identified

| Dimension | Gap | Severity |
|-----------|-----|----------|
| **Memory** | 记忆间关系没有置信度标签，全部等权处理 | High — 直接影响记忆质量判断 |
| **Quality** | profile_analyst 的 blind_spots 靠 LLM 直觉，无系统性 surprise 评分 | Medium — 产出质量不稳定 |
| **Context** | memory consolidation 全量重处理，无内容哈希跳过机制 | Medium — 浪费嵌入计算 |
| **Execution** | 无 wiki-style 导航层，agent 要么全量加载要么盲查 | Low — L0-L3 分层已部分缓解 |
| **Failure** | graphify 本身也弱——但提醒我们：Qdrant 写入失败时无原子保护 | Low |

## Adjacent Discoveries

- **graspologic**: Microsoft 出品的 Python 图统计库，Leiden 算法实现。如果未来 MemPalace 需要自动聚类，可直接用
- **tree-sitter multi-language**: graphify 用 LanguageConfig dataclass 统一 20 种语言的 AST 提取。如果 cafi_index 需要更精确的文件路由，可参考此模式
- **Hyperedges**: graphify 支持多节点关系（"A、B、C 共同实现了 X"），存在 `G.graph["hyperedges"]`。MemPalace 如果要表达"这三条记忆共同支撑了某个结论"，可用此结构
- **vis.js HTML 导出**: 零依赖的交互式图谱可视化，可能比我们用 Qdrant dashboard 看数据更直观

## Meta Insights

1. **诚实数据 > 更多数据**：graphify 的核心竞争力不是"能建图"而是"每条边都标明了自己有多不靠谱"。这与 R42 的 Evidence Grading 完全一致——我们在记忆层面做了，但关系层面还没做。补上这一环，MemPalace 的可信度就有了完整链路。

2. **成本分层是架构决策，不是优化技巧**：graphify 最聪明的设计是把"能免费做的"和"要花钱做的"在架构层面分开——代码变更走 tree-sitter（毫秒级），文档变更标记等 LLM（美元级）。我们的 collector pipeline 目前没有这个区分，所有变更等权触发。

3. **Pipeline-as-Functions 证明了极简架构的可行性**：6900 行代码，零 class hierarchy，零 DI 框架，纯函数 + dict 传递。我们的 governance 层用了大量类和继承。不是说要重写——但新模块可以尝试这种风格，测试成本会显著降低。

4. **图分析的真正价值在"问好问题"**：`suggest_questions()` 从图结构自动生成审查问题——AMBIGUOUS 边 → "这两者到底什么关系？"、bridge node → "为什么这个概念连接了两个不同领域？"。profile_analyst 可以从记忆图谱结构生成类似的 probing questions，比"你最近怎么样"有深度得多。

5. **security.py 是被低估的模式**：SSRF 防护 + 重定向逐跳验证 + label 消毒 + 路径遍历防护，不到 200 行。我们的 ingest/channel 层处理外部 URL 时应该有同级别防护。
