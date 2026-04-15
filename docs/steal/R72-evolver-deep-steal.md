# R72: Evolver v1.63.0 深度偷师报告

**来源**: https://github.com/EvoMap/evolver  
**作者**: EvoMap team (team@evomap.ai)  
**版本**: v1.63.0 (package.json)  
**许可**: GPL-3.0-or-later（核心模块混淆发布）  
**分析日期**: 2026-04-14  
**分支**: steal/round-deep-rescan-r60  

---

## 概述

Evolver 是一个 GEP（Genome Evolution Protocol）驱动的 AI Agent 自进化引擎。**它不直接改代码**，而是扫描运行日志、提取信号、从 Gene/Capsule 库中选择进化策略、生成一个严格协议约束的 GEP prompt，再由宿主 runtime（如 OpenClaw）执行真正的代码修改。修改后走 solidify 验证→git 状态录入→EvolutionEvent 写入 append-only 日志，形成完整审计链。v1.63.0 的"自进化"本质是：**协议约束下的提示词驱动代码修改 + 事后固化**，而非运行时任意自改代码。

核心技术栈：Node.js 18+，零外部依赖（只有 dotenv），全部核心算法内置。关键 GEP 模块（selector/mutation/solidify/prompt 等 28 个文件）在公开发布版中**以 javascript-obfuscator 混淆**，但逻辑通过 `.integrity` 校验文件保护，exports 接口可调用。

---

## 进化循环图（Evolution Loop Map）

```
                    ┌──────────────────────────────────────────┐
                    │              TRIGGER LAYER                │
                    │  (Hook / --loop daemon / 手动 run)        │
                    └──────────────┬───────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────┐
                    │         SIGNAL EXTRACTION                 │
                    │  Layer 1: Regex (0ms, 确定性)             │
                    │  Layer 2: Keyword Score (0ms, 统计)       │
                    │  Layer 3: LLM Semantic (每5轮1次, 异步)   │
                    │  输入: memory/ + session logs             │
                    │  输出: Signal[]                           │
                    └──────────────┬───────────────────────────┘
                                   │ signals[]
                    ┌──────────────▼───────────────────────────┐
                    │         HISTORY ANALYSIS                  │
                    │  analyzeRecentHistory(events[-10])        │
                    │  → suppressedSignals (频率≥3/8)           │
                    │  → consecutiveRepairCount                 │
                    │  → emptyCycleCount / failureRatio         │
                    │  Post-processing: dedup / force-innovate  │
                    └──────────────┬───────────────────────────┘
                                   │ final signals[]
         ┌─────────────────────────▼────────────────────────────┐
         │              GENE SELECTOR                            │
         │  signals × gene.signals_match → scoreTagOverlap()    │
         │  + memoryGraph predictive boost (过去成功率)          │
         │  + personality key (rigor/creativity/risk_tolerance) │
         │  + curriculum targets                                 │
         │  → {selected_gene, reason[], alternatives[]}         │
         └─────────────────────────┬────────────────────────────┘
                                   │ gene
         ┌─────────────────────────▼────────────────────────────┐
         │              MUTATION BUILDER                         │
         │  buildMutation(signals, gene, personality, strategy)  │
         │  → {id, category, trigger_signals,                   │
         │      target, expected_effect, risk_level}            │
         └─────────────────────────┬────────────────────────────┘
                                   │ mutation
         ┌─────────────────────────▼────────────────────────────┐
         │              PROMPT ASSEMBLY                          │
         │  buildGepPrompt() / buildReusePrompt()               │
         │  嵌入: Gene策略 + Capsule历史 + 亲代Event + Mutation  │
         │  + NarrativeMemory摘要 + LocalStateAwareness          │
         │  输出: 严格结构化的 GEP protocol prompt 打印到 stdout  │
         └─────────────────────────┬────────────────────────────┘
                                   │ GEP prompt → 宿主执行代码修改
         ┌─────────────────────────▼────────────────────────────┐
         │              SOLIDIFY (代码修改完成后调用)             │
         │  1. policyCheck: blast_radius + forbidden_paths      │
         │  2. isValidationCommandAllowed: 白名单校验            │
         │  3. runValidations: 执行 gene.validation[] 命令       │
         │  4. runCanaryCheck: fork index.js 加载测试            │
         │  5. detectDestructiveChanges: 识别高危变更            │
         │  成功 → 写 EvolutionEvent → 更新 AssetStore          │
         │  失败 → git rollback → 写 failed EvolutionEvent      │
         └─────────────────────────┬────────────────────────────┘
                                   │
         ┌─────────────────────────▼────────────────────────────┐
         │              LEARNING & MEMORY                        │
         │  memoryGraph.recordOutcomeFromState()                 │
         │  narrativeMemory.recordNarrative()                    │
         │  reflection.recordReflection() (每N轮)               │
         │  skillDistiller.autoDistill() (idle时)               │
         │  selfPR (score≥0.85 + streak≥3 → PR 到公开仓库)      │
         └──────────────────────────────────────────────────────┘
                         │ 下轮循环读取 memory/ 作为输入
                         └────────────────────────────────────▲
                                       反馈闭环
```

