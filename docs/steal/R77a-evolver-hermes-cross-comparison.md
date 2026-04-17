# R77a — Evolver × Hermes Agent 交叉对比报告

**基础报告**: R72 (Evolver v1.63.0 深度偷师) + R77 (Hermes Agent v1.0-rc)
**对比博文**: https://evomap.ai/zh/blog/hermes-agent-evolver-similarity-analysis (403, 通过搜索引擎缓存和 R77 provenance 章节间接获取)
**Date**: 2026-04-15 | **Category**: Cross-Comparison (Follow-up)

---

## TL;DR

Evolver 和 Hermes Agent 在三个层面解决相同的核心问题——但解法的抽象层不同。Evolver 在**进化循环层**做记忆（MemoryGraph 跨 session 因果链），Hermes 在**会话压缩层**做记忆（12 字段 state snapshot 在 session 内迭代）。Evolver 用**信号去重 + 强制创新**打断修复循环，Hermes 用**anti-thrashing + circuit breaker**打断压缩循环。两者都是"检测无效重复 → 切换策略"的实例，但操作对象不同。对 Orchestrator 而言，这两套机制不互斥——一个管 session 间的进化记忆，一个管 session 内的上下文压缩。联合偷法是：Evolver 的跨 session 因果链 + Hermes 的 session 内状态序列化。

---

## 一、架构同构争议：事实梳理

EvoMap 团队发表了架构同构分析，R77 的 provenance 章节已记录核心事实：

| 时间线 | EvoMap Evolver | Hermes Agent |
|--------|---------------|--------------|
| 公开日期 | 2026-02-01 | v0.2.0: 2026-03-12 (skill 生态) |
| 自进化仓库 | EvoMap/evolver (GEP 协议) | hermes-agent-self-evolution: 2026-03-09 |
| 时间窗口 | — | 24-39 天后 |
| 核心协议 | Scan → Select → Mutate → Validate → Solidify | Scan → Select → Generate → Test → Register |
| 记忆资产 | Gene + Capsule + EvolutionEvent | SKILL.md + 执行记录 + session history |
| 术语映射 | Gene → SKILL.md, Capsule → 执行记录, solidify → skill_manage(create) | (12 组系统性替换) |
| 代码保护 | 核心 28 模块混淆 + .integrity hash + GPL-3.0 | MIT |

**本报告不评判谁抄谁**——那是法律和社区的事。本报告的任务是：两个项目都做了什么，做得怎么样，我们能学什么。

---

## 二、同一问题的不同层次解法

### 2.1 记忆系统：跨 Session 因果链 vs Session 内状态快照

这是两个系统最根本的分歧。

| 维度 | Evolver (R72) | Hermes (R77) |
|------|---------------|--------------|
| **记忆粒度** | EvolutionEvent（一次进化的完整记录：信号→基因→结果） | Summary（12 字段的 agent 状态快照） |
| **记忆跨度** | 跨所有 session（append-only events.jsonl） | 仅限当前 session（`_previous_summary` 在 session 内迭代） |
| **更新方式** | append 新事件 + parent 指针形成因果链 | 字段级 update（In Progress → Completed Actions） |
| **消费者** | Selector（选择下一个 Gene 时读取历史胜率） | "DIFFERENT assistant"（压缩后的 agent 自己） |
| **预测能力** | `computePredictiveBoost()`——贝叶斯先验提升基因选择 | 无——summary 是描述性的，不驱动决策 |
| **遗忘机制** | `checkEpochBoundary()` 分代衰减，防止过拟合 | `_SUMMARY_TOKENS_CEILING = 12K` 硬上限 + "Remove only if clearly obsolete" |
| **因果追溯** | parent_id → 可以重建完整进化谱系 | 无——每次 summary 是独立快照 |

**关键洞见**：Evolver 的记忆是**决策驱动**的（记住什么有效，用于选择下一步），Hermes 的记忆是**上下文驱动**的（记住现状，用于恢复工作环境）。

两者解决的是记忆的不同维度：
- **What worked before**（Evolver）→ 指导未来行动
- **Where am I now**（Hermes）→ 恢复当前状态

