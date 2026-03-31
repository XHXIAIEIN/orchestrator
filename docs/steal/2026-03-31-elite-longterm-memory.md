# Round 23: elite-longterm-memory @nextfrontierbuilds — 深挖报告

> 来源：https://github.com/NextFrontierBuilds/elite-longterm-memory
> 日期：2026-03-31
> 下载量：44.4k | 459 installs | 170 stars
> 许可：MIT-0

---

## elite-longterm-memory @nextfrontierbuilds

**概述**: 六层记忆栈（HOT/WARM/COLD/ARCHIVE/CLOUD/AUTO-EXTRACT），用 WAL 协议保证不丢上下文，LanceDB 做语义检索，git-notes 做结构化决策存储，SuperMemory 做云备份，Mem0 做自动事实抽取。

**核心机制**:

| 层级 | 存储 | 作用 | 持久性 |
|------|------|------|--------|
| Layer 1: HOT RAM | SESSION-STATE.md | 当前任务上下文 | 写盘+WAL |
| Layer 2: WARM | LanceDB vectors | 语义检索历史记忆 | 本地向量DB |
| Layer 3: COLD | git-notes | 结构化决策/学习 | git 分支感知 |
| Layer 4: ARCHIVE | MEMORY.md + daily/ | 人可读长期记忆 | 文件系统 |
| Layer 5: CLOUD | SuperMemory API | 跨设备同步 | 远程 |
| Layer 6: AUTO | Mem0 | 自动事实抽取 | 远程API |

---

## 可偷模式

### P0 — 立刻能用

#### 模式 1: Daily Log 自动归档

**描述**: 每天自动创建 `memory/YYYY-MM-DD.md` 日志，session 结束时把 SESSION-STATE.md 中有价值的条目沉淀到当天日志。MEMORY.md 只保留精炼的长期记忆（<5KB 上限），细节在 daily log 里。

**为什么值得偷**: 我们的 MEMORY.md 已经 bloat 了——所有东西塞一个文件，无法区分"上周的临时笔记"和"永远有效的规则"。daily log 提供了自然的时间衰减机制。

**与 Orchestrator 现状差异**: 我们有 `memory_tier.py` 的 hot/extended 分层，但没有时间维度的自动归档。SESSION-STATE.md（wal.py）写了就不清理。

**适配方案**:
1. `SOUL/tools/` 加 `daily_log.py`：session 结束时把 SESSION-STATE.md 的 completed tasks 移到 `memory/YYYY-MM-DD.md`
2. 给 Stop hook 加日志沉淀步骤（已有 experiences.jsonl 记录，加 daily markdown 是平行通道）
3. MEMORY.md 加 size guard：超 5KB 时提醒用户 prune

---

#### 模式 2: Topic-Based Memory Sharding

**描述**: `memory/topics/` 目录按主题切分记忆文件（projects/、people/、decisions/、lessons/、preferences.md）。MEMORY.md 作为索引，指向详细文件。

**为什么值得偷**: 我们 Claude 项目 memory 目录里已经有 30+ 个 md 文件，但命名混乱（有的按项目、有的按反馈类型、有的按功能）。需要子目录分类。

**与 Orchestrator 现状差异**: `memory_tier.py` 的 `load_extended_memory()` 已按 tag 匹配文件名，但文件组织是扁平的。topic sharding 能让 tag 匹配更精准。

**适配方案**:
1. Claude memory 目录重组：`feedback/`、`projects/`、`references/`、`steal/` 四个子目录
2. `_find_memory_dir()` 改为递归扫描子目录
3. MEMORY.md 的索引区按子目录分组

---

#### 模式 3: Memory Hygiene 周期

**描述**: 每周一次记忆卫生检查——清理过期 vector、合并 daily log 到 MEMORY.md、归档已完成项目。有明确的维护命令（`memory_recall query="*" limit=50` 审计、`memory_forget id=<id>` 清理）。

**为什么值得偷**: 记忆系统的第一杀手不是写不进去，是写太多噪声导致检索精度崩溃。我们目前没有任何清理机制。

**适配方案**:
1. 加 `memory_hygiene.py` 定时任务（或手动触发）
2. 检查维度：文件大小 > 10KB 的 md 文件、3 个月未修改的 daily log、hotness score = 0 的条目
3. 建议（不自动执行）把候选条目移到 `.trash/` 或降级

---

### P1 — 需要额外基础设施

#### 模式 4: LanceDB 本地向量检索

**描述**: 用 LanceDB 做本地向量存储，OpenAI embedding 做索引。`autoRecall: true` 每次对话自动注入相关记忆；`autoCapture: false` 只手动存储重要内容。`minImportance: 0.7` + `minScore: 0.3` 双阈值过滤噪声。

**为什么值得偷**: 我们的 `load_extended_memory()` 用关键词匹配（tag in filename），语义检索能力为零。用户说"上次那个蓝牙问题"，关键词匹配找不到 `bluetooth_stanmore.md`，向量检索能找到。

**与 proactive-agent 的 WAL 区别**: proactive-agent 只有 WAL（写盘保证），没有向量检索层。elite-longterm-memory 的 WAL 是第一层，LanceDB 是第二层——WAL 保证不丢，LanceDB 保证能找回来。