---

## 一、架构深度分析

### 1.1 GEP 资产体系（三类型）

**Gene（基因）**: 可复用的进化策略模板，存于 `assets/gep/genes.json`。每个 Gene 包含：
- `category`: repair / optimize / innovate / explore
- `signals_match[]`: 触发匹配关键词
- `strategy[]`: 步骤化执行策略（给 LLM 的指令）
- `constraints`: max_files, forbidden_paths
- `validation[]`: solidify 后执行的验证命令

内置 3 个核心 Gene: `gene_gep_repair_from_errors`、`gene_gep_optimize_prompt_and_assets`、`gene_gep_innovate_from_opportunity`，另有 `gene_tool_integrity` 等在 assetStore 默认值中定义。

**Capsule（胶囊）**: 成功进化的具体实例快照，含 diff snippet + outcome score。是"历史上这个 Gene 解决了什么问题"的具体记录，用于 prompt 中展示可参考案例。

**EvolutionEvent（进化事件）**: append-only JSONL（`assets/gep/events.jsonl`），每次进化的完整记录：
```json
{
  "type": "EvolutionEvent",
  "intent": "repair",
  "signals": ["log_error", "errsig:..."],
  "genes_used": ["gene_gep_repair_from_errors"],
  "mutation_id": "mut_...",
  "personality_state": {"rigor":0.7,"creativity":0.35,...},
  "blast_radius": {"files":2,"lines":44},
  "outcome": {"status":"success","score":0.85},
  "meta": {
    "selector": {"selected":"...", "reason":[], "alternatives":[]},
    "constraint_violations": [],
    "validation_ok": true,
    "memory_graph": "..."
  }
}
```

EvolutionEvent 是整个系统的**因果追溯锚点**——每个事件指向亲代事件（`parent` 字段），形成进化谱系链。

### 1.2 Signal 提取（三层架构）

`src/gep/signals.js` 实现了 3 层信号提取，互相补充：

**Layer 1 - Regex（确定性，0ms）**: 手写规则，覆盖错误类型、操作系统兼容性、路径问题、工具滥用等。包含中文/繁中/日语的功能请求检测（`加个功能|做个功能|追加|实装` 等），提取时附带上下文 snippet。

**Layer 2 - Keyword Scoring（统计，0ms）**: 7 个信号 profile，每个信号有关键词权重表，累计得分超阈值才触发。例如 `perf_bottleneck` 阈值 6，`slow`=3 + `timeout`=4 可触发，单一 `slow` 不够。防止误报。

**Layer 3 - LLM Semantic（每 5 轮 1 次，同步 curl）**: 把 corpus 摘要发到 Hub `/a2a/signal/analyze`，用 LLM 做语义级信号识别。用 `execSync` + curl 实现同步 HTTP（因为 Node http.request 异步在 spin-wait 中无法触发）。

三层合并后走**后处理流水线**：
1. 优先级过滤（有 actionable 信号时去掉纯配置缺失信号）
2. 历史去重（同一信号在最近 8 轮出现 ≥3 次 → 压制，避免修复循环）
3. 强制创新（连续 ≥3 次 repair → 注入 `force_innovation_after_repair_loop`）
4. 空轮检测（blast_radius=0 的轮次 ≥4 → 注入 `empty_cycle_loop_detected`）
5. 饱和退化（连续空轮 ≥5 → 切换到 `steady-state` 策略）

### 1.3 策略系统（6 种预设）

`src/gep/strategy.js` 定义了 6 种策略，每种是 repair/optimize/innovate/explore 的比例混合：

| 策略 | Repair | Optimize | Innovate | Explore | 适用场景 |
|------|--------|----------|----------|---------|---------|
| balanced | 20% | 20% | 50% | 10% | 日常运行 |
| innovate | 5% | 10% | 80% | 5% | 系统稳定，快速出功能 |
| harden | 40% | 35% | 20% | 5% | 大变更后稳定期 |
| repair-only | 80% | 18% | 0% | 2% | 紧急故障 |
| early-stabilize | 60% | 22% | 15% | 3% | 刚上线头几轮 |
| steady-state | 55% | 25% | 5% | 15% | 进化饱和，维护+探索 |

策略由 `repairLoopThreshold` 控制何时自动切换（连续 repair 比例超过阈值触发创新强制）。

### 1.4 Personality State（个性状态）