Orchestrator 两个都需要。我们的 `experiences.jsonl` 有 Evolver 的"记什么有效"但缺因果链；我们的 `condenser` 试图做 Hermes 的"记现状"但缺结构化 schema。

### 2.2 循环打断：信号去重 vs Anti-Thrashing

两个系统都遇到"做同样的事但期望不同结果"的循环问题，解法结构对称但操作层不同。

| 维度 | Evolver: 信号去重 | Hermes: Anti-Thrashing |
|------|-------------------|------------------------|
| **检测什么** | 同一信号在最近 8 轮出现 ≥3 次 | 连续 2 次压缩各省 <10% |
| **检测对象** | 进化信号（错误模式、性能瓶颈） | 压缩效果（token 节省比） |
| **打断方式** | `suppressedSignals` 过滤 + 注入 `force_innovation_after_repair_loop` | `_ineffective_compression_count` + 停止压缩 + 降级到 trim-only |
| **升级路径** | 连续 repair ≥3 → 强制创新; 空轮 ≥5 → steady-state | 压缩耗尽 → gateway 层 auto-reset session |
| **恢复方式** | 新信号出现 → 去重集合重建 | 新对话 → 计数器归零 |
| **操作层** | 跨 session（events.jsonl 历史） | session 内（内存状态，不持久化） |

**抽象一层看**，两者都是同一个 pattern 的实例：

```
检测: consecutive_ineffective_attempts >= threshold
打断: switch_strategy() 或 escalate_to_outer_layer()
恢复: new_input_breaks_the_pattern()
```

Evolver 在"进化策略选择"层面实例化了这个 pattern，Hermes 在"上下文压缩"层面实例化。**这个 pattern 本身是 P0——可以在 Orchestrator 的任何重复执行路径中应用。**

### 2.3 验证 / 固化：Solidify vs Verification Gate

| 维度 | Evolver: Solidify | Hermes: 无显式 gate（Gateway 层恢复） |
|------|-------------------|---------------------------------------|
| **验证时机** | 每次进化后，代码修改完成时 | 无显式"验证后固化"步骤 |
| **验证内容** | blast_radius 检查 + forbidden_paths + 命令白名单 + canary check | 压缩后 tool_pair sanitize + role alternation |
| **失败处理** | `git reset --hard` 回滚 + 写 failed EvolutionEvent + 生成 LearningSignals | 降级到 fallback model / trim-only / gateway reset |
| **审计记录** | ValidationReport（结构化：每条命令 stdout/stderr/ok + env_fingerprint） | 无结构化验证记录 |
| **约束类型** | 硬性（代码层白名单，不可绕过） | 混合（regex self-destruct prevention 是硬性，压缩阈值是软性） |

Evolver 的 Solidify 是一个**显式的验证-固化门**——验证通过才写入成功事件，失败直接回滚。Hermes 没有这个概念——它的"验证"分散在各个 recovery 路径中。

**Orchestrator 的 verification-gate skill 在概念上接近 Evolver 的 Solidify**，但缺少：
1. 机器可执行的验证命令（Gene 的 `validation[]`）
2. 结构化的 ValidationReport
3. 失败自动生成学习信号（`buildSoftFailureLearningSignals()`）

---

## 三、联合偷法：两个系统的互补模式

### P0 — 联合模式（3 个）

#### 1. 双层记忆架构：决策记忆 + 上下文记忆

| 层 | 来源 | 机制 | 用途 |
|----|------|------|------|
| 决策记忆 | Evolver MemoryGraph | 信号→基因→结果的因果链 + parent_id + 贝叶斯先验 | "上次遇到类似信号时，哪个策略成功了？" |
| 上下文记忆 | Hermes Compressor v3 | 12 字段 state schema + 迭代 update + DIFFERENT assistant framing | "当前 agent 在做什么？做到哪了？还剩什么？" |

**我们的 gap**: `experiences.jsonl` 兼具两个角色但都做得不够——作为决策记忆缺因果链和预测能力，作为上下文记忆缺结构化 schema。

**适配方案**:
1. experiences.jsonl 增加 `parent_id` 和 `outcome_score`，使其成为决策记忆
2. condenser 的 SUMMARIZE_PROMPT 改为结构化模板（参考 Hermes 12 字段裁剪），使其成为上下文记忆
3. 两层分开——不要让一个数据结构同时承担两个职责

