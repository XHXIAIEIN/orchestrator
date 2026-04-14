# R51 — OpenSpace Steal Report

**Source**: https://github.com/HKUDS/OpenSpace | **Stars**: 5,150 | **License**: MIT
**Date**: 2026-04-14 | **Category**: Self-Evolving Agent Infrastructure

---

## TL;DR

OpenSpace 是目前见过最系统化的**技能自演化基础设施**。核心命题：每次任务执行后，系统自动分析执行质量，识别技能缺陷，触发 LLM 修复/衍生/捕获三种演化模式，并持久化进 SQLite。46% 的 token 节省来自技能复用，而非压缩。

三个直接可偷的独立机制：**技能版本 DAG**（SkillLineage）、**工具质量感知降级**（ToolQualityRecord.penalty）、**多触发器演化管道**（三种触发源 → 统一 EvolutionContext → 并行执行）。

---

## Architecture Overview

```
Layer 4: Communication Gateway (WhatsApp/Feishu + 会话 store + 附件缓存 + allowlist ACL)

Layer 3: OpenSpace.execute() 主循环
  ├── SkillRegistry.select_skills()  — BM25 + embedding 两阶段选技能
  ├── GroundingAgent.process()       — 最多 20 轮 tool-calling 主循环
  ├── [finally] ExecutionAnalyzer.analyze_execution()  — 后执行分析
  └── [finally] SkillEvolver.process_analysis()        — 触发演化

Layer 2: 技能引擎 (skill_engine/)
  ├── SkillRegistry     — 发现 / 选择 / 注入
  ├── SkillRanker       — BM25 rough-rank → embedding re-rank
  ├── ExecutionAnalyzer — 对话 log → ExecutionAnalysis (LLM 判断)
  ├── SkillEvolver      — 三触发 + 三演化类型 + 并发限制
  ├── SkillStore        — SQLite 持久化（带 exponential backoff retry）
  └── patch.py          — FULL/DIFF/PATCH 三格式 + fuzzy match 6 级降级

Layer 1: 工具层 (grounding/)
  ├── ToolQualityManager  — 工具成功率追踪 + LLM issue 注入 + penalty 计算
  ├── Backends: shell / gui / mcp / web / system
  ├── Security: sandbox (e2b), policy
  └── Transport: stdio / SSE / streamable HTTP / websocket

数据存储:
  .openspace/openspace.db  — 技能记录 + 执行分析 + 工具质量（统一 SQLite）
  .openspace/skill_embedding_cache/  — embedding 向量 pickle 缓存
  logs/recordings/  — 轨迹录像（对话 log + 截图 + 可选视频）
  sessions/  — Communication gateway 会话（transcript.jsonl + workspace/）
```

---

## Steal Sheet

### P0 — 必偷（3 个）

#### P0-1: 技能版本 DAG (SkillLineage)

**机制**：每个技能版本都是 DAG 中的一个节点。三种 origin：IMPORTED（初始导入，根节点）、FIXED（原地修复，`generation = parent + 1`，同名同路径新 skill_id）、DERIVED（增强/合成，新目录新名字，可多父节点）、CAPTURED（从执行轨迹中识别新模式，无父节点）。每个节点存 `content_snapshot`（完整目录快照 dict）+ `content_diff`（unified diff）。

```python
# types.py — SkillLineage 核心字段
@dataclass
class SkillLineage:
    origin: SkillOrigin          # IMPORTED / FIXED / DERIVED / CAPTURED
    generation: int = 0          # 距根节点深度
    parent_skill_ids: List[str]  # FIXED: 1个; DERIVED: 1+个; IMPORTED/CAPTURED: []
    source_task_id: Optional[str]  # 触发演化的任务 ID
    change_summary: str           # LLM 生成的变更描述
    content_diff: str             # unified diff (多父 DERIVED 时为空)
    content_snapshot: Dict[str, str]  # {相对路径: 内容} 完整快照
    created_by: str               # "human" | model name
```

**技能 ID 格式**：`{name}__imp_{uuid8}`（导入）、`{name}__v{gen}_{uuid8}`（演化）。持久化在 `.skill_id` sidecar 文件——目录移动/机器迁移后 ID 不变。

**我们的差距**：技能目前无版本追踪，SKILL.md 改了就改了，不知道是谁改的、改了什么、为什么改。引入 `.skill_id` + frontmatter 里的 `generation`/`parent` 字段就能复现 80% 的价值。

**改造方案**：`.claude/skills/<name>/.skill_id` sidecar + `SOUL/public/skill_store.json` 记录版本链。不需要 SQLite，JSONL append 就够。

| 维度 | OpenSpace | 我们 |
|------|-----------|------|
| 技能版本追踪 | 有（DAG + snapshot + diff） | 无 |
| 技能 ID 稳定性 | .skill_id sidecar，迁移后不变 | 用目录名，重命名就断 |
| 演化历史查询 | SQL 查 parent_skill_ids | 无法查询 |
| 回滚能力 | content_snapshot 随时还原 | git diff 手动 |

---

#### P0-2: 三触发器演化管道

**机制**：演化不只是"分析完了触发一次"，而是三个独立触发源：