`src/gep/personality.js` 实现了可进化的人格状态，5 个维度，每个 0-1：
```
rigor | creativity | verbosity | risk_tolerance | obedience
```

`personalityKey()` 输出形如 `rigor=0.7|creativity=0.3|...` 的键，用于 memoryGraph 中按人格分组查找历史成功率。人格状态随进化事件的 outcome 更新（成功 → 强化，失败 → 调整），多模型并行维护（`personality_models.json`）。

### 1.5 MemoryGraph（预测性记忆）

`src/gep/memoryGraph.js` 是整个系统的"工作记忆"，以 JSONL 格式存在 `memory/evolution/memory_graph.jsonl`。核心功能：
- `recordSignalSnapshot()`: 记录信号→基因选择→结果的完整轨迹
- `getMemoryAdvice()`: 根据当前信号返回历史建议（偏好哪个基因、哪种人格）
- `computePredictiveBoost()`: 计算基因的预测得分提升（基于历史胜率）
- `recordHypothesis() / recordAttempt() / recordOutcomeFromState()`: 三阶段实验跟踪

`checkEpochBoundary()` 实现分代机制：当事件数 / 成功率满足条件时，旧偏好记录衰减，开启新纪元，防止记忆过拟合历史模式。

### 1.6 Solidify 验证链

Solidify 是"把 LLM 的建议固化为已验证知识"的关键步骤。验证链：

1. **blast_radius 计算**: `git diff --numstat` 统计实际改动文件数/行数，与 Gene 约束对比
2. **forbidden_paths 检查**: 禁止路径（.git, node_modules, evolver 源文件本身）
3. **destructive change 检测**: 识别删除大量代码等高危变更
4. **validation 命令执行**: Gene 声明的验证命令（白名单：只允许 `node/npm/npx` 开头，禁止 `$(...)` / `;` / `|` 等）
5. **canary check**: fork 子进程执行 `require('../index.js')` 验证入口不崩溃

全部通过才写入 EvolutionEvent（status=success）。任何失败 → `git reset --hard` 回滚 → 写 failed 事件 → 触发 LearningSignals 记录失败教训。

**硬性上限**: `BLAST_RADIUS_HARD_CAP_FILES=20, BLAST_RADIUS_HARD_CAP_LINES=800`（可配置）

### 1.7 自修改边界（Editable vs Fixed）

**可修改区域**（evolution 可以改）：
- `assets/gep/` 下的 Gene/Capsule 定义
- `memory/` 下的各类状态文件
- 宿主 workspace 的业务代码（通过 prompt 引导 LLM 修改）
- `SKILL.md`、技能定义文件

**禁止修改区域**（28 个混淆核心模块，见 `src/gep/selfPR.js` OBFUSCATED_FILES）：
```
src/evolve.js, src/gep/selector.js, src/gep/mutation.js,
src/gep/solidify.js, src/gep/prompt.js, src/gep/candidates.js,
src/gep/reflection.js, src/gep/narrativeMemory.js, src/gep/curriculum.js,
src/gep/personality.js, src/gep/learningSignals.js, src/gep/memoryGraph.js,
src/gep/memoryGraphAdapter.js, src/gep/strategy.js, src/gep/candidateEval.js,
src/gep/hubVerify.js, src/gep/crypto.js, src/gep/contentHash.js,
src/gep/a2aProtocol.js, src/gep/hubSearch.js, src/gep/hubReview.js,
src/gep/policyCheck.js, src/gep/deviceId.js, src/gep/envFingerprint.js,
src/gep/skillDistiller.js, src/gep/explore.js, src/gep/integrityCheck.js,
src/gep/shield.js
```

这 28 个文件在 `src/gep/.integrity` 文件中有内容 hash 记录，`integrityCheck.js` + `shield.js` 在运行时验证完整性。

`EVOLVE_ALLOW_SELF_MODIFY=false` 是默认值，即使用户配置，forbidden_paths 也会阻止写入 evolver 本身的源码目录。

### 1.8 自动 SelfPR 机制

`src/gep/selfPR.js` 实现了一个极具野心的机制：当 evolver 优化自身非混淆文件（如 `src/ops/`、`src/adapters/`、`src/config.js`）达到高质量标准时，**自动向公开仓库提 PR**：

触发条件（全部满足）：
- `EVOLVER_SELF_PR=true`（默认关闭）
- outcome score ≥ 0.85
- 连续成功 streak ≥ 3
- 改动文件 ≤ 3，改动行数 ≤ 100
- 24h 冷却期
- 通过 fullLeakCheck（无凭据泄露）
- 文件不在 OBFUSCATED_FILES 集合中

使用 `gh` CLI 创建 PR，**永不自动合并**，branch 名 `evolver-self-mutation-{timestamp}`。

