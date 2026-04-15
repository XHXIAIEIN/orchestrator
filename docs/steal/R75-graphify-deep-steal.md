# R75: Graphify 深度偷师报告

> 来源：`D:/Agent/.steal/graphify/` (github.com/safishamsi/graphify)
> 版本：0.3.28
> 日期：2026-04-14
> 分析员：Orchestrator
> 本次：首次分析，特定模块深度（知识图谱构建 + 转录流水线）

---

## 一、执行摘要

Graphify 是一个**把任意文件夹变成可导航知识图谱的 Claude Code skill + Python 库**。核心主张：把 Andrej Karpathy 的 `/raw` 文件夹工作流（把一切扔进文件夹）变成结构化图谱，输出 HTML、GraphRAG-ready JSON 和 Markdown 审计报告。

本次最值得偷的两个模式：

1. **API 消除模式**：Apr 10 commit `699e996` 把 `build_whisper_prompt()` 里对 `claude-haiku` 的调用完全删掉，改成「让调用它的 agent 自己写提示词，通过环境变量传入」。本质上是**把 LLM 推理成本从库转移到 orchestrator 层**，库只做字符串拼接，智能留在调用者手里。

2. **双轨提取 + AST/语义并行**：代码走 tree-sitter（免费、确定性），文档/图片走 Claude 子 agent（有成本、语义）。两条轨道并行运行，结果通过 `node["id"]` 去重合并。这是一个能直接复用的提取架构模板。

---

## 二、六维度扫描

### 维度 1：架构与核心机制（简述）

流水线：
```
detect() → [AST extract‖semantic subagents] → merge → build(nx.Graph) → cluster(Leiden) → analyze() → export()
```

每个阶段是独立函数，通过 Python dict 和 `nx.Graph` 通信，零共享状态。中间产物全写到 `graphify-out/`，支持 `--update` 增量模式（只重提取变更文件）。

图存储：**NetworkX 内存图 + JSON 序列化落盘**（`graph.json`），不用图数据库。查询靠 BFS/DFS 遍历。MCP stdio server 暴露 7 个 tool（`query_graph` / `get_node` / `get_neighbors` / `get_community` / `god_nodes` / `graph_stats` / `shortest_path`）。

### 维度 2：记忆与学习 ★ 深入

#### 2.1 三级缓存体系

**文件级缓存（`cache.py`）**

```python
def file_hash(path: Path) -> str:
    raw = p.read_bytes()
    # Markdown 文件只哈希 frontmatter 以下的 body，frontmatter 改了不失效
    content = _body_content(raw) if p.suffix.lower() == ".md" else raw
    h = hashlib.sha256()
    h.update(content)
    h.update(b"\x00")
    h.update(str(p.resolve()).encode())   # 路径不同 → 不同缓存 key
    return h.hexdigest()
```

缓存文件：`graphify-out/cache/{sha256}.json`，原子写（先写 `.tmp` 再 `os.replace`）。命中即跳过 Claude 调用，AST 缓存同一套机制。

**语义缓存分离**：`check_semantic_cache()` 在派发子 agent 前先查缓存，只把 uncached 文件列表传给 agent。子 agent 返回后 `save_semantic_cache()` 按 `source_file` 分组写回。

```python
# cache.py L93-116
def check_semantic_cache(files: list[str], root: Path) -> tuple[cached_nodes, cached_edges, cached_hyperedges, uncached_files]:
    ...
    for fpath in files:
        result = load_cached(Path(fpath), root)
        if result is not None:
            cached_nodes.extend(result.get("nodes", []))
            ...
        else:
            uncached.append(fpath)
```

**增量检测（`detect.py`）**：`detect_incremental()` 对比上次 `manifest.json`（存 mtime），只返回新增/修改文件。删除的文件被标记为 `deleted_files`，下次 build 时剔除。

#### 2.2 查询结果回写图谱（记忆闭环）

`ingest.py` 里有一个鲜少被注意的函数：

```python
def save_query_result(question: str, answer: str, memory_dir: Path, ...) -> Path:
    """Save a Q&A result as markdown so it gets extracted into the graph on next --update.
    
    This closes the feedback loop: the system grows smarter from both
    what you add AND what you ask.
    """
    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^\w]", "_", question.lower())[:50]
    filename = f"query_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.md"
    # 写入 graphify-out/memory/，detect() 会自动扫这个目录
    ...
```

