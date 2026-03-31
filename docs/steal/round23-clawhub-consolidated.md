# Round 23: ClawHub Skill Lab 偷师总报告

**日期**: 2026-03-31
**分支**: `steal/round23-clawhub`
**目标**: Clawvard Skill Lab 全部 21 个 ClawHub 技能
**方法**: 21 路并行 agent 深入源码/prompt 提取可偷模式

---

## 总览

| 指标 | 数值 |
|------|------|
| 技能数 | 21 |
| 提取模式总数 | 120+ |
| P0 模式 | 42 |
| P1 模式 | 45+ |
| P2 模式 | 30+ |
| 新发现结构性缺口 | 8 |

---

## P0 模式总索引（按主题聚类）

### 🔒 安全与防护（9 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 1 | **SOUL/Private 路径保护** | skill-vetter | MEMORY.md/SOUL.md/IDENTITY.md 列为 red flag，我们最核心资产竟无保护 | 2h |
| 2 | **14条 Red Flag 检查清单** | skill-vetter | curl到IP/eval外部输入/sudo/读.ssh/.aws 等系统性拦截规则集 | 4h |
| 3 | **Permission Scope 四维分析** | skill-vetter | Read/Write/Execute/Network 四维权限审计 | 1d |
| 4 | **四级风险分类** | skill-vetter | GREEN/YELLOW/RED/EXTREME 替代二元 allow/block | 4h |
| 5 | **Committer-Guard** | steipete/github | 专用脚本禁止 `git add .`、commit前清staging、stale lock恢复 | 4h |
| 6 | **Blast Radius Gate** | evolver | 改动前预估影响范围，超阈值需要确认 | 1d |
| 7 | **反操控条款** | self-improving-proactive | 禁止学习"什么让用户更顺从"/"情感触发点"，认知安全边界 | 2h |
| 8 | **Constraint-Before-Commit** | ontology | 写入前校验（防 secret 明文、类型约束）| 4h |
| 9 | **Allowlist Sandbox** | gog | per-agent 命令白名单，声明式 tool_allowlist | 4h |

### 🧠 记忆与学习（8 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 10 | **Error Detection Hook** | self-improving-agent | PostToolUse 检测非零退出码，自动写 DB | 2h |
| 11 | **Correction Detection** | self-improving-agent | 检测用户纠正语义("不对"/"actually")，记为 correction | 4h |
| 12 | **五阶段 Pattern Evolution** | self-improving-proactive | Tentative→Emerging→Pending→Confirmed→Archived，记忆有生命周期 | 1d |
| 13 | **主动确认流程** | self-improving-proactive | 同一纠正出现3次时主动问用户"要固定吗？" | 4h |
| 14 | **Typed Entity Memory** | ontology | 给 SOUL 加 graph 层，markdown给人看+graph给agent查 | 2d |
| 15 | **子Agent上下文透传** | elite-longterm-memory | memory_tier.py → Governor dispatch 管道接通 | 1h |
| 16 | **Daily Log 归档** | elite-longterm-memory | session结束时沉淀到 memory/YYYY-MM-DD.md | 4h |
| 17 | **Memory Hygiene** | elite-longterm-memory | 清理机制，记忆只增不减迟早噪声淹没信号 | 1d |

### 🔄 工作流与执行（10 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 18 | **Iron Law Gate（调试门禁）** | superpowers/debugging | Phase 1 未完成不能 propose fix，硬门禁 | 4h |
| 19 | **3-Attempt Architectural Escalation** | superpowers/debugging | 3次fix失败→停止，输出报告交用户 | 2h |
| 20 | **Iron Law 删除制（TDD）** | superpowers/TDD | 先写了实现？删掉重来，封杀6种绕过方式 | 4h |
| 21 | **Gate Function 门控** | superpowers/TDD | 危险操作前插入 IF-THEN 决策树，泛化到删除/rollback | 4h |
| 22 | **合理化免疫表** | superpowers/TDD | 12+条"借口→反驳"对照表，堵死AI自我说服 | 2h |
| 23 | **原子步骤粒度** | superpowers/plans | 2-5min/step，路短到不可能迷路 | 2h |
| 24 | **No Placeholder 铁律** | superpowers/plans | 计划中禁止模糊指令，每步可独立执行 | 2h |
| 25 | **Slash-Command-as-Workflow** | steipete/github | 每个命令是7-12步端到端可执行脚本 | 1d |
| 26 | **Verification Gate 五步证据链** | superpowers | 识别命令→运行→读输出→确认→声明，禁止"should" | 4h |
| 27 | **Spec Self-Review 内联清单** | superpowers | 设计文档写完后内联扫描placeholder/矛盾/范围膨胀 | 2h |