---

## 二、六维扫描

### 2.1 记忆/学习系统

**MemoryGraph（工作记忆）**: JSONL append-only，按 signal_key 索引（信号集合 → sorted → hash key），记录每种信号组合的历史胜率和偏好基因。`computePredictiveBoost()` 给 Selector 提供贝叶斯风格的先验分数提升。

**NarrativeMemory（叙事记忆）**: `narrativeMemory.js` 将离散事件压缩为时间序列叙事摘要（max 3000 chars），注入 prompt 中。`trimNarrative()` 用 FIFO 窗口控制长度。

**Reflection（元反思）**: 每 `REFLECTION_INTERVAL_CYCLES` 轮触发一次，`buildReflectionContext()` 分析近期事件模式，`buildSuggestedMutations()` 生成人格/策略调整建议，写入 `memory/evolution/reflections.jsonl`。

**Curriculum（课程目标）**: `curriculum.js` 维护一个技能学习目标列表（`curriculum_state.json`），`generateCurriculumSignals()` 在当前信号稀疏时注入 `curriculum_target` 信号，驱动主动学习。

**SkillDistiller（技能蒸馏）**: `skillDistiller.js`（混淆，337k tokens）是系统最复杂的模块。在 idle 时分析成功 Capsule 的模式，合成新 Gene（`gene_distilled_` 前缀），自动发布到 EvoMap Hub。`collectDistillationData()` + `analyzePatterns()` + `synthesizeGeneFromPatterns()` 三阶段流水线。

**IdleScheduler（闲置调度）**: OMLS 启发，检测系统 idle 时间（Win/macOS/Linux 各平台实现），分 4 档强度：`signal_only` → `normal` → `aggressive`（触发蒸馏+反思） → `deep`（触发深度进化）。

### 2.2 质量/评审系统

**Gene Validation 命令白名单**:
```javascript
// isValidationCommandAllowed 规则：
1. 只允许 node / npm / npx 开头
2. 禁止命令替换 $(...)、反引号
3. 禁止 shell 操作符 ;、&、|、>、<
4. 每个命令 180s 超时
5. cwd 锁定在 repoRoot
```

**Canary Check**: `src/canary.js` 用 fork 验证入口文件加载不崩溃，是最后一道安全网。

**ValidationReport**: 结构化报告类型（schema_version 1.6.0），包含每条验证命令的 stdout/stderr/ok，env_fingerprint（node版本/平台/evolver版本），用于 Hub 端可审计评估。

**LlmReview**: `src/gep/llmReview.js`（模块存在，`EVOLVER_LLM_REVIEW=0` 默认关闭），可在 solidify 前发送 diff 给 LLM 做代码审查。

**MIN_PUBLISH_SCORE=0.78**: Capsule 发布到 Hub 的最低分数门槛。

**Blast Radius 分类**: `classifyBlastSeverity()` 按文件数/行数分 low/medium/high/critical，`BLAST_RADIUS_HARD_CAP` 是绝对上限，超过直接拒绝进化。

### 2.3 安全/治理系统

**混淆 + Integrity 双重保护**: 28 个核心模块混淆发布，`.integrity` 文件存储内容 hash，`shield.js` 运行时验证，防止有人替换核心逻辑。

**Sanitize 模块（凭据脱敏）**: `src/gep/sanitize.js` 实现了完整的多模式脱敏：
- Bearer token / sk- / github_pat_ / AKIA / sk-ant- / npm_ 等
- 本地路径（/home/、/Users/、Windows 驱动器路径）
- 邮件地址、.env 文件引用
- PEM 私钥块

`fullLeakCheck()` 检测模式（不替换，只报告），用于 broadcast 前扫描，LEAK_CHECK_MODE=warn|error 可控。

**EnvFingerprint（环境指纹）**: `captureEnvFingerprint()` 记录 node 版本/平台/架构/OS/evolver版本，hostname 做 SHA-256 哈希（保护隐私），写入每条 ValidationReport。跨环境对比时能识别"同样代码在不同机器失败"的模式。

**IssueReporter（自动问题上报）**: 连续失败 ≥5 次 + 24h 冷却，自动向 GitHub 提 issue（凭据必须脱敏）。错误签名用 sha256 做 key，防重复上报。

**Singleton Guard（进程单例）**: `evolver.pid` 文件 + 进程信号 kill(pid, 0) 检测，防多实例冲突。

**Worker Pool 双重开关**: 本地 `WORKER_ENABLED=1` + Hub 端 dashboard toggle，两者都开才接任务，防止意外承接工作。

### 2.4 集成/适配系统

