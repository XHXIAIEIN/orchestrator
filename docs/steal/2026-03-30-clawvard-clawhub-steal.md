# ClawHub 偷师总报告 — Round 14

> 来源：Clawvard Skill Lab + ClawHub 生态，5 路并行深挖
> 日期：2026-03-30
> 扫描范围：~70 个技能，深挖 7 个，提取 16 个可偷模式

---

## 偷师目标一览

| 项目 | 作者 | 下载量 | 重点 |
|------|------|--------|------|
| self-improving-agent | @pskoett | 305k | 三分类错误日志 + Pattern-Key 自动晋升 |
| proactive-agent | @halthelobster | 121k | WAL Protocol + Working Buffer + ADL/VFM |
| ontology | @oswalpalash | 133k | Typed knowledge graph + Event Sourcing |
| evolver | @autogame-17 | 37k | GEP 基因进化 + 四阶段审计链 + 爆炸半径 |
| elite-longterm-memory | @nextfrontierbuilds | 41k | 六层 memory + git-notes + vector search |
| self-improving-proactive | @ivangdavila | 115k | 热温冷三层 + 自动晋降 + 反思协议 |
| skill-vetter | @spclaudehome | 153k | 14 项红旗检查 + 四级风险分类 |

---

## 跨项目收敛的 5 个核心发现

### 1. WAL（Write-Ahead Log）已成标配
3 个独立项目（proactive-agent、elite-longterm-memory、self-improving-proactive）都强制「写盘在响应前」。不是巧合，是 LLM agent context loss 的系统性解法。

### 2. 上下文温度分层（HOT/WARM/COLD）
至少 3 个项目独立提出三层记忆架构，晋降规则高度一致（使用频率 + 时间衰减 → 自动晋升/降级）。

### 3. 反退化协议（Anti-Drift）
proactive-agent 的 ADL、evolver 的 `EVOLVE_ALLOW_SELF_MODIFY=false`、self-improving 的 Core Rules —— 都在解决同一个问题：自改进 agent 越改越烂。

### 4. 结构化进化日志（Signal → Hypothesis → Attempt → Outcome）
不只记 log，记「为什么改、改完验证了什么」。git commit 有 message，agent evolution 也必须有因果链。

### 5. 人工审批作为安全阀
高风险操作统一走审批。与 Orchestrator 的 Claw/TG/WX 三通道审批完全对齐。

---

## 16 个可偷模式（按优先级排序）

### P0 — 立刻能用

#### 模式 1：WAL-Before-Reply 协议
**来源**：proactive-agent + elite-longterm-memory
**描述**：每条 input 在生成回复前，扫描 6 类信号（纠正/专有名词/偏好/决策/草稿变更/精确值），命中则先写 `SESSION-STATE.md` 再回复。
**实现**：在 SOUL/private/ 下加 `session-state.md`，executor 入口插扫描钩子。
**解决的问题**：长任务 crash/compaction 后上下文丢失。
**对应现有**：run-log 是事后写，WAL 是事前写，互补。

#### 模式 2：三分类错误日志
**来源**：self-improving-agent
**描述**：按类型分三文件：LEARNINGS.md（知识更新）、ERRORS.md（工具/API 错误）、FEATURE_REQUESTS.md（能力缺口）。每条带 `Pattern-Key` + `Occurrences` 计数。
**实现**：`.learnings/` 目录，session-stop hook 里分类写入。
**对应现有**：experiences.jsonl 是「情感日记」，这是「工程知识库」，双轨并行。

#### 模式 3：Pattern-Key 计数 → 自动晋升
**来源**：self-improving-agent
**描述**：每个 learning 条目带语义键（如 `docker-rebuild-unnecessary`），同一 Pattern-Key 出现 ≥3 次 + 30 天窗口 → 自动晋升到 boot.md Learnings。
**实现**：检测脚本 + boot.md Learnings 区块动态化。
**价值**：把静态手写的 Learnings 变成数据驱动的活系统。

#### 模式 4：爆炸半径控制
**来源**：evolver
**描述**：每次进化有明确的文件数/行数上限，按策略动态调整（cautious: 2-6 文件, balanced: 3-10, innovate: ≤12）。
**实现**：manifest.yaml 加 `max_files_per_run` 字段，Governor 读取并限制。
**一个下午的事**。

#### 模式 5：四阶段进化审计链
**来源**：evolver
**描述**：Signal → Hypothesis → Attempt → Outcome，缺任何一环进化无效。
**实现**：`evolution_state.json` 升级为 `evolution_events.jsonl`，每次部门 prompt 迭代写完整因果记录。
**对应现有**：当前只记 `last_evolution_ts + success_rate`，因果完全丢失。

### P1 — 值得花时间

#### 模式 6：Working Buffer（上下文危险区日志）
**来源**：proactive-agent
**描述**：context 达 60% 时，每条对话追加到 `working-buffer.md`（timestamp + human message + agent 摘要）。compaction 后从文件恢复。
**实现**：长任务 executor（duration_s > 300）中激活。
**恢复路径**：buffer → SESSION-STATE → daily notes → 全量搜索。