1. **ANALYSIS**（Trigger 1）：每次 `execute()` finally 块 → `ExecutionAnalyzer.analyze_execution()` → `EvolutionSuggestion` list → `process_analysis()`
2. **TOOL_DEGRADATION**（Trigger 2）：`ToolQualityManager` 检测到工具成功率跌破阈值 → 找所有依赖该工具的技能 → 自动修复指令（anti-loop：`_addressed_degradations` dict）
3. **METRIC_MONITOR**（Trigger 3）：周期扫描所有活跃技能的 `applied_rate`/`completion_rate`/`effective_rate`/`fallback_rate` → 低于阈值 → LLM confirm → 演化

三个触发源都产生 `EvolutionContext` → `_execute_contexts()` → `asyncio.Semaphore(max_concurrent=3)` 并行执行。

```python
# evolver.py — 三触发阈值常量
_FALLBACK_THRESHOLD = 0.4           # fallback_rate > 40% → 候选修复
_LOW_COMPLETION_THRESHOLD = 0.35    # completion_rate < 35% → 候选修复
_HIGH_APPLIED_FOR_FIX = 0.4        # applied_rate > 40% + 低完成率 → FIX 而非 DERIVED
_MIN_APPLIED_FOR_DERIVED = 0.25    # applied_rate > 25% + 适度完成率 → DERIVED
```

**两阶段确认**：rule-based 粗筛（宽松阈值）→ LLM confirmation（`_llm_confirm_evolution()`），避免 LLM 过度演化。

**Anti-loop 设计**：
- Trigger 2：`_addressed_degradations[tool_key] = {skill_ids}`，工具恢复后自动清除，再次降级时重新评估
- Trigger 3：新演化技能 `total_selections=0`，自然需要 `min_selections=5` 新数据才会被再次评估，不需要冷却期

**我们的差距**：skills 没有质量追踪，不知道哪些 skills 被选中了、用没用上、任务成没成。现有的 steal 报告只是存档，没有形成反馈环。

---

#### P0-3: 工具质量 Penalty 计算 + LLM issue 注入

**机制**：每个工具维护一个 `ToolQualityRecord`，key 格式 `{backend}:{server}:{tool_name}`。

```python
# types.py — ToolQualityRecord.penalty 计算逻辑
@property
def penalty(self) -> float:
    if self.total_calls < 3:
        return 1.0                    # 新工具不惩罚
    success_rate = self.recent_success_rate
    if success_rate >= 0.4:           # PENALTY_THRESHOLD
        return 1.0                    # 超过阈值不惩罚
    # 线性映射: penalty = 0.3 + (success_rate / threshold) * 0.7
    base_penalty = 0.3 + (success_rate / 0.4) * 0.7
    # 连续失败额外惩罚: 3次连续 → -0.1, 5次 → -0.3
    consec = self.consecutive_failures
    if consec >= 3:
        base_penalty -= min(0.3, (consec - 2) * 0.1)
    return max(0.2, min(1.0, base_penalty))  # 夹在 [0.2, 1.0]
```

**LLM issue 注入**：`ExecutionAnalyzer` 完成分析后，如果 LLM 识别出工具有问题（HTTP 200 但数据错误等语义失败），通过 `add_llm_issue()` 注入为 `ExecutionRecord(success=False)`，喂进同一个 `recent_success_rate` pipeline，与规则追踪统一成一个 penalty 分数。

**我们的差距**：Orchestrator 跑完任务不知道哪个 tool 出了问题。Telegram bot 超时只能靠 log 手动排查。

---

### P1 — 值得做（4 个）

| Pattern | 机制摘要 | 我们的差距 | 改造代价 |
|---------|---------|-----------|---------|
| **BM25 + Embedding 两阶段技能检索** | 超过 10 个技能时 BM25 rough-rank（top_k × 3 候选）→ embedding re-rank（text-embedding-3-small），embedding 跨 session pickle 缓存 | 技能选择靠 LLM 全量扫描，技能多了上下文爆炸 | ~3h，实现 BM25，embedding 部分可选 |
| **SkillID hallucination 纠正** | LLM 经常把 ID hex 后缀写错（`cb` → `bc`），分析器用 Levenshtein edit distance ≤ 4 做最近邻纠正，防止演化指向不存在的技能 | 我们的技能没有稳定 ID，LLM 只能引用名字 | 先实现 .skill_id sidecar，纠正逻辑捎带做 |
| **多格式 Patch 应用 + 6 级 Fuzzy Match** | LLM 输出技能更新时支持 FULL/DIFF（SEARCH/REPLACE blocks）/PATCH（\*\*\* Begin Patch 多文件格式）三种格式自动检测，SEARCH/REPLACE 精确匹配失败时有 6 级降级：exact → line-trimmed → block-anchor → whitespace-normalized → indentation-flexible → trimmed-boundary | 手动 Edit tool 写死 old_string，LLM 生成的 diff 经常因空白匹配失败 | ~2h |
| **轨迹 token 分类追踪** | `contextvars.ContextVar` 标记每次 LLM 调用来源（agent/skill_select/analyzer/evolver/summarizer），并发安全。可以算"技能选择消耗了多少 token"vs"主 agent 消耗了多少" | 我们的 token 消耗完全黑盒 | ~1h，litellm callback hook |