**HookAdapter（平台无关接口）**: `src/adapters/hookAdapter.js` + 3 个平台 adapter（cursor/claude-code/codex）。`setupHooks` 自动检测平台（通过 `.cursor`/`.claude`/`.codex` 目录）并安装 3 个 hook 脚本：
- `evolver-session-start.js`: SessionStart hook，注入最近 5 次进化记忆
- `evolver-signal-detect.js`: PostToolUse(Write) hook，实时检测文件编辑中的信号
- `evolver-session-end.js`: Stop hook，录入会话结果到 memoryGraph

`mergeJsonFile()` 用 atomic rename（写 .tmp 再 rename）+ `_evolver_managed` 标记，支持幂等安装和无损卸载。

**A2A Protocol（代理间通信）**: `src/gep/a2aProtocol.js`（混淆，245k tokens）实现 EvoMap Hub 通信协议，支持 hello/heartbeat/event-poll/mailbox 等。`src/atp/` 模块提供 merchantAgent/consumerAgent，实现技能市场的买卖双方逻辑。

**Proxy 架构（本地邮箱代理）**: `src/proxy/` 实现本地 HTTP 代理服务器（默认端口 19820），Agent 只与本地 proxy 通信，proxy 负责认证+重试+消息同步。SKILL.md 中明确：**Agent 不直接调用 Hub API**，全部走 `localhost:19820`。

**SkillPublisher（技能发布）**: 将 Gene 对象转换为 SKILL.md 格式，自动推导 kebab-case 名称，支持上传到 EvoMap 技能市场。

### 2.5 状态持久化

所有状态文件在 `memory/evolution/` 目录，使用 atomic write 模式（先写 .tmp 再 fs.renameSync）：

| 文件 | 内容 | 格式 |
|------|------|------|
| `memory_graph.jsonl` | 信号→结果历史 | JSONL append |
| `evolution_solidify_state.json` | 最近一次 solidify 状态（用于断点恢复） | JSON |
| `narrative_memory.jsonl` | 叙事摘要 | JSONL |
| `reflections.jsonl` | 反思记录 | JSONL |
| `curriculum_state.json` | 学习目标进度 | JSON |
| `idle_schedule_state.json` | 闲置调度状态 | JSON |
| `personality_models.json` | 多人格模型 | JSON |
| `issue_reporter_state.json` | 问题上报冷却状态 | JSON |
| `self_pr_state.json` | 自 PR 冷却和 diff 去重 | JSON |
| `distiller_state.json` | 蒸馏进度 | JSON |

`evolution_solidify_state.json` 的 `last_run`/`last_solidify` 字段实现了**断点恢复**：如果 run_id 不匹配，说明有 pending evolution 未被 solidify（可能 crash），启动时自动 auto-reject。

**Session Archive**: 当 session 日志超过 `SESSION_ARCHIVE_TRIGGER=100` 条时，触发归档（保留最近 50 条），防止 memory/ 无限膨胀。

### 2.6 版本化/发布机制

**版本号**: SemVer，package.json 中维护，当前 1.63.0，MINOR 版本说明从初始版本已有 63 次特性级更新。

**公开发布流水线**:
- `npm run build` → 混淆核心模块
- `npm run publish:public` → 推送到 `PUBLIC_REPO`（EvoMap/evolver），可选创建 GitHub Release
- 混淆列表在 `selfPR.js` OBFUSCATED_FILES 集合中精确控制

**Schema 版本**: `contentHash.js` 定义 `SCHEMA_VERSION=1.6.0`，所有 EvolutionEvent/ValidationReport/Gene/Capsule 资产都携带 `schema_version` 字段，Hub 端可做向后兼容处理。

**Asset ID 计算**: `computeAssetId()` 基于内容 canonical JSON 的 sha256，保证相同内容不重复存储。

---

## 三、五层深度分析（核心模块）

### signals.js — 信号提取引擎

**Layer 1**: 代码级观察，`_extractRegex()` 函数 ~300 行，工具滥用检测（`bypassPatterns`）最为精妙：通过 `exec:.*$` 匹配行中的 `node xxx.js / npx / python xxx.py / curl.*api` 判断 AI 有没有绕过工具层用 shell 直接跑脚本。

**Layer 2**: `SIGNAL_PROFILES` 权重表设计合理，`perf_bottleneck` 中 `oom`=5 最高，`slow`=3 次之，单一词不触发，需要累积证据。`threshold=6` 的门槛过滤了单词误报。

**Layer 3**: LLM 分析用 `execSync` 同步调用是刻意设计（注释明确说明原因），每 5 轮才调一次，不影响主循环性能。

**设计亮点**: `suppressedSignals` 去重机制直接回答了"为什么不陷入无限修同一个 bug 的循环"——同一信号连续出现 3+ 次就被压制，注入 `evolution_stagnation_detected` 迫使创新。

