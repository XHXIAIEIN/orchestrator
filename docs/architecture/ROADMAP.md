# Implementation Roadmap

> 基于 [PATTERNS.md](PATTERNS.md) 中 🔲 和 📐 模式，按 **战略价值 × 实施难度** 排序。
>
> ✅ = done / 📐 = designed (spec exists) / 🔲 = pending / ⏸️ = shelved

## Sprint 1: Quick Wins（低难度高回报）

| # | Pattern | ID | Source | Value | Effort | Target |
|---|---------|-----|--------|-------|--------|--------|
| 1 | CDP screencastFrame stream | P13 | Carbonyl (R9) | High | Low | `core/browser_cdp.py` |
| 2 | Persistent Failure Counter | R5 | OpenAkita (R4) | High | Low | `governance/stuck_detector.py` |
| 3 | Truncation-safe Rollback | R6 | OpenAkita (R4) | High | Low | `governance/pipeline/phase_rollback.py` |
| 4 | Hallucinated Action Detection | S12 | OpenFang (R6) | High | Low | `governance/executor_session.py` |
| 5 | Smart Model Selection | P10 | Firecrawl (R5) | High | Low | `core/llm_router.py` |
| 6 | Context Summarization (trajectory) | I15 | bytebot (R10) | High | Medium | `desktop_use/trajectory.py` |
| 7 | Fact-Expression Split pipeline | S16 | Original (R-) | High | Medium | `governance/dispatcher.py` |

## Sprint 2: Design Required（需 spec，中高难度）

| # | Pattern | ID | Source | Value | Effort | Target |
|---|---------|-----|--------|-------|--------|--------|
| 8 | Runtime Supervisor (8 detectors × 5-level) | R4 + R2 | OpenAkita (R4) | Critical | Medium | `governance/supervisor.py` |
| 9 | Sub-Budget Proportional Allocation | C2 | OpenAkita (R4) | High | Medium | `core/cost_tracking.py` |
| 10 | Tool Policy (deny-wins + glob + depth) | S11 | OpenFang (R6) | High | Medium | `governance/policy/` |
| 11 | Engine Waterfall (multi-engine race) | P8 | Firecrawl (R5) | High | Medium | `core/llm_router.py` |
| 12 | Feature Flag Engine Selection | P9 | Firecrawl (R5) | High | Medium | `core/llm_router.py` |
| 13 | Transformer Pipeline (pure function chain) | O4 | Firecrawl (R5) | High | Medium | new module |
| 14 | Heartbeat + Lock Renewal | R13 | Firecrawl (R5) | Medium | Medium | `core/system_monitor.py` |
| 15 | Heartbeat Producer-Consumer | R9 | Agent Lightning (R8) | Medium | Low | `core/system_monitor.py` |
| 16 | ExecutionStrategy (debug/production) | O7 | Agent Lightning (R8) | Medium | Medium | `governance/executor.py` |
| 17 | Shared Memory IPC (zero-copy frames) | P12 | Carbonyl (R9) | High | Medium | `desktop_use/screen.py` |

## Sprint 3: Strategic Reserve（长期建设）