`detect()` 里专门处理 `memory_dir`：

```python
memory_dir = root / "graphify-out" / "memory"
scan_paths = [root]
if memory_dir.exists():
    scan_paths.append(memory_dir)
```

**效果**：每次 `query` 结果写成 Markdown，下次 `--update` 时被提取进图，形成图谱自增长闭环。这是 RAG 里很少见的「问答结果反哺知识库」模式。

#### 2.3 图谱差分（`graph_diff`）

```python
def graph_diff(G_old, G_new) -> dict:
    # 返回 new_nodes / removed_nodes / new_edges / removed_edges / summary
```

支持版本对比，可用于「这次 --update 到底加了什么」。

### 维度 3：执行与编排 ★ 深入

#### 3.1 并行子 agent 编排（skill.md Step B）

核心模式（SKILL.md 里写死的禁令）：

```
MANDATORY: You MUST use the Agent tool here. Reading files yourself one-by-one is forbidden
— it is 5-10x slower. If you do not use the Agent tool you are doing this wrong.

Dispatch ALL subagents in a single message.
[Agent tool call 1: files 1-15]
[Agent tool call 2: files 16-30]
[Agent tool call 3: files 31-45]
All three in one message. Not three separate messages.
```

分组逻辑：
- 每块 20-25 个文件
- 图片单独一块（vision 需要独立 context）
- 同目录文件分在同一块（跨文件关系更容易被捕捉）
- 估算公式：`ceil(uncached_non_code_files / 22)` 个 agent，每批 ~45s

AST 提取和语义子 agent **在同一条消息里并发启动**，互不阻塞。

#### 3.2 子 agent prompt schema（完整定义）

```
You are a graphify extraction subagent. Output ONLY valid JSON — no explanation, no markdown fences.

Rules:
- EXTRACTED: relationship explicit in source (import, call, citation, "see §3.2")
- INFERRED: reasonable inference (shared data structure, implied dependency)  
- AMBIGUOUS: uncertain - flag for review, do not omit

confidence_score is REQUIRED on every edge — never omit it, never use 0.5 as default:
- EXTRACTED: 1.0 always
- INFERRED: reason individually. Direct structural evidence: 0.8-0.9. Reasonable: 0.6-0.7. Weak: 0.4-0.5
- AMBIGUOUS: 0.1-0.3
```

子 agent 直接输出 JSON，orchestrator 侧做校验（`validate.py`）和合并（`build.py`）。

#### 3.3 git hook 自动重建

```python
# hooks.py：post-commit hook
CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null)
# 过滤出代码文件
code_changed = [f for f in changed if f.suffix.lower() in CODE_EXTS and f.exists()]
if code_changed:
    from graphify.watch import _rebuild_code
    _rebuild_code(Path('.'))
```

`post-checkout` hook 在切分支时也触发重建（只重建代码部分，不触发 LLM）。标记用 `# graphify-hook-start` / `# graphify-hook-end` 包裹，支持追加到已有 hook。

### 维度 4：工具与集成（简述）

- **多格式输入**：代码（25 种语言）/ Markdown / PDF（pypdf）/ 图片（vision）/ docx / xlsx / 视频（faster-whisper）/ URL（推文 oEmbed / arXiv API / yt-dlp）
- **多格式输出**：HTML（vis.js 交互图）/ JSON / SVG / GraphML / Cypher（Neo4j）/ Obsidian vault / Wiki Markdown / MCP server
- **Hyperedge 渲染**：用 canvas 画凸包多边形表示三节点以上的群关系
- **平台 skill 文件**：同一套功能在 Claude Code / Codex / Aider / Copilot CLI / Gemini CLI / Cursor / Trae / OpenCode 各有一个 SKILL.md，内容基本相同，安装路径不同

### 维度 5：安全（简述）

`security.py` 做了 4 层：URL 白名单（只允许 http/https）、重定向拦截（`_NoFileRedirectHandler` 阻止 `file://` 重定向）、响应大小上限 + 超时、节点 label HTML 转义。`.graphifyignore` 支持 gitignore 风格的跳过规则，秘钥文件（`.env` / `.pem` / `credential*` 等）自动跳过不提取。

### 维度 6：质量与测试（简述）