**Triple Validation**:
- 跨域复现 ✅: 数据库的 WAL（决策 = query planner statistics）+ checkpoint（上下文 = buffer pool state）；版本控制的 blame（决策 = 谁改的哪行）+ working copy（上下文 = 当前文件状态）
- 生成力 ✅: 任何新 agent 能力都可以问"需要决策记忆还是上下文记忆？"来决定存储策略
- 排他性 ✅: 不是"加两种存储"——是从"一个 experiences 文件"拆分为"两种不同用途的记忆层"
- Score: **3/3** | Knowledge irreplaceability: 判断直觉 + 隐性上下文 + 独特行为模式 = **3 categories**

#### 2. 通用循环打断 Pattern

```
CYCLE_BREAKER(metric, threshold, strategy_switch, escalation):
  if consecutive_ineffective(metric) >= threshold:
    attempt strategy_switch()
    if still_ineffective after strategy_switch:
      escalate_to_outer_layer()
```

| 实例化 | metric | threshold | strategy_switch | escalation |
|--------|--------|-----------|-----------------|------------|
| Evolver 信号去重 | same_signal_count | 3 / 8 events | suppress + force_innovation | steady-state 模式 |
| Hermes 压缩反抖动 | compression_savings_pct | 2 consecutive < 10% | stop compress + trim-only | gateway auto-reset |
| **Orchestrator: 任务重试** | same_error_pattern | 3 attempts | 换 approach / 换 model | 停止 + 报告用户 |
| **Orchestrator: 学习去重** | same_experience_type | 3 entries | suppress + 标记 "已知问题" | 升级为 Skill |

**适配方案**: 抽象为 `src/governance/safety/cycle_breaker.py`，参数化 metric/threshold/switch/escalation 四个维度。loop_detection.py 的现有逻辑是这个 pattern 的一个实例。

**Triple Validation**:
- 跨域复现 ✅: TCP 拥塞控制（slow start → congestion avoidance → timeout → reset）、电路断路器（closed → open → half-open）
- 生成力 ✅: 给定任何新的循环场景，pattern 直接告诉你需要定义哪四个参数
- 排他性 ✅: 不是"加个 counter"——是四维参数化的通用循环打断框架（metric × threshold × switch × escalation）
- Score: **3/3** | Knowledge irreplaceability: 判断直觉 + 踩坑经验 = **2 categories**

#### 3. 验证声明 + 失败学习信号

Evolver 的 Gene `validation[]` + `buildSoftFailureLearningSignals()` 组合：验证命令在任务开始前声明，失败后自动转为可学习的信号。

| 阶段 | Evolver | Hermes | Orchestrator 现状 |
|------|---------|--------|-------------------|
| 声明 | Gene.validation[] | 无 | verification-gate 概念性检查 |
| 执行 | solidify 时 run 白名单命令 | 无 | 手动验证 |
| 记录 | ValidationReport（结构化） | 无 | 无结构化记录 |
| 失败→学习 | `buildSoftFailureLearningSignals()` → 信号注入 | 分级冷却（但不生成学习信号） | 无 |

**适配方案**:
1. SKILL.md 增加 `validation` 字段，声明完成验证命令（白名单：python/node/npm/pytest）
2. verification-gate 执行这些命令，生成 ValidationReport
3. 验证失败时，自动分析失败原因生成 experience entry（类似 `buildSoftFailureLearningSignals()`）

**Triple Validation**:
- 跨域复现 ✅: TDD（测试在代码前声明）、CI（pipeline 在 merge 前声明）、合同（验收标准在交付前声明）
- 生成力 ✅: 任何新 Skill 都能问"验证命令是什么？"来填充 validation 字段
- 排他性 ✅: 不是"加个 test"——是事前声明 + 事后验证 + 失败学习的三阶段闭环
- Score: **3/3** | Knowledge irreplaceability: 踩坑经验 + 判断直觉 = **2 categories**

### P1 — 值得做（3 个）