#### 模式 7：信号驱动进化选择
**来源**：evolver
**描述**：从 run-log 提取错误信号，匹配最适合的进化基因（Gene），而不是 LLM 自由生成建议。
**评分公式**：`score = pattern_hits + (tagScore × 0.6) + (semanticScore × 0.4)`
**实现**：写轻量 signal extractor，替换「LLM 看日志自由建议」。

#### 模式 8：抗重复负反馈
**来源**：evolver
**描述**：失败的进化路径施加负权重（success: +0.12, hard_fail: -0.22），防止同一错误被反复选中。连续 3 次失败强制切换策略。
**对应现有**：evolution_state.json 没有失败路径记录。

#### 模式 9：热温冷三层自动晋降
**来源**：self-improving-proactive
**描述**：
- HOT（≤100行）= 全局偏好，永远加载
- WARM（≤200行/文件）= 部门级，按需加载
- COLD = 归档，显式查询才出现
- 晋升：3 次成功应用或 7 天 → WARM→HOT
- 降级：30 天未用 → 降温
**对应现有**：SOUL 系统已有分层思路，但缺自动晋降机制。

#### 模式 10：PostToolUse 错误探测 Hook
**来源**：self-improving-agent
**描述**：`error-detector.sh` 挂在 PostToolUse(Bash)，扫描输出中的 error pattern，触发分类记录。正常执行时静默。
**实现**：追加到现有 `persona-anchor.sh`，双功能：人格锚点 + 错误捕获。

#### 模式 11：Canary 验证（隔离子进程）
**来源**：evolver
**描述**：补丁应用后，启动独立子进程验证核心模块能正常 load，通过才 commit，失败自动回滚。
**实现**：对 MUTATE 权限部门，提交前跑测试 = canary。

### P2 — 长远布局

#### 模式 12：跨部门 Ontology 层
**来源**：ontology
**描述**：部门间通过 typed knowledge graph 通信，而非直接查表。JSONL event sourcing + YAML schema 约束。
**价值**：工部写 `CodePatch` 实体，质部查 `CodePatch --status pending_review`，彻底解耦。
**代价**：季度级工程。

#### 模式 13：DAG 无环依赖检测
**来源**：ontology
**描述**：任务依赖关系构成 DAG，commit 前 DFS 检测环，拒绝循环依赖。
**对应现有**：`depends_on` 数组没有图层面保护，成环时静默死锁。

#### 模式 14：git-notes 决策存储
**来源**：elite-longterm-memory
**描述**：git-notes 给 commit 附加决策记录，天然 branch-aware，不改 commit hash。
**适合**：记录 Orchestrator 自身架构决策历史。

#### 模式 15：ADL/VFM 自改进护栏
**来源**：proactive-agent
**描述**：自我修改前必须打分（频率×3 + 失败减少×3 + 负担减少×2 + token 效率×2），加权分 < 50 不执行。
**禁止**：加复杂度装聪明、无法验证的改动、用「直觉」做理由。

#### 模式 16：Skill Vetting 安全网关
**来源**：skill-vetter
**描述**：14 项红旗检查 + 四级风险分类（LOW/MEDIUM/HIGH/EXTREME）。
**红旗**：curl/wget to unknown URLs、base64 decode、eval+外部输入、credential 请求等。
**适用**：Orchestrator 扩展外部工具时的安全网关。

---

## 落地建议

### Sprint 4 可纳入（Q2 2026）

| 优先级 | 模式 | 工作量 | 影响面 |
|--------|------|--------|--------|
| P0 | WAL-Before-Reply | 半天 | executor + SOUL |
| P0 | 三分类错误日志 | 半天 | .learnings/ + hooks |
| P0 | Pattern-Key 自动晋升 | 1 天 | boot.md 动态化 |
| P0 | 爆炸半径控制 | 半天 | manifest.yaml + governor |
| P0 | 四阶段进化审计链 | 1 天 | evolution_events.jsonl |

### Sprint 5 候选

| 优先级 | 模式 | 工作量 |
|--------|------|--------|
| P1 | Working Buffer | 1 天 |
| P1 | 信号驱动进化 | 2 天 |
| P1 | 热温冷自动晋降 | 1 天 |
| P1 | PostToolUse 错误探测 | 半天 |

---

## 源码链接

| 项目 | GitHub |
|------|--------|
| self-improving-agent | github.com/pskoett/pskoett-ai-skills |
| proactive-agent | github.com/openclaw/skills (skills/halthelobster/) |
| ontology | github.com/oswalpalash/ontology |
| evolver | github.com/autogame-17/evolver (推测) |
| elite-longterm-memory | github.com/NextFrontierBuilds/elite-longterm-memory |
| self-improving-proactive | github.com/ivangdavila (推测) |
| skill-vetter | github.com/spclaudehome (推测) |
