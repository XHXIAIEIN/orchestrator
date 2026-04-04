# Implementation Roadmap

> 基于 [PATTERNS.md](PATTERNS.md) 中 🔲 和 📐 模式，按 **战略价值 × 实施难度** 排序。
>
> ✅ = done / 📐 = designed (spec exists) / 🔲 = pending / ⏸️ = shelved
>
> Last updated: 2026-04-01

## Sprint 1: Quick Wins — ✅ ALL COMPLETE

| # | Pattern | ID | Source | Status | Target |
|---|---------|-----|--------|--------|--------|
| 1 | CDP screencastFrame stream | P13 | Carbonyl (R9) | ✅ | `core/browser_cdp.py` |
| 2 | Persistent Failure Counter | R5 | OpenAkita (R4) | ✅ | `governance/stuck_detector.py` |
| 3 | Truncation-safe Rollback | R6 | OpenAkita (R4) | ✅ | `governance/pipeline/phase_rollback.py` |
| 4 | Hallucinated Action Detection | S12 | OpenFang (R6) | ✅ | `governance/executor_session.py` |
| 5 | Smart Model Selection | P10 | Firecrawl (R5) | ✅ | `core/llm_router.py` |
| 6 | Context Summarization (trajectory) | I15 | bytebot (R10) | ✅ | `desktop_use/trajectory.py` |
| 7 | Fact-Expression Split pipeline | S16 | Original (R-) | ✅ | `governance/dispatcher.py` |

## Sprint 2: Design Required — ✅ ALL COMPLETE

| # | Pattern | ID | Source | Status | Target |
|---|---------|-----|--------|--------|--------|
| 8 | Runtime Supervisor (8 detectors × 5-level) | R4 + R2 | OpenAkita (R4) | ✅ | `governance/supervisor.py` |
| 9 | Sub-Budget Proportional Allocation | C2 | OpenAkita (R4) | ✅ | `core/cost_tracking.py` |
| 10 | Tool Policy (deny-wins + glob + depth) | S11 | OpenFang (R6) | ✅ | `governance/policy/tool_policy.py` |
| 11 | Engine Waterfall (multi-engine race) | P8 | Firecrawl (R5) | ✅ | `core/llm_router.py` |
| 12 | Feature Flag Engine Selection | P9 | Firecrawl (R5) | ✅ | `core/llm_router.py` |
| 13 | Transformer Pipeline (pure function chain) | O4 | Firecrawl (R5) | ✅ | `core/transformer_pipeline.py` |
| 14 | Heartbeat + Lock Renewal | R13 | Firecrawl (R5) | ✅ | `core/system_monitor.py` |
| 15 | Heartbeat Producer-Consumer | R9 | Agent Lightning (R8) | ✅ | `core/system_monitor.py` |
| 16 | ExecutionStrategy (debug/production) | O7 | Agent Lightning (R8) | ✅ | `governance/executor.py` |
| 17 | Shared Memory IPC (zero-copy frames) | P12 | Carbonyl (R9) | ✅ | `desktop_use/screen.py` |

## Sprint 3: Strategic Reserve — ✅ ALL COMPLETE (orchestrator items; cvui items remain)