### 🔍 审查与质量（5 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 28 | **Context Isolation** | superpowers/review | reviewer 只拿 SHA+plan+summary，不看执行过程 | 4h |
| 29 | **Anti-Sycophancy Protocol** | superpowers/review | 硬编码禁止表演式认同，只接受技术陈述或技术推回 | 2h |
| 30 | **Source-Specific Trust** | superpowers/review | human/internal_agent/external 三级信任分流 | 4h |
| 31 | **双阶段 Review 门禁** | superpowers | 先 spec compliance 后 code quality，不可逆 | 4h |
| 32 | **Ground-Truth-First** | super-design | 改UI前先像素级复现现有状态作基线 | 2h |

### 📡 数据与搜索（5 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 33 | **URL-Template Engine Registry** | multi-search-engine | 结构化搜索引擎知识注入agent context | 2h |
| 34 | **CN/Global 双轨搜索** | multi-search-engine | WeChat/头条/集思录——中文内容盲区 | 2h |
| 35 | **Extraction-Before-Summarization** | summarize | 采集和处理彻底解耦，中间产物可缓存/调试 | 1d |
| 36 | **Cascading Fallback Chain** | summarize | 每种输入3-5层降级，local-first | 1d |
| 37 | **Length Spec 量化约束** | summarize | target/min/max字符数+格式指令，替代模糊"短/中/长" | 4h |

### 🏗️ 架构与设计（5 个 P0）

| # | 模式 | 来源 | 描述 | 实施难度 |
|---|------|------|------|---------|
| 38 | **Scope Ladder 权限阶梯** | gog | 认证时按 readonly/file/full 锁死 scope | 4h |
| 39 | **Stable Output Contract** | gog | agent 声明输出格式，dispatcher 按消费者选格式 | 4h |
| 40 | **Snapshot-Ref 寻址** | agent-browser | accessibility tree → ref ID，10x context 压缩 | 1d |
| 41 | **Multi-Dimension Weighted Scoring** | stock-analysis | 加权多维评分框架，可用于agent绩效/偷师分级/任务优先级 | 1d |
| 42 | **Compaction Recovery** | proactive-agent | 主进程context丢失时的确定性恢复链 | 4h |

---

## 八大结构性缺口

| # | 缺口 | 严重度 | 发现来源 | 现状 |
|---|------|--------|---------|------|
| 1 | **SOUL/Private 无保护** | 🔴 Critical | skill-vetter | 核心资产零防护，任何agent可读取/外发 |
| 2 | **调试方法论从0到1** | 🔴 Critical | superpowers/debugging | 遇bug全靠直觉，无前置调查门禁 |
| 3 | **记忆只增不减** | 🟡 High | elite-longterm-memory | 无清理/归档/衰减机制，噪声累积 |
| 4 | **被动学习 vs 主动学习** | 🟡 High | self-improving-* | 所有记忆靠用户手写，agent不检测纠正信号 |
| 5 | **重执行轻计划** | 🟡 High | superpowers/plans | 御史台审执行，没人审计划质量 |
| 6 | **Review 反馈盲目执行** | 🟡 High | superpowers/review | 无反谄媚协议，rework loop会盲目同意reviewer |
| 7 | **CN搜索盲区** | 🟠 Medium | multi-search-engine | WeChat/头条/集思录完全不可见 |
| 8 | **英文 deslop 检测空白** | 🟠 Medium | humanizer | deai_writer.py 只覆盖中文 |

---

## 21 个技能偷师摘要

