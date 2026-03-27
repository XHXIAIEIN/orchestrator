# Documentation & Knowledge Restructure Design

> 2026-03-28 — 10 轮偷师、90+ 模式、散落三处的研究成果，需要一次系统性整合。

## Problem Statement

### 症状

1. **知识碎片化**：偷师成果散在 memory/（10 个 steal_sheet_*.md）、docs/superpowers/steal-sheets/（3 份深度分析）、tmp/research-2026-03-22/（原始笔记）三个地方
2. **重复严重**：Loop Detection 在 5 个 sheet 出现，Cost Tracking 在 3 个 sheet 出现，Context Compression 在 3 个 sheet 出现
3. **文档职责不清**：CLAUDE.md 里 50% 是 desktop_use 架构文档（87 行），boot.md 和 management.md 有 121 行完全重复
4. **无全局视图**：没有"这些模式怎么组合在一起"的架构图
5. **路线图断裂**：52 个已实施模式没有统一追踪，38 个待实施模式散在各处无优先级

### 根因

每次偷师写新文件，从不回头整合。读多写少的自然结果。

---

## Design

### 目录结构变更

```
docs/
├── architecture/                    ← NEW: 架构知识中枢
│   ├── README.md                    ← 总纲：模块全景 + 设计哲学
│   ├── PATTERNS.md                  ← 模式总表（90+ 模式，带状态追踪）
│   ├── ROADMAP.md                   ← 下阶段路线图（38 个待实施模式排序）
│   ├── fact-expression-split.md     ← 原创研究（从 SOUL/public/ 移入）
│   └── modules/                     ← 按模块的架构文档
│       ├── desktop-use.md           ← 从 CLAUDE.md 抽出的 87 行 + 扩展
│       ├── governance.md            ← 三省六部 + 安全体系
│       ├── channels.md              ← Telegram/WeChat/Chat 层
│       ├── collectors.md            ← 采集器体系
│       ├── browser-runtime.md       ← 浏览器运行时
│       └── storage.md               ← 存储层
│
├── superpowers/                     ← 保持不变
│   ├── plans/                       ← 实施计划（已有 8 个）
│   ├── specs/                       ← 设计文档（已有 4 个 + 本文件）
│   └── steal-sheets/                ← 保持：3 份深度分析原地不动
│
└── research-archive/                ← NEW: 从 tmp/ 毕业
    └── 2026-03-22-orchestrator-survey/  ← mv from tmp/research-2026-03-22/
```

### Layer 1: 知识整合 — PATTERNS.md

**核心产出**：一个权威的模式总表，按主题域组织，不按来源项目。

**结构**：

```markdown
# Pattern Library

## 概览
- 总计：90+ 模式，来自 56+ 项目
- 已实施：52 | 已设计：6 | 待实施：32+

## 1. Safety & Control (安全与控制)
| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| S1 | Taint Tracking 5-tag lattice | OpenFang | 🔲 | — | P1, needs design |
| S2 | Authority Ceiling READ→APPROVE | Round 1 | ✅ | governance/policy/ | |
| S3 | Prompt Injection 14-case suite | Round 2 | ✅ | tests/ | |
| ... | | | | | |

## 2. Reliability & Monitoring (可靠性与监控)
## 3. Performance & Efficiency (性能与效率)
## 4. Intelligence & Learning (智能与学习)
## 5. Resource Management (资源管理)
## 6. Perception & Vision (感知与视觉)
## 7. Orchestration & Routing (编排与路由)
## 8. Human-AI Collaboration (人机协作)

## Cross-Reference: Source → Patterns
（按来源项目反查，方便回溯原始上下文）
```

**状态标记**：
- ✅ 已实施（含代码位置）
- 📐 已设计（指向 specs/ 或 plans/）
- 🔲 待实施（含优先级 P0/P1/P2）
- ⏸️ 搁置（说明原因）

**去重规则**：
- Loop Detection 的 5 个变体 → 合并为 1 条，列出"实现方式"子表
- Cost Tracking 的 3 个变体 → 合并为 1 条，标注演进路径
- 同理 Context Compression、Prompt Injection 等

### Layer 2: 文档架构对齐

#### 2a. CLAUDE.md 瘦身

**Before**（131 行）：
- 8 行引导
- 23 行 working rules
- 87 行 desktop_use 架构文档
- 4 行 Docker rules