| # | Pattern | ID | Source | Status | Target |
|---|---------|-----|--------|--------|--------|
| 18 | Three-Layer Memory (Semantic+Episode+Scratch) | I11 | OpenAkita (R4) | ✅ | `governance/context/memory_tier.py` |
| 19 | APO Automatic Prompt Optimization | I6 | Agent Lightning (R8) | ✅ | `governance/apo.py` |
| 20 | LLM Proxy Transparent Layer | O8 | Agent Lightning (R8) | ✅ | `core/llm_proxy.py` |
| 21 | VLM Zone Stage (semantic first-cut) | V1 | Gemini+OmniParser (R7) | 🔲 | cvui |
| 22 | CNN ClassifyStage | V2 | UIED (R7) | 🔲 | cvui |
| 23 | Image Tiling (large screenshots) | V7 | DarkHelp (R7) | 🔲 | cvui |
| 24 | Unicode Pixel Grid Visualization | V15 | Carbonyl (R9) | ✅ | `src/tui/` |
| 25 | MCP Endpoint Exposure | O17 | bytebot (R10) | ✅ | `desktop_use/mcp_server.py` |
| 26 | Store Collections Abstraction | O9 | Agent Lightning (R8) | ✅ | `core/registry.py` |
| 27 | Hook Lifecycle (16 events) | R12 | Agent Lightning (R8) + Inspect AI (R38) | ✅ | `core/lifecycle_hooks.py` |
| 28 | Graceful Shutdown | R10 | Agent Lightning (R8) | ✅ | entrypoint |
| 29 | Channel 5-Level Routing | O16 | OpenFang (R6) | ✅ | `channels/` |
| 30 | Format Converter (to_coco/yolo) | V4 | labelU (R7) | 🔲 | cvui |
| 31 | LoDPI Adaptive Downscaling | P11 | Carbonyl (R9) | 🔲 | cvui |
| 32 | Sliding Window Auto-Degradation | I12 | OpenAkita (R4) | ✅ | `core/llm_router.py` |
| 33 | A/B Testing Framework | I14 | Firecrawl (R5) | ✅ | `core/ab_testing.py` |
| 34 | Text Tool Call Recovery (6 formats) | D10 | OpenFang (R6) | ✅ | `core/tool_call_recovery.py` |
| 35 | Deep Research Multi-Round Loop | D8 | Firecrawl (R5) | ✅ | `core/deep_research.py` |

## Sprint 4: Orphan Integration — ✅ ALL COMPLETE (2026-03-31)

55 orphan modules from Rounds 3-16 integrated in 18 commits. 3 archived to `.trash/` after comparison. 321 new integration tests. See [forensics report](../2026-03-31-steal-forensics-report.md) for details.

| # | Area | Modules | Status |
|---|------|---------|--------|
| 36 | Safety pipeline (5 modules) | injection_test, dual_verify, prompt_lint, drift_detector, convergence → scrutiny/supervisor | ✅ |
| 37 | Storage (2 modules) | dedup, hotness → learnings + memory | ✅ |
| 38 | Audit chain (6 modules) | skill_vetter, change_aware, file_ratchet, WAL, evolution_chain, execution_snapshot | ✅ |
| 39 | Learning pipeline (3 modules) | fact_extractor, experience_cull, fix_first | ✅ |
| 40 | Condenser strategies (3 modules) | llm_summarizing, water_level, amortized_forgetting → context assembly | ✅ |
| 41 | ChatDev 2.0 core (4 modules) | resilient_retry, event_stream, future_gate, function_catalog | ✅ |
| 42 | R3-7 orphans (6 modules) | manifest_inherit, cross_review, lifecycle_hooks, webhook, rule_deps, deferred_retrieval | ✅ |
| 43 | Remaining 14 orphans | structured_memory, group_orchestration, cross_dept, session_repair, permissions, etc. | ✅ |
| 44 | output_compress wiring | Replace hardcoded `[:2000]` truncation | ✅ |
| 45 | Memory consolidation | experiences + design_memory → structured_memory DB | ✅ |

## Sprint 5: Round 28-34 Steal Digest — ✅ COMPLETE (2026-04-01)

21 patterns from 6 sub-rounds (R28a-f) + digest session. 11 P0 from main batch + 10 from digest.