| # | 技能 | 作者 | P0数 | 核心洞察 |
|---|------|------|------|---------|
| 1 | self-improving-agent | @pskoett | 3 | 有仓库没进货渠道——感知层空白 |
| 2 | summarize | @steipete | 3 | 采集/处理解耦 + 级联降级 + 量化长度约束 |
| 3 | agent-browser | @thesethrose | 2 | tool输出为AI context优化，不是人类可读性 |
| 4 | skill-vetter | @spclaudehome | 4 | SOUL文件保护缺口 + 14条安全红旗 |
| 5 | gog | @steipete | 4 | 零抽象只做认证注入的克制哲学 |
| 6 | ontology | @oswalpalash | 2 | markdown给人看 + graph给agent查的双层设计 |
| 7 | github/agent-scripts | @steipete | 4 | 命令即工作流 + Committer-Guard 硬约束 |
| 8 | proactive-agent | @halthelobster | 2 | 协议闭环缺后半段（Recovery+Heartbeat+Reverse Prompting）|
| 9 | self-improving-proactive | @ivangdavila | 3 | 五阶段记忆生命周期 + 反操控条款 |
| 10 | multi-search-engine | @gpyangyoujun | 3 | 17引擎URL模板 + CN搜索盲区 |
| 11 | humanizer | @biostartechnology | 1 | 英文AI写作检测24条规则，我们只有中文 |
| 12 | super-design | @mpociot | 3 | Ground-Truth-First + SOP约束AI不发散 |
| 13 | stock-analysis | @udiedrichsen | 3 | 加权多维评分元模式 + 安全红旗反面教材 |
| 14 | elite-longterm-memory | @nextfrontierbuilds | 3 | 上下文透传管道断裂 + Daily Log + Hygiene |
| 15 | api-gateway | @byungkyu | 3 | 零抽象透明网关 + Control/Data双平面 |
| 16 | evolver | @autogame-17 | 4 | GEP进化协议 + Blast Radius Gate + 40轮dogfooding |
| 17 | superpowers (核心) | @obra | 4 | 2-5min粒度任务+零placeholder+每步验证=自主数小时 |
| 18 | superpowers/debugging | @obra | 3 | Iron Law门禁 + 3次失败升级 + 冗余认知摩擦 |
| 19 | superpowers/TDD | @obra | 3 | 门控决策树 + 合理化免疫表可泛化到所有危险操作 |
| 20 | superpowers/plans | @obra | 2 | 重执行轻计划 = 完美做错事 |
| 21 | superpowers/review | @obra | 3 | 反谄媚协议 + 上下文隔离 + 来源分级信任 |

---

## 实施路线建议

### 本周（安全+基础设施）
1. `guard-redflags.sh` — 14条 red flag + SOUL路径保护 (P0 #1-2)
2. `systematic-debugging` skill — Iron Law + 3-Attempt (P0 #18-19)
3. 反谄媚协议写入 review guidelines (P0 #29)
4. memory_tier → Governor 管道接通 (P0 #15, 1h)

### 下周（工作流升级）
5. 合理化免疫表 — 泛化到 Git Safety/删除/核心文件修改 (P0 #22)
6. Verification Gate 五步证据链 (P0 #26)
7. Error/Correction Detection hooks (P0 #10-11)
8. 计划模板 + No Placeholder 铁律 (P0 #23-24)

### 下下周（记忆系统升级）
9. 五阶段 Pattern Evolution (P0 #12)
10. Memory Hygiene 清理机制 (P0 #17)
11. Daily Log 归档 (P0 #16)
12. CN 搜索引擎 registry (P0 #33-34)

### 远期（架构级）
13. Typed Entity Memory 双层设计 (P0 #14)
14. Cascading Fallback Chain 通用框架 (P0 #36)
15. Multi-Dimension Weighted Scoring 评分框架 (P0 #41)

---

## 详细报告索引

| 技能 | 报告位置 |
|------|---------|
| self-improving-agent | `docs/steal/2026-03-31-self-improving-agent.md` |
| summarize | (inline report — agent output) |
| agent-browser | `memory/steal_round23_agent_browser.md` |
| skill-vetter | (inline report — agent output) |
| gog | `memory/steal_round23_gog_clawhub.md` |
| ontology | `docs/steal/round23_ontology.md` |
| github/agent-scripts | `memory/steal_round25_steipete_agent_scripts.md` |
| proactive-agent | `docs/steal/2026-03-31-proactive-agent-deep-dive.md` |
| self-improving-proactive | `docs/steal/2026-03-31-self-improving-proactive-deep.md` |
| multi-search-engine | `docs/steal/2026-03-31-round23-multi-search-engine.md` |
| humanizer | `memory/steal_round23_clawhub_humanizer.md` |
| super-design | `memory/steal_round23_superdesign.md` |
| stock-analysis | `docs/steal/2026-03-31-stock-analysis-clawhub.md` |
| elite-longterm-memory | `docs/steal/2026-03-31-elite-longterm-memory.md` |
| api-gateway | `docs/steal/2026-03-31-api-gateway-byungkyu.md` |
| evolver | `memory/steal_round23_evolver.md` |
| superpowers (核心) | `memory/steal_round23_superpowers.md` |
| superpowers/debugging | (inline report — agent output) |
| superpowers/TDD | `memory/steal_round23_superpowers_tdd.md` |
| superpowers/plans | `docs/steal/2026-03-31-superpowers-writing-plans.md` |
| superpowers/code-review | (inline report — agent output) |