### strategy.js — 策略调度器

6 种策略 + `repairLoopThreshold` 组成一个简洁的自适应调度器。`steady-state` 策略是"退化到维护模式"的兜底，Explore 比例从 10% 升到 15% 说明饱和状态下系统主动寻找新方向。

信号系统和策略系统解耦清晰：信号描述"世界发生了什么"，策略描述"我们当前想做什么"，两者在 Selector 中结合。

### solidify.js — 固化验证引擎

最大的模块（混淆后 291k tokens），是整个系统的安全核心。关键设计：
- `isValidationCommandAllowed()` 的 5 条规则是硬性约束，不是建议
- `BLAST_RADIUS_HARD_CAP_FILES/LINES` 是全局上限，绕不过去
- canary check（fork 子进程）比 require 更安全，避免模块缓存污染
- `buildSoftFailureLearningSignals()` 将失败原因转为可学习的信号，失败不白失

### memoryGraph.js — 预测性记忆

`computePredictiveBoost()` 的 Bayesian 思路：给定当前信号集合，计算该基因历史使用成功率 × 置信区间，返回 0-0.3 的分数提升。当 memoryGraph 数据不足时返回 0（不影响 Selector 正常工作）。

`checkEpochBoundary()` 分代防止过拟合：每过一个 epoch（可能是固定轮数或成功率变化），旧的偏好权重打折扣，系统不会永远偏向曾经成功的基因。

### hookAdapter.js + claudeCode.js — 平台集成层

`deepMerge()` + atomic write + `_evolver_managed` 标记的三件套解决了"如何安全安装到已有 settings.json"的经典问题。卸载时能精确移除自己注入的内容，不影响用户原有配置。

Claude Code 集成的 3 个 hook 时机选择精确：
- SessionStart：注入记忆（让 agent 知道历史经验）
- PostToolUse(Write)：实时检测（在编辑文件时捕获信号）
- Stop：录入结果（会话结束时固化本次经验）

---

## 四、可偷模式提取

### P0 — 立即可用，填补结构性缺口

#### 1. 三层信号提取（Regex + Score + LLM）

**当前 Orchestrator**: hooks 里有简单的关键词检测，但没有加权 scoring，没有信号去重历史，没有 LLM 补充层。

**Evolver 的做法**: `SIGNAL_PROFILES` 权重表 + threshold 门槛是精华。关键词 → 权重分 → 阈值触发，比 if/else 检测鲁棒得多。

**适配方案**: 把 `SIGNAL_PROFILES` 的设计引入 `audit.sh` 或新建 `signal-extractor.py`，对 session log 做加权扫描。中英日三语覆盖直接复用。

**参考代码**: `src/gep/signals.js` L150-195（SIGNAL_PROFILES 定义）+ L197-223（_extractKeywordScore）

#### 2. 信号历史去重（Anti-Repair-Loop）

**当前 Orchestrator**: 没有跨会话信号去重，理论上会对同一问题反复生成相同建议。

**Evolver 的做法**: `analyzeRecentHistory()` 分析最近 8-10 个事件，signal 出现 ≥3 次 → `suppressedSignals` → 过滤 → 注入 `evolution_stagnation_detected`。连续 repair ≥3 次 → 强制创新。

**适配方案**: 在 `experiences.jsonl` 读取逻辑中加历史频率检查，同类型建议已经出现 3+ 次 → 标记为 suppressed，触发"换角度思考"信号。

**参考代码**: `src/gep/signals.js` L33-141（analyzeRecentHistory）

#### 3. 闲置感知调度（OMLS-inspired IdleScheduler）

**当前 Orchestrator**: 无闲置感知，任何时候行为一致。

**Evolver 的做法**: 检测系统 idle 时间（Win/macOS/Linux），idle ≥5min → `aggressive`（触发蒸馏+反思），idle ≥30min → `deep`（触发更深度操作）。sleep_multiplier 0.25x 表示越闲运转越快。

**适配方案**: 在 Orchestrator 后台任务（如 loop-detector、定期 review）中引入 idle 检测，利用 idle 窗口做记忆整理、experience 去重、Skill 萃取等重度操作。

**参考代码**: `src/gep/idleScheduler.js`（完整文件，145行，可直接复用 Win/macOS/Linux 三平台实现）

#### 4. Solidify 验证模式（命令白名单 + Canary + ValidationReport）

**当前 Orchestrator**: verification-gate 是概念性的，但没有机器可验证的验证链。

**Evolver 的做法**: Gene 声明 `validation[]` 命令，solidify 时执行，通过才固化。canary 在 fork 中验证主入口不崩溃，全程有 ValidationReport 结构化记录。