**适配方案**:
1. 新模块 `src/governance/context/memory_vector.py`
2. 用 LanceDB（纯本地，无 API 依赖）+ 本地 embedding（`D:\Agent\models` 里可能已有 sentence-transformers）
3. 索引源：MEMORY.md + memory/*.md + experiences.jsonl
4. 查询入口：Governor dispatch 前自动检索相关记忆注入 prompt
5. **不用 OpenAI embedding**——我们已有本地模型偏好，用 sentence-transformers/all-MiniLM-L6-v2

---

#### 模式 5: Git-Notes 作为决策冷存储

**描述**: 用 `git notes` 把决策和学习附着到 commit 上。分支感知（不同分支的决策不互相污染）。Python CLI 做 CRUD：`memory.py remember/get/export`。

**为什么值得偷**: 我们的 experiences.jsonl 是 append-only 扁平文件，不跟 git 历史关联。决策"为什么选 Agent SDK 而不是 subprocess"应该挂在迁移的那个 commit 上，而不是散落在 MEMORY.md。

**与 Orchestrator 现状差异**: 我们有 `src/governance/audit/wal.py` 做 WAL 写盘，有 `experiences.jsonl` 做经历记录，但两者都不跟 git commit 关联。git-notes 补上了"决策溯源"这条线。

**适配方案**:
1. `SOUL/tools/git_decisions.py`：封装 `git notes add/show/list`
2. Governor 做重大决策后，自动在当前 HEAD 附着 note
3. 部门执行完成后，在 commit 上附着执行摘要
4. 注意：git-notes 需要 `git notes push` 才能同步到 remote——加到 push workflow

---

#### 模式 6: 子 Agent 上下文透传

**描述**: 文档明确指出"Sub-agents isolated — Don't inherit context"是五大失败模式之一。解法：spawn 子 agent 时，主动把关键上下文（从 SESSION-STATE.md 和 MEMORY.md 中提取）注入到任务 prompt。

**为什么值得偷**: 我们 Governor dispatch 到六部时，只传 task spec，不传记忆上下文。工部 agent 不知道用户偏好、不知道之前的决策历史，每次从零开始。

**与 Orchestrator 现状差异**: `memory_tier.py` 的 `format_extended_for_prompt()` 已经能格式化 extended memory，但 Governor dispatch 没调用它。管道断了。

**适配方案**:
1. Governor dispatch 流程加一步：`resolve_tags_from_spec(spec)` → `load_extended_memory(tags)` → 注入到 sub-agent prompt
2. 这管道的代码 90% 已经写好了，只是没接上

---

### P2 — 观察但不急

#### 模式 7: SuperMemory 云备份

**描述**: 可选的云端记忆同步，跨设备共享知识库。

**评估**: 我们是单机架构，暂不需要。但如果未来 Mac Mini + Windows 双机协作，这个模式可以回来。先记下。

---

#### 模式 8: Mem0 自动事实抽取

**描述**: 用 Mem0 API 自动从对话中提取事实，去重合并，号称 80% token 节省。

**评估**: 依赖外部 API（MEM0_API_KEY），与我们"本地优先"原则冲突。但"自动从对话中提取可记忆事实"这个 idea 可以用本地模型实现。留作 P2 备选。

---

## 记忆架构对比

| 维度 | elite-longterm-memory | Orchestrator 现状 | 差距 |
|------|----------------------|-------------------|------|
| WAL 协议 | SESSION-STATE.md + 6 类信号扫描 | `wal.py` — 相同的 6 类信号 ✅ | **已对齐**（Round 14 已偷） |
| 热层 | SESSION-STATE.md | `session-state.md` via wal.py ✅ | **已对齐** |
| 温层（向量） | LanceDB + OpenAI embedding | 无 ❌ | **P1 缺口** |
| 冷层（结构化） | git-notes + Python CLI | experiences.jsonl（无 git 关联）| **P1 缺口** |
| 归档层 | MEMORY.md + daily/ + topics/ | MEMORY.md（单文件 bloat）| **P0 缺口** |
| 云层 | SuperMemory | 无（暂不需要）| N/A |
| 自动抽取 | Mem0 API | 无 | P2 |
| 分层加载 | 6 层分离 | 2 层（hot/extended）| **P1 缺口** |
| 子 agent 上下文 | 文档化的最佳实践 | 代码写好但没接上 | **P0 缺口** |
| 记忆卫生 | 周清理 + 审计命令 | 无 | **P0 缺口** |

---

## 与 proactive-agent WAL 的区别

proactive-agent（Round 14 已偷）只做了第一层：WAL 写盘保证。

elite-longterm-memory 在 WAL 之上叠了五层：
1. **向量检索**（proactive 没有）—— WAL 保证写了，LanceDB 保证找得回来
2. **git-notes 溯源**（proactive 没有）—— 决策挂在 commit 上，不是散落文件
3. **时间归档**（proactive 没有）—— daily log 提供自然衰减
4. **主题切分**（proactive 没有）—— 按 topic 组织比按时间组织更适合检索
5. **卫生机制**（proactive 没有）—— 定期清理防止噪声累积

WAL 是地基，elite-longterm-memory 是整栋楼。

---

## 执行优先级

| 序号 | 模式 | 难度 | 预计工作量 |
|------|------|------|-----------|
| 1 | Daily Log 归档 | 低 | 2h |
| 2 | 子 Agent 上下文透传 | 低 | 1h（接管道） |
| 3 | Memory Hygiene | 低 | 2h |
| 4 | Topic Sharding | 中 | 3h（需迁移现有文件）|
| 5 | LanceDB 向量检索 | 中 | 4h |
| 6 | Git-Notes 决策存储 | 中 | 3h |

建议顺序：2 → 1 → 3 → 4 → 5 → 6（先接已有管道，再加新层）

---

*偷师 agent: Claude Opus 4.6 | 分支: steal/round23-clawhub*