| Pattern | 机制 | 适配方向 | 工时 |
|---------|------|---------|------|
| **EvolutionEvent 审计链** | parent_id + blast_radius + mutation 描述 + outcome score，append-only JSONL | 扩展 experiences.jsonl 条目，增加 parent_id 和 blast_radius 字段 | ~3h |
| **分代记忆衰减** | Evolver `checkEpochBoundary()`: 事件数/成功率满足条件 → 旧偏好权重打折扣 | 在 experiences 读取时按时间衰减权重，防止历史成功模式垄断未来决策 | ~2h |
| **Strategy Presets** | 6 种预设（balanced/innovate/harden/repair-only/early-stabilize/steady-state）+ 自动切换 | 让 Orchestrator 的执行模式可配置：日常/紧急/稳定期/探索期 | ~4h |

### P2 — 仅参考（2 个）

| Pattern | 为何参考 |
|---------|---------|
| **Hub 网络继承** | EvoMap 的 Gene 可以跨节点继承（GPT-4 agent 发布的 Gene 可以被 Claude agent 使用）。Orchestrator 是单节点，暂无需求 |
| **Personality State 进化** | 5 维人格向量随进化事件更新。有趣但当前声音校准是静态的且足够 |

---

## 四、对比矩阵（所有 P0 联合模式）

| 能力 | Evolver impl | Hermes impl | Orchestrator 现状 | Gap 性质 | Action |
|------|-------------|-------------|-------------------|---------|--------|
| **跨 session 决策记忆** | MemoryGraph: 信号→基因→结果因果链 + 贝叶斯先验 | 无（session 隔离） | experiences.jsonl: 扁平记录，无因果链，无预测 | 结构性 | 增加 parent_id + outcome_score |
| **session 内上下文记忆** | 无（Evolver 不管 session 内上下文） | Compressor v3: 12 字段 state schema + 迭代 update | condenser: 自由文本 + 每次从零摘要 | 范式级 | 定义 state schema + 迭代 update（R77 P0 已规划） |
| **循环打断** | suppressedSignals + force_innovation（跨 session） | anti-thrashing + circuit breaker（session 内） | loop_detection.py: 仅 session 内，无跨 session 信号去重 | 覆盖面 | 抽象通用 cycle_breaker + 跨 session 信号去重 |
| **验证声明** | Gene.validation[] 白名单命令 | 无 | verification-gate 概念性 | 机器可执行性 | SKILL.md 加 validation 字段 |
| **失败→学习** | `buildSoftFailureLearningSignals()` | 分级冷却（不生成学习信号） | 无 | 完全缺失 | 验证失败时自动生成 experience |

---

## 五、路径依赖交叉分析

### Evolver 的路径锁定

1. **"不改代码"定位** → 必须依赖宿主 runtime → 宿主不配合就无法验证。核心 28 模块混淆 + GPL-3.0 加强了控制但限制了社区参与。
2. **Hub 中心化** → 高级功能（semantic search、skill market、LLM review）都是 Hub 依赖。断网后降级到本地但失去了进化的核心价值。
3. **Node.js 零依赖** → 极度便携，但算法全部内置意味着升级任何依赖的算法要改 Evolver 本身。

### Hermes 的路径锁定

1. **10,900 行单文件** → 新贡献者倾向加 patch 而非重构 → 文件继续膨胀 → 状态交互 bug 继续产生。
2. **SQLite 单节点** → 部署简单但无法水平扩展。
3. **sync-first 压缩** → 状态管理简单但长压缩阻塞用户。

### Orchestrator 应避免的陷阱

| 锁定类型 | Evolver 教训 | Hermes 教训 | 我们的防线 |
|----------|-------------|-------------|-----------|
| 文件膨胀 | 混淆 28 个核心模块，单模块 769K | run_agent.py 10,900 行 | **拆分原则**: 任何文件 >500 LOC 必须评估是否该拆 |
| 中心化依赖 | Hub 是单点故障 | SQLite 是单节点瓶颈 | **本地优先**: git + 本地 DB，不依赖外部服务做核心功能 |
| 接口僵化 | GEP 协议版本 1.6.0，但 Gene schema 已经 3 次迁移 | Compressor 经历 36 commits 5 次重大重构 | **schema 版本**: 任何结构化数据带 schema_version 字段 |