**适配方案**: 在 Orchestrator 的 task completion 流程中引入 Gene-style 验证声明。Skill 可以在 SKILL.md 中声明 `validation` 命令（白名单：只允许 python/node/npm），执行后生成 ValidationReport 写入 experiences。

**参考代码**: `src/gep/policyCheck.js` 的 `isValidationCommandAllowed()` 5 条规则

### P1 — 值得偷但需要设计

#### 5. EvolutionEvent 审计链（GEP 核心设计）

**描述**: 每次进化 append 一条 EvolutionEvent 到 JSONL，含亲代指针（`parent` 字段）、信号快照、mutation 描述、blast_radius 实测值、validation 结果、outcome score。

**为什么值得**: Orchestrator 的 `experiences.jsonl` 结构相对扁平，缺少 parent 链 + blast_radius + mutation 描述。GEP 的事件结构可以完整回答"这次改了什么、为什么改、改了多大、结果怎样"。

**适配方案**: 扩展 experiences.jsonl 条目结构，增加 `parent_id`、`mutation`（描述本次意图）、`blast_radius`（git diff 统计）、`validation_commands_ok` 字段。

**成本估计**: 中等——需要修改 experiences 写入逻辑，但不破坏现有读取。

#### 6. Gene/Capsule 资产体系（可复用策略库）

**描述**: Gene 是可复用的策略模板（带 signals_match + strategy + constraints + validation），Capsule 是具体成功案例快照。两者组合：Gene 告诉 AI"应该怎么做"，Capsule 告诉 AI"上次怎么做成的"。

**为什么值得**: Orchestrator 的 Skill 定义偏向"工具能做什么"，缺少"在什么信号下应该用什么策略"的 Gene 层。GEP 的 Gene 相当于 Orchestrator 的 SKILL.md + 触发条件 + 验证命令的三合一。

**适配方案**: 在每个 `.claude/skills/<skill>/` 下加 `gene.json`，定义 signals_match + validation。skill_routing.md 成为 Gene selector 的人工版本，可以逐步自动化。

**成本估计**: 大——需要对现有技能体系做结构化改造。

#### 7. 技能蒸馏（SkillDistiller AutoDistill）

**描述**: 分析成功 Capsule 的模式，当多个 Capsule 有相似信号+策略时，自动合成新 Gene，命名 `gene_distilled_` 前缀，发布到 Hub。

**为什么值得**: 这是"知识自动化提炼"的核心机制——重复的成功模式不再只存在于 experiences，而是被提炼为可主动引用的 Gene。

**适配方案**: 在 Orchestrator 的 collect skill 逻辑中，当某类任务成功率持续高时，触发蒸馏流程，生成新的 SKILL.md + gene.json。需要 LLM 辅助（buildDistillationPrompt → LLM 合成）。

**成本估计**: 大，需要新的蒸馏流水线。但 `skillDistiller.js` 的 `buildDistillationPrompt()` + `extractJsonFromLlmResponse()` 可以直接参考实现。

### P2 — 远期参考

#### 8. Personality State（可进化人格参数）

5 维人格向量（rigor/creativity/verbosity/risk_tolerance/obedience）+ 历史加权更新。现阶段 Orchestrator 的声音校准是静态的，这个机制可以让它根据用户反馈自动调整。

#### 9. SelfPR 自动贡献

分数 ≥0.85 + streak ≥3 + 改动小 → 自动向上游提 PR。这是 Orchestrator "经验共享到 Orchestrator 主仓"的自动化机制原型。

#### 10. Curriculum（主动学习目标）

当信号稀疏时系统自行注入学习目标，驱动主动探索。类似 Orchestrator 的 `explore_opportunity` 信号逻辑，但有显式的目标追踪和进度记录。

---

## 五、路径依赖分析

### 5.1 "Evolver 不改代码"的定位边界

Evolver 最核心的定位决定了它的所有设计：**它是 prompt 生成器，不是代码执行器**。这个决定让它：
- 天然解决了"AI 改了 AI 的代码"的安全噩梦（混淆 + forbidden_paths + 白名单）
- 代价是必须依赖宿主 runtime（OpenClaw）来实际执行修改

Orchestrator 要"偷"这套思路，但不需要完全复制这个分层——Orchestrator 本身就是执行者，可以直接让 verification-gate 兼具 solidify 的功能。

### 5.2 GEP 协议的可移植性

GEP 的核心洞见是：**进化操作必须有结构化的事前声明（Gene）+ 事后验证（ValidationReport）+ 审计记录（EvolutionEvent）三件套**，缺一不可。

当前 Orchestrator 有审计记录（experiences）但缺事前声明（Gene 层）和结构化事后验证（ValidationReport）。补齐 Gene 层和 ValidationReport 是最高价值的单点改进。

### 5.3 三层信号架构的可移植性