| # | Pattern | ID | Source | Status | Target |
|---|---------|-----|--------|--------|--------|
| 46 | Governor Synthesis Discipline | H10 | CC Prompts (R28b) | ✅ | `SOUL/public/prompts/synthesis_discipline.md` |
| 47 | Verification Gate Adversarial | S22 | CC Verification (R28b) | ✅ | `SOUL/public/prompts/guardian_assessment.md` |
| 48 | PreCompact 9-Section Structure | H12 | CC Compact (R28b) | ✅ | `SOUL/public/prompts/compact_template.md` |
| 49 | Collaboration Mode Switching | H11 | Codex CLI (R28c) | ✅ | `SOUL/public/prompts/collaboration_modes.md` |
| 50 | Cheapest-First Gate Chain | O19 | CC AutoDream (R28a) | ✅ | `src/core/gate_chain.py` |
| 51 | Address Scheme Registry | O20 | CC peerAddress (R28a) | ✅ | `src/core/address_registry.py` |
| 52 | Unified Executor Interface | O21 | CC backends (R28a) | ✅ | `src/governance/agent_executor_interface.py` |
| 53 | Protocol Messages | O22 | CC teammateMailbox (R28a) | ✅ | `src/core/protocol_messages.py` |
| 54 | Guard Banned Prefixes + Exec Policy | S21 | Codex ExecPolicy (R28c) | ✅ | `config/exec-policy.yaml` + `.claude/hooks/guard-redflags.sh` |
| 55 | Guardian Risk Assessment | S22 | Codex policy (R28c) | ✅ | `SOUL/public/prompts/guardian_assessment.md` |
| 56 | Loop Detection Hook | R15 | DeerFlow 2.0 | ✅ | `.claude/hooks/loop-detector.sh` |
| 57 | Config Protection Hook | S20 | CC+Codex | ✅ | `.claude/hooks/config-protect.sh` |
| 58 | Boundary Nonce | S19 | yoyo-evolve (R30) | ✅ | `src/channels/boundary_nonce.py` |
| 59 | Strategic Compact Decision Table | H12 | CC+Headroom | ✅ | `SOUL/public/prompts/compact_template.md` |
| 60 | Session Handoff Protocol | H13 | CC (R28) | ✅ | `SOUL/public/prompts/session_handoff.md` |
| 61 | Evaluator-Fix Loop | O24 | yoyo-evolve (R30) | ✅ | `SOUL/public/prompts/evaluator_fix_loop.md` |
| 62 | Middleware Pipeline | O23 | DeerFlow 2.0 | ✅ | `src/governance/pipeline/middleware.py` |
| 63 | Memory Staleness Annotator | I19 | CC (R29) | ✅ | `SOUL/tools/memory_staleness.py` |
| 64 | Instinct Learning Pipeline | I16 | CC (R29) | ✅ | `src/governance/learning/instinct_pipeline.py` |
| 65 | SSE Progress Streaming | O25 | CC (R28a) | ✅ | `dashboard/server.js` |
| 66 | Subagent Limit Middleware | O26 | CC (R28a) | ✅ | `src/governance/dispatcher.py` |

## Sprint 5b: Additional Features (2026-04-01)

| # | Feature | Status | Target |
|---|---------|--------|--------|
| 67 | Multi-Pass Model Normalization (P14) | ✅ | `src/core/model_normalize.py` |
| 68 | Checkpoint-Restart Recovery (R16) | ✅ | `src/governance/checkpoint_recovery.py` |
| 69 | Transcript Filter (S18) | ✅ | `src/governance/safety/transcript_filter.py` |
| 70 | Memory 2-Phase Pipeline (I17) | ✅ | `SOUL/tools/memory_synthesizer.py` |
| 71 | Memory No-Op Gate (I18) | ✅ | `SOUL/tools/memory_noop_gate.py` |
| 72 | Disposition Parameters (I20) | ✅ | `config/disposition.yaml` |
| 73 | babysit-pr Skill | ✅ | `.claude/skills/babysit-pr/SKILL.md` |
| 74 | Forced Output Gate (scrutiny upgrade) | ✅ | `SOUL/public/prompts/scrutiny.md` |
| 75 | Rationalization Immunity | ✅ | `SOUL/public/prompts/rationalization-immunity.md` |

## Plan Files — ALL IMPLEMENTED

All 12 plan files under `docs/superpowers/plans/` have been fully implemented:

| Plan | Status |
|------|--------|
| Browser Runtime (2026-03-25) | ✅ |
| Browser Tools (2026-03-25) | ✅ |
| UI Blueprint (2026-03-25) | ✅ |
| Element Detection v2 (2026-03-26) | ✅ |
| File Split Refactor (2026-03-26) | ✅ |
| Wake Session Redesign (2026-03-26) | ✅ |
| Runtime Supervisor (2026-03-26) | ✅ |
| SQLite Resilience (2026-03-26) | ✅ |
| Docs Restructure (2026-03-28) | ✅ |
| Intent Rule Engine (2026-03-29) | ✅ |
| Round 12 Steal P0 (2026-03-29) | ✅ |
| ChatDev Steal P0 (2026-03-30) | ✅ |

## Designed Patterns — Status

| ID | Pattern | Status | Notes |
|----|---------|--------|-------|
| S16 | Fact-Expression Split | ✅ | `governance/dispatcher.py` |
| O4 | Transformer Pipeline | ✅ | `core/transformer_pipeline.py` |
| H3 | Fast Rule Scan (zero-LLM regex) | ✅ | `governance/safety/fast_rule_scan.py` |
| H4 | Renderer Hijacking | ✅ | `desktop_use/output_interceptor.py` |
| H6 | Input Event Backflow | ✅ | `channels/event_backflow.py` |
| V8 | DOTS OCR Layout Parsing | 📐 | VLM layout-only prompt, no implementation |
| V14 | Text-First Layered Strategy | 📐 | DOM/Win32 text → OCR fallback, no implementation |
| I11 | Three-Layer Memory | ✅ | `governance/context/memory_tier.py` |
| D1 | Knowledge Graph + Blast Radius | ✅ | `governance/knowledge_graph.py` |

## Fact-Expression Split — ✅ COMPLETE

| # | Item | Target | Status |
|---|------|--------|--------|
| F1 | Governor dispatch pipeline | `governance/dispatcher.py` | ✅ |
| F2 | Quality SKILL.md + confidence tags | `departments/quality/SKILL.md` | ✅ |
| F3 | Protocol SKILL.md + rephrase rule | `departments/protocol/SKILL.md` | ✅ |
| F4 | boot.md learnings "举例前先查证" | `SOUL/private/` → compiler | ✅ |

## Sprint 6: PUA Behavioral Engineering (R35) — ✅ COMPLETE (2026-04-01)

6 patterns from tanweai/pua (14K+ stars). Core insight: externalize behavior correction to deterministic logic.

| # | Pattern | ID | Source | Status | Target |
|---|---------|-----|--------|--------|--------|
| 76 | Deterministic Pressure Escalation | R17 | PUA (R35) | ✅ | `.claude/hooks/error-detector.sh` |
| 77 | PreCompact Behavioral Checkpoint | R18 | PUA (R35) | ✅ | `.claude/hooks/pre-compact.sh` |
| 78 | Methodology Router | O27 | PUA (R35) | ✅ | `src/governance/executor_prompt.py` |
| 79 | Sub-Agent Behavioral Norms | S23 | PUA (R35) | ✅ | `.claude/hooks/dispatch-gate.sh` |
| 80 | Anti-Rationalization Hook (dynamic) | H14 | PUA (R35) | ✅ | `.claude/hooks/error-detector.sh` (L2-L4) |
| 81 | Failure-Mode → Methodology Switch | H15 | PUA (R35) | ✅ | `SOUL/public/prompts/methodology_router.md` |

## Remaining Work

**Orchestrator 本体：** Sprint 1-6 全部 81 项已完成 ✅

**cvui 包（独立仓库 `D:\Users\Administrator\Documents\GitHub\cvui`）：**
- 🔲 V1: VLM Zone Stage
- 🔲 V2: CNN ClassifyStage
- 🔲 V4: Format Converter (COCO/YOLO)
- 🔲 V5: Pre-Annotation + Human Correction
- 🔲 V7: Image Tiling
- 🔲 P11: LoDPI Adaptive Downscaling
- 📐 V8: DOTS OCR Layout Parsing
- 📐 V14: Text-First Layered Strategy