| # | Pattern | ID | Source | Value | Effort | Target |
|---|---------|-----|--------|-------|--------|--------|
| 18 | Three-Layer Memory (Semantic+Episode+Scratch) | I11 | OpenAkita (R4) | High | High | new module (SQLite+FTS5) |
| 19 | APO Automatic Prompt Optimization | I6 | Agent Lightning (R8) | High | High | `governance/policy_advisor.py` |
| 20 | LLM Proxy Transparent Layer | O8 | Agent Lightning (R8) | Medium | Medium | new module |
| 21 | VLM Zone Stage (semantic first-cut) | V1 | Gemini+OmniParser (R7) | High | Medium | cvui |
| 22 | CNN ClassifyStage | V2 | UIED (R7) | Medium | Medium | cvui |
| 23 | Image Tiling (large screenshots) | V7 | DarkHelp (R7) | Medium | Medium | cvui |
| 24 | Unicode Pixel Grid Visualization | V15 | Carbonyl (R9) | Low | Medium | `channels/telegram/` |
| 25 | MCP Endpoint Exposure | O17 | bytebot (R10) | Medium | Medium | `desktop_use/` |
| 26 | Store Collections Abstraction | O9 | Agent Lightning (R8) | Medium | Medium | new module |
| 27 | Hook Lifecycle (4 hooks) | R12 | Agent Lightning (R8) | Low | Medium | `governance/executor.py` |
| 28 | Graceful Shutdown | R10 | Agent Lightning (R8) | Medium | Low | entrypoint |
| 29 | Channel 5-Level Routing | O16 | OpenFang (R6) | Medium | Medium | `channels/` |
| 30 | Format Converter (to_coco/yolo) | V4 | labelU (R7) | Low | Low | cvui |
| 31 | LoDPI Adaptive Downscaling | P11 | Carbonyl (R9) | Low | Low | cvui |
| 32 | Sliding Window Auto-Degradation | I12 | OpenAkita (R4) | Medium | Low | `core/llm_router.py` |
| 33 | A/B Testing Framework | I14 | Firecrawl (R5) | Medium | Medium | new module |
| 34 | Text Tool Call Recovery (13+ formats) | D10 | OpenFang (R6) | Medium | Medium | `core/llm_router.py` |
| 35 | Deep Research Multi-Round Loop | D8 | Firecrawl (R5) | Medium | High | new module |

## Already Designed（有 spec/plan 待实施）

📐 状态的模式已有设计稿，以下 plan 文件尚未完整实施：

| Plan | File | Related Pattern |
|------|------|-----------------|
| Runtime Supervisor | `docs/superpowers/plans/2026-03-26-runtime-supervisor.md` | R4 + R2 |
| SQLite Resilience | `docs/superpowers/plans/2026-03-26-sqlite-resilience.md` | — |
| Wake Session Redesign | `docs/superpowers/plans/2026-03-26-wake-session-redesign.md` | — |
| Element Detection v2 | `docs/superpowers/plans/2026-03-26-element-detection-v2.md` | V1, V2 |
| Browser Runtime | `docs/superpowers/plans/2026-03-25-browser-runtime.md` | P13 |
| Browser Tools | `docs/superpowers/plans/2026-03-25-browser-tools.md` | — |
| UI Blueprint | `docs/superpowers/plans/2026-03-25-ui-blueprint.md` | V14 |
| File Split Refactor | `docs/superpowers/plans/2026-03-26-file-split-refactor.md` | — |
| Docs Restructure | `docs/superpowers/plans/2026-03-28-docs-restructure.md` | — |

Designed patterns without dedicated plan files:

| ID | Pattern | Notes |
|----|---------|-------|
| S16 | Fact-Expression Split | spec at `docs/architecture/fact-expression-split.md` |
| O4 | Transformer Pipeline | designed, no plan file yet |
| H3 | Fast Rule Scan (zero-LLM regex) | designed, no plan file yet |
| H4 | Renderer Hijacking | designed, no plan file yet |
| H6 | Input Event Backflow | designed, no plan file yet |
| V8 | DOTS OCR Layout Parsing | designed, no plan file yet |
| V14 | Text-First Layered Strategy | designed, covered by UI Blueprint plan |
| I11 | Three-Layer Memory | designed, no plan file yet |
| D1 | Knowledge Graph + Blast Radius | partial impl in `governance/scrutiny.py` |

## Fact-Expression Split Pending Items

来源：[fact-expression-split.md](fact-expression-split.md) 待实施清单

| # | Item | Target |
|---|------|--------|
| F1 | Governor 调度实装 Fact→Expression pipeline | `governance/dispatcher.py` |
| F2 | 刑部 SKILL.md 加置信度标注 + UNVERIFIED | `departments/quality/SKILL.md` |
| F3 | 礼部 SKILL.md 加"只改措辞不改事实" | `departments/protocol/SKILL.md` |
| F4 | boot.md learnings 追加"举例前先查证" | `SOUL/private/` → compiler |