**After**（~60 行）：
- 8 行引导（不变）
- 23 行 working rules（不变）
- ~25 行**模块速查表**（每模块 2-3 行摘要 + 指向 docs/architecture/modules/）
- 4 行 Docker rules（不变）

desktop_use 的 87 行架构文档 → `docs/architecture/modules/desktop-use.md`

#### 2b. management.md → boot.md 去重

**现状**：management.md 81 行 = boot.md 60-139 行，100% 重复。

**方案**：
- management.md 保持为 **source of truth**（Decision Principles + Cognitive Modes）
- compiler.py 从 management.md 拉取内容编译进 boot.md
- 验证 compiler.py 已经这样做了（如果是，则无需改动；如果 boot.md 是手动复制的，需修 compiler）

#### 2c. MEMORY.md 清理

**Before**（113 行，10 条 steal_sheet 引用）：

```
- [orchestrator_steal_sheet.md] — 第一轮...
- [orchestrator_steal_sheet_2.md] — 第二轮...
...（×10）
```

**After**（~95 行，1 条整合引用）：

```
## 偷师研究（已整合）

- [orchestrator_steal_consolidated.md](orchestrator_steal_consolidated.md) — 10 轮偷师总索引（56 项目 / 90+ 模式），详细模式表见 `docs/architecture/PATTERNS.md`
```

**操作**：
1. 新建 `orchestrator_steal_consolidated.md`：每轮 3-5 行摘要（来源、核心收获、实施状态比）
2. 10 个原始 steal_sheet_*.md → 移到 `.trash/2026-03-28-steal-sheet-consolidation/`
3. MEMORY.md 中 10 条替换为 1 条

#### 2d. docs/architecture/README.md — 总纲

一个新实例读完 boot.md 后，如果要理解"这个系统的技术架构长什么样"，去哪里？现在没有答案。

README.md 回答这个问题：

```markdown
# Orchestrator Architecture

## 系统全景
（一段话 + ASCII 架构图：collectors → storage → analysis → governance → channels）

## 模块索引
| Module | Purpose | Key Files | Docs |
|--------|---------|-----------|------|
| core/ | 基础设施 | event_bus, llm_router, config | [→](modules/...) |
| collectors/ | 数据采集 | registry, yaml_runner | [→](modules/...) |
| ... | | | |

## 设计哲学
- ABC 注入制（所有组件可替换）
- 三省六部治理（六部 = 六个 SKILL.md + blueprint.yaml）
- SOUL 传承（compiler → boot.md → 新实例）

## 模式库
→ [PATTERNS.md](PATTERNS.md)（90+ 模式总表）

## 路线图
→ [ROADMAP.md](ROADMAP.md)（下阶段计划）
```

### Layer 3: 路线图 — ROADMAP.md

基于 **战略价值 × 实施难度** 二维排序，分三个 Sprint。

#### Sprint 1: Quick Wins（低难度高回报，1-2 天/个）

| # | Pattern | Source | Value | Effort | Target |
|---|---------|--------|-------|--------|--------|
| 1 | Auto-screenshot after action | bytebot | High | Low | desktop_use/actions.py |
| 2 | type vs paste separation | bytebot | High | Low | desktop_use/actions.py |
| 3 | Text-first layered strategy | Carbonyl | High | Low | desktop_use/perception.py |
| 4 | CDP screencastFrame stream | Carbonyl | High | Low | core/browser_cdp.py |
| 5 | Context Summarization | bytebot | High | Low | desktop_use/trajectory.py |
| 6 | Fact-Expression Split pipeline | 原创 | High | Medium | governance/dispatcher.py |

#### Sprint 2: Design Required（需设计文档，3-5 天/个）

| # | Pattern | Source | Value | Effort | Target |
|---|---------|--------|-------|--------|--------|
| 7 | Runtime Supervisor 8×5 | OpenAkita | Critical | Medium | governance/supervisor.py |
| 8 | Sub-Budget allocation | OpenAkita | High | Medium | core/cost_tracking.py |
| 9 | Taint Tracking 5-tag | OpenFang | High | Medium | governance/safety/taint.py |
| 10 | Transformer Pipeline | Firecrawl | High | Medium | new module |
| 11 | Hallucination action detect | OpenFang | High | Medium | governance/executor_session.py |
| 12 | Tool Policy deny-wins | OpenFang | Medium | Low | governance/policy/ |