每个模块有对应测试文件（`tests/test_*.py`），全部是纯单元测试，无网络调用，无文件系统副作用（只用 `tmp_path`）。测试覆盖 25 种语言的 AST 提取、置信度计算、图差分、MCP server、安全规则。

---

## 三、重点深入：五深度层

### Layer 1 — 表面行为

`/graphify` 命令 → 扫描文件夹 → 输出 `graph.html` + `graph.json` + `GRAPH_REPORT.md`。报告包含 god nodes（最高连通度节点）、社区划分、令人惊讶的跨文件关联、建议问题。

### Layer 2 — 机制

**知识图谱构建**：两轨并行。
- AST 轨道：tree-sitter parse → 遍历语法树 → 提取 class / function / import → 二次调用图 pass（函数体里的 `call` 节点，用 label→nid 字典反查被调用函数，生成 INFERRED `calls` 边）
- 语义轨道：子 agent 读文档/图片 → 输出 JSON schema → 主 agent 校验 + 缓存 + 合并

**转录流水线**：`detect()` 识别视频文件 → skill.md 中 orchestrator agent 自己从 god nodes 写 Whisper domain hint → `transcribe_all()` → 转录文本进 doc 队列 → 语义提取。

### Layer 3 — 设计意图

**为什么用 NetworkX 不用图数据库？**  
轻依赖。`pip install graphifyy` 就够，不需要 Neo4j/ArangoDB。够用的查询（BFS/DFS/最短路径/中心性）NetworkX 全覆盖。需要 Neo4j 的场景靠导出 Cypher 文件解决。

**为什么置信度三级（EXTRACTED / INFERRED / AMBIGUOUS）不是数值？**  
审计导向设计。AMBIGUOUS 标签自动出现在「建议问题」列表，让用户知道哪里不确定。纯数值置信度不能触发 workflow。

**为什么节点 ID 用 `_make_id()` 规范化而不是用原始字符串？**  
```python
def _make_id(*parts: str) -> str:
    combined = "_".join(p.strip("_.") for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", combined)
    return cleaned.strip("_").lower()
```
节点 ID 是 `file_httpclient_constructor` 这样的形式，方便跨文件去重（`G.add_node()` 幂等）且 JSON-safe。

### Layer 4 — 隐藏约束

**节点去重的优先级陷阱**：AST 节点先进图，语义节点后进图会覆盖 AST 节点的 attributes（`nx.add_node()` 后来者覆盖）。`build.py` 注释里明确说这是**故意的**（语义节点有更丰富的 label，AST 节点有精确的 `source_location`）——但如果你想保留 AST 的 `source_location`，就要反转传入顺序。

**god node 过滤的两个隐藏规则**：
- 文件级 hub 节点（label == 文件名）被排除，否则 `client.py` 这个节点会因为有几十条 `contains`/`imports` 边而常年排第一，毫无信息量
- AST method stub（`label.startswith(".") and label.endswith("()")`）也被排除

**社区分裂阈值**：社区超过图总节点的 25%（最少 10 个节点）就触发二次 Leiden pass 分裂。这阻止了一个超级社区吞噬整个图。

### Layer 5 — 可移植洞察

见下节 Pattern Extraction。

---

## 四、API 消除模式深析

### Before（`699e996` 之前）

```python
def build_whisper_prompt(god_nodes: list[dict]) -> str:
    labels = [n.get("label", "") for n in god_nodes[:10]]
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": f"Key concepts: {labels}. Write a 20-word speech-to-text hint."}],
        )
        return msg.content[0].text.strip() + " Use proper punctuation."
    except Exception:
        topics = ", ".join(labels[:5])
        return f"Technical discussion about {topics}. Use proper punctuation."
```

每次转录前额外一次 API 调用，即使模型已经知道 god nodes 是什么。

### After（现在）

```python
def build_whisper_prompt(god_nodes: list[dict]) -> str:
    """
    The coding agent generates the actual one-sentence domain hint from these labels
    and passes it via GRAPHIFY_WHISPER_PROMPT or as initial_prompt — no separate API call needed here.
    """
    override = os.environ.get("GRAPHIFY_WHISPER_PROMPT")
    if override:
        return override
    topics = ", ".join(labels[:5])
    return f"Technical discussion about {topics}. Use proper punctuation."
```

Skill.md 里对应的指令：