---

## 六、Gaps Identified

| 维度 | 从 Evolver 看到的 gap | 从 Hermes 看到的 gap | 联合 gap |
|------|----------------------|---------------------|---------|
| **记忆/学习** | 缺跨 session 因果链（parent_id） | 缺结构化 state schema（12 字段） | 需要两层记忆架构 |
| **故障/恢复** | 缺 Solidify 级别的显式验证门 | 缺 Gateway 外层恢复 | 验证在 agent 内，恢复在 agent 外 |
| **安全/治理** | 缺命令白名单（硬约束） | 缺 self-destruct prevention（硬约束） | 需要代码层 physical interception |
| **执行/编排** | N/A（Evolver 不编排 agent） | 缺跨 session 信号去重 | 通用循环打断框架 |
| **上下文/预算** | N/A（Evolver 不管 token） | 缺按比例缩放的 token 预算 | condenser 已规划改进（R77 P0） |
| **质量/评审** | 缺 ValidationReport 结构化记录 | 缺验证声明（事前） | 三阶段闭环：声明→验证→学习 |

---

## 七、Adjacent Discoveries

1. **EvoMap 的 Proxy 架构（本地邮箱代理）**可以启发 Orchestrator 与外部服务的通信模式——Agent 不直接调用外部 API，全部走本地 proxy，proxy 负责认证+重试+消息同步。这比在每个调用点加 retry 更干净。

2. **Evolver 的 atomic write 模式**（写 .tmp 再 fs.renameSync + `_evolver_managed` 标记）是"安全安装到已有配置"的通用模式。hookAdapter 的 deepMerge + atomic write + managed 标记三件套可以直接用于我们的 hook 安装。

3. **Hermes commit 溯源标注**（"from OpenCode", "from Codex", "from Claude Code"）是我们 steal 流程的验证——标注来源不仅是道德要求，也是技术追溯的基础设施。

---

## 八、Meta Insights

1. **同一问题在不同抽象层有不同的最优解，且这些解法互补而非互斥。** Evolver 的 MemoryGraph 和 Hermes 的 Compressor 不是竞争关系——一个管"什么策略有效"（跨 session），一个管"当前在做什么"（session 内）。把它们放在同一维度比较是误导——它们应该被叠加，而非择一。

2. **循环打断是 agent 系统的第一公理。** Evolver 在进化层、Hermes 在压缩层、TCP 在传输层、电路断路器在服务层——都实例化了同一个 pattern。如果你在设计任何重复执行的流程，第一个问题应该是"无效重复的检测指标是什么，打断策略是什么，升级路径是什么"。

3. **"验证声明前置"的价值被严重低估。** Evolver 的 Gene.validation[] 在进化开始前就声明了"什么叫成功"。这不只是测试——是一个认知约束：强迫系统在行动前定义验收标准。我们的 verification-gate 在行动后才思考"怎么验证"，这时候已经有了 confirmation bias（"我做了这些改动，它应该是对的"）。

4. **架构同构争议的技术教训：当两个系统解决同一问题时，即使独立开发也会产生结构相似性——因为问题本身约束了解空间。** Scan → Select → Mutate → Validate → Solidify 不是 EvoMap 发明的——是"受控自进化"这个问题域的自然结构。这不意味着没有抄袭，但意味着"结构相似"本身不足以作为抄袭的充分证据。

5. **混淆核心模块是"最后手段式"的 IP 保护——它同时也阻止了最有价值的偷师。** Evolver 的 solidify.js（291K tokens）、strategy.js（38K tokens）、evolve.js（769K tokens）都混淆了。这些恰好是最有学习价值的模块。从开源生态角度，这削弱了项目作为技术参考的价值。从 Orchestrator 偷师角度，这意味着我们只能从清文本模块（signals.js, idleScheduler.js, sanitize.js, hookAdapter.js）和接口行为推断核心逻辑。

---

*R77a — Evolver × Hermes Agent 交叉对比完成。核心联合偷法：双层记忆架构（P0）> 通用循环打断 pattern（P0）> 验证声明 + 失败学习信号（P0）> 审计链结构化（P1）> 分代记忆衰减（P1）> 策略预设系统（P1）。*