---

### P2 — 观察（3 个）

| Pattern | 描述 | 是否适合我们 |
|---------|------|------------|
| **Communication Gateway + Session Store** | WhatsApp/Feishu adapter，每个用户一个 `ChannelSession`（session_key = `{platform}_{chat_id}`），workspace 目录隔离，transcript.jsonl 持久化，附件缓存+大小限制 | 我们 TG bot 已有会话，但没有 workspace 目录隔离。可以借鉴 session_key 设计 |
| **GDPVal Benchmark** | 50 个真实世界任务，通过 GDP 价值（时薪×完成时间）衡量 agent 效率，而不是 pass rate。主张"经济价值"比"成功率"更实用 | 对比 benchmark 的思路值得借鉴，但我们规模不到需要这个的地步 |
| **Host Detection + LLM kwargs 自动继承** | `host_detection/` 检测当前运行在哪个 agent 框架内（nanobot/openclaw），自动读取对应配置。子系统的 LLM client 继承主 client 的 `api_key`/`api_base` 等 kwargs | 我们 agent dispatch 时凭证管理也是问题，litellm 的 kwargs 透传模式可以参考 |

---

## Comparison Matrix

| 维度 | OpenSpace | Orchestrator | 差距程度 |
|------|-----------|-------------|---------|
| 技能版本追踪 | DAG + snapshot + diff，可回滚任意版本 | 无，git history 间接追踪 | 显著 |
| 技能演化反馈环 | 3 触发源 × 3 演化类型，全自动 | 无反馈环，人工更新 SKILL.md | 显著 |
| 工具质量追踪 | 成功率 + 连续失败 + LLM issue，统一 penalty | 无 | 显著 |
| 技能检索效率 | BM25 + embedding 两阶段 | 全量 LLM 扫描 | 中等 |
| Token 分类可观测性 | contextvars 标记来源，per-component 统计 | 完全黑盒 | 中等 |
| 多平台通信 | WhatsApp + Feishu，会话/workspace 隔离 | Telegram only，无 workspace 隔离 | 中等 |
| 安全沙箱 | e2b sandbox + policy | 无独立沙箱层 | 低优先级 |

---

## Gaps（OpenSpace 的问题）

1. **数据飞轮需要量**：三触发器的演化效果强依赖 `total_selections >= 5` 的历史数据。冷启动时没有数据，没有演化，没有改进——和当前代理性能没区别。
2. **LLM confirmation 成本**：每次 metric_check 对每个候选技能做一次 LLM confirm，如果有 50 个技能 + 每 10 次执行触发一次 monitor，成本不低。
3. **本地 BM25 + OpenRouter embedding**：嵌入模型走 OpenRouter（qwen3-embedding-8b），有网络依赖。实际代码里写死了 `text-embedding-3-small`（注释说为了和 clawhub 向量空间兼容），但两个 model 名字不一致，像是遗留问题。
4. **stars 5K 但社区还很早期**：2026-03-25 才开源，skills 质量监控是 2026-04-03 才加的。生产稳定性未知。

---

## Adjacent Discoveries

- **GDPVal 评估框架**：用 GDP 价值（任务经济产出）评估 agent 而不是 pass/fail。`gdpval_bench/tasks_50.json` 包含 50 个有 GDP 值标注的真实任务。如果要给 Orchestrator 建客观评估基线，这个框架思路可以直接用。
- **`_db_retry` 装饰器**：`store.py` 里 SQLite retry with exponential backoff 的 decorator 实现非常干净，5 次重试 × 2x backoff，只 catch `OperationalError`（如 database locked）和 `DatabaseError`，不 catch 编程错误。我们如果上 SQLite 直接抄。
- **Fuzzy Match 降级链**：`fuzzy_match.py` 里 6 级降级的 SEARCH/REPLACE 匹配链在写 Edit tool 的地方通用性很高，不只是技能演化能用。
- **SKILL.md frontmatter 标准化**：他们的 `normalize_frontmatter()` 函数会自动修正 LLM 生成的 frontmatter YAML 引号问题（LLM 很容易漏引号），这是我们自己写 SKILL.md 生成器时的一个 footgun。

---

## Meta Insights

**核心洞察**：OpenSpace 解决的不是"agent 能不能用技能"，而是"技能怎么保持有效"。技能会随 API 变化、工具升级、场景演变而过期，没有演化机制的技能库是负债，不是资产。

**和我们的关系**：我们有 `.claude/skills/` 目录和 SKILL.md 格式，但没有任何反馈环。每个技能改了就改了，不知道改没改好。引入 `.skill_id` sidecar + 执行结果追踪（哪次选了哪个技能，任务成没成），就能在不上 SQLite 的情况下复现 P0-1 和 P0-2 的核心价值。

**演化的本质是数据飞轮**：技能越被用 → 数据越多 → 演化越精准 → 技能越好用 → 被选中越多。这个飞轮的启动条件是"有追踪"，而不是"有算法"。先把追踪做起来，算法之后再迭代。