```
Strategy: Read the god nodes from detect output. You are already a language model —
write a one-sentence domain hint yourself from those labels. Then pass it to Whisper
as the initial prompt. No separate API call needed.
```

### 模式总结

**库不做 LLM 调用，orchestrator 做**。库只提供结构化数据（god node labels），orchestrator agent 用自己的上下文生成 prompt，通过环境变量或参数传入。库保持无状态、可测试、无 API key 依赖。

这个模式的适用条件：当一个「辅助性」LLM 调用的输入完全来自上层 orchestrator 已有的上下文时，把调用权上移。

---

## 五、Pattern Extraction

### P0 — 必须偷

**P0-A：查询结果回写知识库（记忆闭环）**

```python
# ingest.py save_query_result()
def save_query_result(question, answer, memory_dir, source_nodes):
    # 写 graphify-out/memory/query_20260414_120000_xxx.md
    # 带 YAML frontmatter (type: "query", source_nodes: [...])
    # detect() 会自动扫 memory/ 目录 → 下次 --update 时进图
```

对 Orchestrator 的意义：经验 `.jsonl` / 记忆 `.md` 写完后不只是存档，还应该被下次构建时的分析工具消费。这是「写入即学习」而不是「写入即遗忘」。

**P0-B：子 agent 并行强制规则**

```
MANDATORY: Dispatch ALL subagents in a single message.
Reading files yourself one-by-one is forbidden — it is 5-10x slower.
```

当前 Orchestrator 的 skill 里没有这么硬的规定。加上「同一条消息派发所有子 agent」的强制规则，可以把多文件分析任务的时间压缩到单批 45s 以内。

**P0-C：置信度三级 + AMBIGUOUS 驱动 workflow**

AMBIGUOUS 边自动出现在「建议问题」和「知识差距」列表。这是把「不确定性」从信息转化为 **action item** 的做法。当前 Orchestrator 的 impression 级别记忆没有对应的「需要验证」队列。

### P1 — 值得偷

**P1-A：Markdown frontmatter 缓存忽略**

```python
def _body_content(content: bytes) -> bytes:
    """Strip YAML frontmatter from Markdown — only hash the body."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].encode()
    return content
```

Orchestrator 的 experience 文件经常更新 frontmatter（status、tags、date）而不改内容。如果有缓存机制，用这个方法可以避免 frontmatter 改动使缓存失效。

**P1-B：`_make_id()` 规范化节点 ID**

统一的 ID 格式使跨文件去重天然幂等，不需要额外的 merge 逻辑。Orchestrator 目前的节点/记忆 ID 缺乏统一的规范化规则。

**P1-C：社区分裂阈值（防大社区吞噬）**

`_MAX_COMMUNITY_FRACTION = 0.25` + `_MIN_SPLIT_SIZE = 10`。任何聚合系统（记忆聚类、skill 归组）都有这个问题：一个主题太泛会把所有东西吸进去。设个分裂阈值然后二次聚类是通用解法。

**P1-D：令人惊讶的连接评分（surprise score）**

```python
def _surprise_score(G, u, v, data, node_community, u_source, v_source):
    score = 0
    score += conf_bonus  # AMBIGUOUS=3, INFERRED=2, EXTRACTED=1
    if u_file_type != v_file_type:  score += 2  # 跨文件类型
    if u_top_dir != v_top_dir:      score += 2  # 跨 repo
    if u_community != v_community:  score += 1  # 跨社区
    if relation == "semantically_similar_to":  score = int(score * 1.5)
    if min(deg_u, deg_v) <= 2 and max(deg_u, deg_v) >= 5:  score += 1  # 外围→核心
```

多维度综合评分比单一维度（仅靠置信度）发现更有价值的连接。可以直接移植到记忆图谱的「推荐关联」功能。

### P2 — 可参考

**P2-A：god node 过滤（排除文件 hub 和 method stub）**

防止结构性节点（文件名、`__init__`）污染中心性排名。对任何图分析系统都适用。

**P2-B：多平台 skill 文件策略**

同功能 9 个平台各一个 SKILL.md（skill.md / skill-aider.md / skill-codex.md / skill-copilot.md 等），内容大同小异，安装命令不同。维护成本高但覆盖面广。Orchestrator 目前只考虑 Claude Code，参考价值有限。

**P2-C：`detect()` 论文启发式检测**