#### Sprint 3: Strategic Reserve（长期建设，需独立 spec）

| # | Pattern | Source | Value | Effort |
|---|---------|--------|-------|--------|
| 13 | Three-Tier Memory (Semantic+Episode+Scratchpad) | OpenAkita | High | High |
| 14 | APO Auto Prompt Optimization | Agent Lightning | High | High |
| 15 | LLM Proxy transparent | Agent Lightning | Medium | High |
| 16 | Shared Memory IPC zero-copy | Carbonyl | High | Medium |
| 17 | MCP endpoint for desktop_use | bytebot | Medium | Medium |
| 18 | Unicode block visualization | Carbonyl | Medium | Low |
| 19 | VLM Zone Stage | CV+VLM | Medium | Medium |
| 20 | Grounding DINO fine-tune | CV+VLM | Medium | High |

#### 已设计待实施（有 spec 或 plan 但未动工）

| Pattern | Spec/Plan | Status |
|---------|-----------|--------|
| Runtime Supervisor | plans/2026-03-26-runtime-supervisor.md | Plan written, not started |
| SQLite Resilience | plans/2026-03-26-sqlite-resilience.md | Plan written, not started |
| Wake Session Redesign | specs/2026-03-26-wake-session-redesign.md | Spec + plan written |
| Phase 3 Complex Scene | specs/2026-03-26-phase3-complex-scene.md | Spec written |
| Element Detection v2 | plans/2026-03-26-element-detection-v2.md | Plan written |

#### Fact-Expression Split 待实施项（从 research-sycophancy-split.md）

| # | Item | Target |
|---|------|--------|
| F1 | Governor 调度实装 Fact→Expression pipeline | governance/dispatcher.py |
| F2 | 刑部 SKILL.md 加置信度标注 + UNVERIFIED | departments/quality/SKILL.md |
| F3 | 礼部 SKILL.md 加"只改措辞不改事实" | departments/protocol/SKILL.md |
| F4 | boot.md learnings 追加"举例前先查证" | SOUL/private/ → compiler |

---

## Execution Plan

### Phase 1: 骨架搭建（本次对话）

1. 创建 `docs/architecture/` 目录结构
2. 写 README.md 总纲
3. 写 PATTERNS.md 模式总表（完整的 90+ 模式）
4. 写 ROADMAP.md 路线图
5. desktop_use 架构文档从 CLAUDE.md 抽出 → `docs/architecture/modules/desktop-use.md`
6. CLAUDE.md 瘦身（替换为模块速查表）

### Phase 2: 知识迁移（本次对话）

7. 创建 `orchestrator_steal_consolidated.md`（memory 整合）
8. MEMORY.md 清理（10 条 → 1 条）
9. 原始 steal_sheet_*.md → `.trash/`
10. `tmp/research-2026-03-22/` → `docs/research-archive/`
11. `SOUL/public/research-sycophancy-split.md` → `docs/architecture/fact-expression-split.md`（保留原位置的 symlink 或 redirect 注释）

### Phase 3: 对齐验证

12. 验证 compiler.py 是否已从 management.md 拉取（确认去重方案）
13. 填充 `docs/architecture/modules/` 下其他模块文档（governance, channels, collectors, storage, browser-runtime）
14. 交叉校验 PATTERNS.md 的实施状态 vs 实际代码

---

## 不做的事

- 不改代码——这次纯文档重构
- 不碰 departments/ 结构——已经很好
- 不碰 docs/superpowers/plans/ 和 specs/——已有的设计文档原地不动
- 不碰 SOUL/private/——编译管线由 compiler.py 管
- 不删 docs/superpowers/steal-sheets/——深度分析文档有独立价值

---

## Success Criteria

1. 新实例读 boot.md → CLAUDE.md → `docs/architecture/README.md` 就能理解全系统
2. 任何模式可在 PATTERNS.md 里查到状态、来源、实现位置
3. MEMORY.md 偷师引用从 10 条降到 1 条
4. CLAUDE.md 从 131 行降到 ~60 行
5. 零信息丢失——所有原始文件可在 .trash/ 或 docs/research-archive/ 找到