Layer 1（Regex）和 Layer 2（Score）完全不需要外部依赖，可以直接移植为 Python/Shell 脚本集成到 hooks。Layer 3（LLM）需要 Hub 连接，对 Orchestrator 而言可以替换为直接调用本地 LLM 或跳过。

### 5.4 Hub 网络的中心化风险

EvoMap Hub 是整个生态的中心节点——信号分析、技能市场、评估、任务分发都依赖 Hub。Proxy 架构虽然提供了本地离线降级，但高级功能（semantic search、LLM review、skill publishing）都是 Hub 依赖的。

Orchestrator 的去中心化设计（本地 DB + git 历史）反而是优势，不需要依赖外部 Hub 才能运转。

---

## 六、与 Orchestrator 现有能力对比

| 维度 | Evolver v1.63.0 | Orchestrator 现状 |
|------|-----------------|-------------------|
| 信号提取 | 3层(Regex+Score+LLM) + 多语言 | hooks 简单 if/else 检测 |
| 信号去重 | 历史频率分析，≥3次压制 | 无跨会话去重 |
| 策略调度 | 6种预设 + repairLoopThreshold | EVOLVE_STRATEGY 有类似概念 |
| 进化资产 | Gene+Capsule+Event 三类型 | experiences.jsonl 扁平记录 |
| 事后验证 | ValidationReport + canary | verification-gate 概念性 |
| 审计链 | parent_id + blast_radius 完整链 | experiences 无亲代指针 |
| 记忆预测 | memoryGraph 贝叶斯先验 | 无预测性提升 |
| 元反思 | 每N轮 reflection + 建议生成 | 无自动反思触发 |
| 技能蒸馏 | idle 触发，合成新 Gene | 无自动蒸馏 |
| 平台集成 | Cursor/Claude-Code/Codex 适配器 | Claude Code 专属 |
| 凭据保护 | fullLeakCheck 广泛模式 | env-leak-scanner.sh |
| 自提 PR | score+streak 门控，自动提 PR | 无 |
| 闲置感知 | 3平台 idle 检测，调整强度 | 无 |
| 单例保护 | PID 文件 + kill(0) 探测 | 无进程单例保护 |

---

## 附：关键文件索引

```
D:/Agent/.steal/evolver/
├── index.js              # 主入口：循环/单次/review/solidify 命令
├── src/config.js         # 全局配置，所有阈值，支持 env override
├── src/evolve.js         # (混淆) 进化循环核心编排
├── src/gep/
│   ├── signals.js        # ★ 三层信号提取 (Regex+Score+LLM)
│   ├── strategy.js       # ★ 6种策略预设
│   ├── selector.js       # (混淆) Gene 选择器
│   ├── mutation.js       # (混淆) Mutation 构建器
│   ├── solidify.js       # (混淆) 固化验证引擎
│   ├── prompt.js         # (混淆) GEP prompt 组装
│   ├── policyCheck.js    # ★ blast_radius + 命令白名单 (混淆)
│   ├── memoryGraph.js    # (混淆) 预测性记忆
│   ├── personality.js    # (混淆) 人格状态
│   ├── reflection.js     # (混淆) 元反思
│   ├── curriculum.js     # (混淆) 课程目标
│   ├── skillDistiller.js # (混淆) 技能蒸馏
│   ├── idleScheduler.js  # ★ 闲置感知调度 (明文)
│   ├── sanitize.js       # ★ 凭据脱敏 (明文，含20+模式)
│   ├── validationReport.js # ★ ValidationReport 类型定义
│   ├── selfPR.js         # ★ 自动提PR逻辑 + 混淆文件列表
│   ├── assetStore.js     # Gene/Capsule/Event CRUD
│   ├── gitOps.js         # git diff/numstat/rollback 封装
│   └── contentHash.js    # ★ SHA-256 资产 ID，schema 1.6.0
├── src/adapters/
│   ├── hookAdapter.js    # ★ 平台无关 hook 安装框架
│   ├── claudeCode.js     # ★ Claude Code 适配器
│   └── scripts/          # 3 个 hook 脚本 (明文)
├── src/ops/
│   ├── lifecycle.js      # 进程生命周期管理
│   └── self_repair.js    # git 紧急修复
├── src/proxy/            # 本地 EvoMap 代理服务器
└── assets/gep/
    ├── genes.json        # 3 个内置 Gene 定义
    └── events.jsonl      # 进化事件历史（示例数据）
```

---

*R72 — 分析完成。核心偷点按优先级排序：三层信号提取（P0）> 信号历史去重（P0）> 闲置感知调度（P0）> Solidify 验证白名单（P0）> GEP 审计链结构（P1）> Gene 资产体系（P1）> 技能蒸馏（P1）。*