```python
_PAPER_SIGNALS = [
    re.compile(r'\[\d+\]'),     # [1] 引用格式
    re.compile(r'\bwe propose\b', re.IGNORECASE),
    re.compile(r'\d{4}\.\d{4,5}'),   # arXiv ID
    ...
]
_PAPER_SIGNAL_THRESHOLD = 3  # 需要至少 3 个信号
```

对 `.md` 文件用启发式规则判断是否是学术论文，改走 paper 提取路径。低成本的文件类型细化方案。

---

## 六、路径依赖分析

### Graphify 做了什么约束选择

1. **NetworkX + JSON 而非图数据库**：适合单机离线场景，但 100k 节点以上性能会降级。跨进程查询（多个 agent 并发访问图）需要额外的锁或 MCP server 作为单点访问层。

2. **tree-sitter 而非 LLM 做代码提取**：确定性高、可测试、免费，但无法理解语义（函数 A 和函数 B 在解决同一问题但没有调用关系 → AST 不知道）。这是靠语义子 agent 补的。

3. **skill-as-orchestrator 而非独立 daemon**：没有后台进程，每次 `/graphify` 都是一次完整的 pipeline 执行。简单可靠，但无法支持实时增量（最快只能到 post-commit hook 粒度）。

### 对 Orchestrator 的影响

直接复用图数据库不现实（Orchestrator 没有持久化图谱需求）。可以复用的是：
- 查询结果回写机制（闭环记忆）
- 子 agent 并行强制规则
- 置信度 + AMBIGUOUS 驱动 workflow

---

## 七、可直接移植的代码片段

### 片段 A：Frontmatter-aware 缓存 key

```python
def _body_hash(path: Path) -> str:
    raw = path.read_bytes()
    text = raw.decode(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:].encode()
            return hashlib.sha256(body).hexdigest()
    return hashlib.sha256(raw).hexdigest()
```

适用场景：Orchestrator 的经验/记忆文件经常只更新 frontmatter（date、status），用这个哈希可以跳过内容未变的重新处理。

### 片段 B：查询回写（记忆闭环）

```python
def save_to_memory(question: str, answer: str, memory_dir: Path, source_refs: list[str] = None) -> Path:
    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^\w]", "_", question.lower())[:50].strip("_")
    filename = f"qa_{now.strftime('%Y%m%d_%H%M%S')}_{slug}.md"
    
    frontmatter = f"""---
type: "query_result"
date: "{now.isoformat()}"
question: "{question}"
---"""
    
    body = f"\n\n# Q: {question}\n\n## Answer\n\n{answer}"
    if source_refs:
        body += "\n\n## Sources\n\n" + "\n".join(f"- {r}" for r in source_refs)
    
    out = memory_dir / filename
    out.write_text(frontmatter + body, encoding="utf-8")
    return out
```

### 片段 C：惊喜连接评分模板

```python
def surprise_score(edge_data: dict, source_type: str, target_type: str, 
                   source_community: int, target_community: int,
                   source_degree: int, target_degree: int) -> int:
    score = {"AMBIGUOUS": 3, "INFERRED": 2, "EXTRACTED": 1}.get(
        edge_data.get("confidence", "EXTRACTED"), 1)
    if source_type != target_type:
        score += 2  # 跨类型更令人惊讶
    if source_community != target_community:
        score += 1  # 跨社区
    if edge_data.get("relation") == "semantically_similar_to":
        score = int(score * 1.5)
    if min(source_degree, target_degree) <= 2 and max(source_degree, target_degree) >= 5:
        score += 1  # 外围节点意外连到核心
    return score
```

---

## 八、总结

Graphify 最值得偷的不是图谱本身，而是三个**系统工程选择**：

1. **API 消除**：辅助性 LLM 调用（生成 Whisper prompt）的输入完全来自 orchestrator 上下文时，把调用权上移到 orchestrator，库保持无 API key 依赖。这是成本控制的正确姿势，不是偷懒。

2. **记忆闭环**：问答结果写回语料库，下次构建时进图。知识不只从外部输入，也从系统自身的推理中生长。

3. **不确定性驱动 action**：AMBIGUOUS 标签不是「我不知道」的终点，而是「需要验证」的起点，自动出现在 workflow 的待办列表里。

这三个模式都和 Orchestrator 的当前痛点直接对应，P0-A/B/C 值得在下一轮 implementation 里落地。
