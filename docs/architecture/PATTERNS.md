# Pattern Library

> 38 轮偷师，100+ 项目，179 模式。按主题域组织，不按来源。
>
> 每个模式只出现一次。跨轮重复的模式合并为单条，在 Notes 中标注演进。

## Overview

| Metric | Count |
|--------|-------|
| Total patterns | 179 |
| ✅ Implemented | 154 |
| 📐 Designed (spec exists) | 2 |
| 🔲 Pending (cvui only) | 6 |
| ⏸️ Shelved | 17 |

---

## 1. Safety & Control

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| S1 | Authority Ceiling (READ→APPROVE 4-tier) | Round 1 | ✅ | `governance/policy/` | 4-tier permission model + CEILING_TOOL_CAPS |
| S2 | Taint Tracking (5-label lattice) | OpenFang (R6) | ✅ | `governance/safety/taint.py` | 5 labels (External/UserInput/PII/Secret/Untrusted) + 3 sink rules + declassify |
| S3 | Immutable Constraints | Round 1 | ✅ | `governance/safety/immutable_constraints.py` | FORBIDDEN_TOOLS + FORBIDDEN_PATHS glob |
| S4 | Prompt Injection Defense | Round 2 + Firecrawl (R5) + OpenFang (R6) | ✅ | `governance/safety/injection_test.py` | R2: 14 test cases / 6 categories; R5: LLM prompt hardening; R6: 3-level scanner (critical/warning/info) |
| S5 | Prompt Canary (injection tripwire) | Round 1 | ✅ | `governance/policy/prompt_canary.py` | Canary token deployment |
| S6 | Prompt Lint (anti-pattern detection) | Round 2 | ✅ | `governance/safety/prompt_lint.py` | Rule-based lint for prompt anti-patterns |
| S7 | Dual-AI Cross Verification | Round 2 | ✅ | `governance/safety/dual_verify.py` | Independent dual-model + agreement analysis |
| S8 | Drift Detection | Round 2 | ✅ | `governance/safety/drift_detector.py` | Behavioral drift from baseline |
| S9 | Ralph Loop Convergence Detection | Round 2 | ✅ | `governance/safety/convergence.py` | Detect non-converging iterative loops |
| S10 | 4-Gate Verification Framework | Round 2 | ✅ | `governance/safety/verify_gate.py` | 4 verification gates before action |
| S11 | Tool Policy (deny-wins + glob + depth limit) | OpenFang (R6) | ✅ | `governance/policy/tool_policy.py` | ToolPolicy class with deny-wins, glob matching, depth limits |
| S12 | Hallucinated Action Detection | OpenFang (R6) | ✅ | `governance/executor_session.py` | Regex scan for action claims without tool calls; log-only, no blocking |
| S13 | SSRF Protection | Firecrawl (R5) | ⏸️ | — | `assertSafeTargetUrl()` — not needed until we do external fetches |
| S14 | Secret Zeroization | OpenFang (R6) | ⏸️ | — | Rust `Zeroizing<String>` has no reliable Python equivalent; use `SecretStr` + env cleanup |
| S15 | Zero Data Retention (ZDR) | Firecrawl (R5) | ⏸️ | — | Full-chain data scrubbing flag. Needed for multi-tenant, not now |
| S16 | Fact-Expression Split (anti-sycophancy) | Research (R-) | ✅ | `governance/dispatcher.py` + `departments/quality/SKILL.md` + `departments/protocol/SKILL.md` | 2-step pipeline: Fact Layer (刑部) → Expression Layer (礼部). Auto-detect via intent |
| S17 | Persona Anchor Hook (attention decay fix) | Research (R-) | ✅ | `.claude/hooks/persona-anchor.sh` | PostToolUse counter every 10 calls + PreCompact anchor injection |
| S18 | Transcript Filter (strip assistant text) | CC System Prompts (R28b) | ✅ | `governance/safety/transcript_filter.py` | Strip assistant text before safety classifier input |
| S19 | Boundary Nonce (injection defense) | yoyo-evolve (R30) | ✅ | `channels/boundary_nonce.py` | Random nonce at message boundary, detect cross-boundary injection |
| S20 | Config Protection Hook | CC+Codex (R28) | ✅ | `.claude/hooks/config-protect.sh` | Block writes to .env, CLAUDE.md, settings.json without approval |
| S21 | Exec Policy Rule Engine | Codex CLI (R28c) | ✅ | `config/exec-policy.yaml` + `scripts/exec_policy_loader.py` | YAML-configurable guard rules with bash fallback |
| S22 | Guardian Risk Assessment | Codex (R28c) | ✅ | `SOUL/public/prompts/guardian_assessment.md` | Semantic risk eval prompt for sub-agent modifications |
| S23 | Sub-Agent Behavioral Norms Injection | PUA (R35) | ✅ | `.claude/hooks/dispatch-gate.sh` | Auto-inject verification discipline + diagnostic norms into sub-agent context |
| S24 | VBR Gate (Verify Before Reporting) | proactive-agent (R23) | ✅ | `.claude/hooks/vbr-gate.sh` | Stop hook: detect completion claims without verification evidence |
| S25 | Self-Modification Gate (Editable/Fixed) | AutoAgent (R38b) | ✅ | `CLAUDE.md` Gate Functions | Eval baseline required before config change; editable/fixed boundary enforced |
| S26 | Anti-Degradation Protocol | ClawHub (R14) | ✅ | `governance/safety/anti_degradation.py` | Pre-modification scoring gate: 4-dim weighted (freq×3/fail×3/burden×2/token×2), gate<50=reject, forbidden justifications |

---

## 2. Reliability & Monitoring

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| R1 | Loop/Stuck Detection (unified) | Round 1 + R2 + OpenAkita (R4) + OpenFang (R6) + Agent Lightning (R8) | ✅ | `governance/stuck_detector.py` + `governance/safety/doom_loop.py` | R1: Doom Loop Detection; R2: StuckDetector 6 patterns (REPEATED_ACTION, MONOLOGUE, CONTEXT_WINDOW_LOOP, SIGNATURE_REPEAT); R4: Signature Repeat `tool(md5[:8])` + Progress-Aware Timeout; R6: result-aware + ping-pong A-B-A-B. **Gap**: ping-pong and result-hash not yet merged into stuck_detector |
| R2 | 5-Level Graduated Intervention | OpenAkita (R4) | ✅ | `governance/supervisor.py` | InterventionLevel enum: NUDGE→STRATEGY_SWITCH→MODEL_SWITCH→ESCALATE→TERMINATE |
| R3 | Watchdog Embedded Health Check | Agent Lightning (R8) | ✅ | `governance/_tasks_mixin.py` | Piggyback on `update_task()` to scan timeout/heartless tasks, 30s debounce |
| R4 | Runtime Supervisor (9 detectors) | OpenAkita (R4) | ✅ | `governance/supervisor.py` | 9 detectors (signature_repeat, edit_jitter, reasoning_loop, token_anomaly, idle_spin, error_cascade, output_regression, scope_creep, context_exhaustion) + 29 tests |
| R5 | Persistent Failure Counter | OpenAkita (R4) | ✅ | `governance/stuck_detector.py` | `_persistent_failures` + `_persistent_signatures` survive reset(); `should_escalate()` at 3×/5× |
| R6 | Truncation-safe Rollback | OpenAkita (R4) | ✅ | `governance/executor_session.py` + `governance/pipeline/phase_rollback.py` | PipelineCheckpointer wired into run loop; rollback attempted before abort |
| R7 | Phase Rollback + Checkpoint | Round 2 | ✅ | `governance/pipeline/phase_rollback.py` | PipelineCheckpointer + rollback; also covers R2 "breakpoint resume" |
| R8 | System Monitor Backpressure | Firecrawl (R5) | ✅ | `core/system_monitor.py` | CPU/RAM check; `acceptConnection()` pattern; 25-reject stall alarm |
| R9 | Heartbeat Producer-Consumer | Agent Lightning (R8) | ✅ | `core/system_monitor.py` | HeartbeatMonitor: background collector thread + cached reads, zero blocking |
| R10 | Graceful Shutdown | Agent Lightning (R8) | ✅ | `core/graceful_shutdown.py` | SIGINT/SIGTERM handler, cleanup stack, zombie thread detection |
| R11 | Rollout-Attempt Retry Model | Agent Lightning (R8) | ✅ | `governance/executor.py` | Rollout wraps Attempt loop; `RolloutConfig(max_attempts, retry_conditions, backoff_seconds)`; sub_runs table |
| R12 | Hook Lifecycle (16 events) | Agent Lightning (R8) + Inspect AI (R38) | ✅ | `core/lifecycle_hooks.py` | Unified 16-event registry: batch/task/rollout/attempt/context/llm/review/error layers. LimitExceededError pierces isolation. HookEntry: enabled()+priority. Aliases for backwards compat |
| R13 | Heartbeat + Lock Renewal | Firecrawl (R5) | ✅ | `core/system_monitor.py` | TTL-based heartbeat with death callback + lock renewal |
| R14 | Audit Hash Chain (Merkle) | Round 1 + OpenFang (R6) | ✅ | `governance/audit/run_logger.py` | SHA-256 hash chain JSONL. Confirmed equivalent to OpenFang's Merkle chain |
| R15 | Loop Detection Hook | DeerFlow 2.0 (R28) | ✅ | `.claude/hooks/loop-detector.sh` | Detect repeated tool calls, inject break prompt |
| R16 | Checkpoint-Restart Recovery | Codex CLI (R28c) | ✅ | `src/governance/checkpoint_recovery.py` | Resume interrupted sub-agents from checkpoint |
| R17 | Deterministic Pressure Escalation | PUA (R35) | ✅ | `.claude/hooks/error-detector.sh` | Shell counter drives L1-L4 escalation on consecutive Bash failures; success resets to 0. LLM cannot opt out |
| R18 | PreCompact Behavioral Checkpoint | PUA (R35) | ✅ | `.claude/hooks/pre-compact.sh` | Before compaction: dump tried approaches, eliminated hypotheses, failure count to disk. Bridges memory gap |
| R19 | Hook Self-Check Bypass Prevention | Claudeception (R36c) | ✅ | `.claude/hooks/dispatch-gate.sh` | Force self-check hooks cannot be bypassed by passive matching |
| R20 | MCP Server Health Check | entrix (R15) | ✅ | `src/core/mcp_health.py` | 3-state (healthy/degraded/unhealthy) + exponential backoff + auto-recovery |

---

## 3. Performance & Efficiency

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| P1 | Token Budget Degradation | Round 1 | ✅ | `governance/budget/token_budget.py` | Model degradation chain when budget runs low |
| P2 | Context Budget (dual-layer truncation) | OpenFang (R6) | ✅ | `core/context_budget.py` | Layer 1: single result 30% cap; Layer 2: global 75% guard; UTF-8 safe truncation |
| P3 | Context Compression (4 strategies) | Round 2 + R3 + Firecrawl (R5) | ✅ | `governance/condenser/` | Recent, Amortized, LLMSummarizing, WaterLevel. R3 water-level 85% stop hook. R5: Firecrawl transformer pipeline inspired per-step timing |
| P4 | Attention Decay HOT/WARM/COLD | Round 2 | ✅ | `governance/context/context_assembler.py` | 3-tier context assembly with decay weighting |
| P5 | RTK Output Compression | Round 2 | ✅ | `governance/pipeline/output_compress.py` | Compress verbose tool outputs |
| P6 | Depth Tiers (4 levels) | Tavily (R3) | ✅ | `core/llm_router.py` | 4 depth tiers orthogonal to task_type; `generate(depth=...)` |
| P7 | Context Threshold Semantic Modes | Brave (R3) | ✅ | `core/llm_router.py` | THRESHOLD_MODES: strict(50) / balanced(10) / lenient(3) / disabled(0) |
| P8 | Engine Waterfall (multi-engine race) | Firecrawl (R5) | ✅ | `core/llm_router.py` | async _waterfall_generate() with staggered starts + first-wins cancellation |
| P9 | Feature Flag Engine Selection | Firecrawl (R5) | ✅ | `core/llm_models.py` | Feature matrix per engine + select_engine_by_features() |
| P10 | Smart Model Selection (complexity-based) | Firecrawl (R5) | ✅ | `core/llm_router.py` | `_score_schema_complexity()` + `select_model_for_schema()` → fast/balanced/strong tier |
| P11 | LoDPI Adaptive Downscaling | Carbonyl (R9) | 🔲 | — | P1. Resolution-target-driven scale factor instead of fixed ratio. Apply to cvui DownscaleStage |
| P12 | Shared Memory IPC (zero-copy frames) | Carbonyl (R9) | ✅ | `desktop_use/screen.py` | SharedFrameBuffer: zero-copy frame buffer via shared_memory |
| P13 | CDP Screencast Frame Stream | Carbonyl (R9) | ✅ | `core/browser_cdp.py` | `take_screenshot()` + `enable/disable_screencast()` + `recv_screencast_frame()` with ack |
| P14 | Multi-Pass Model Normalization | CC (R28a) | ✅ | `src/core/model_normalize.py` | 4-pass: exact/prefix/date/fuzzy model name resolution |
| P15 | Configurable Summarization Triggers | DeerFlow (R29) | ✅ | `governance/condenser/configurable.py` | OR-logic triggers (token/message/fraction) + configurable retention policies |
| P16 | Upload Mention Stripping | DeerFlow (R29) | ✅ | `governance/condenser/upload_stripper.py` | Strip ephemeral file paths (/tmp, uploads, AppData) from memory |
| P17 | WAL Buffer (Context Danger Zone) | ClawHub (R14) | ✅ | `governance/context/wal_buffer.py` | At 60% context, log human+agent summaries; recover after compaction |

---

## 4. Intelligence & Learning

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| I1 | Learn-from-Edit | Round 1 | ✅ | `governance/learning/learn_from_edit.py` | Extract patterns from user corrections |
| I2 | Scout-Synthesize Pattern | Round 1 | ✅ | `governance/pipeline/scout.py` | Reconnaissance → synthesis pipeline |
| I3 | Usage-based Experience Culling | Round 2 | ✅ | `governance/learning/experience_cull.py` | DB migration + usage-based pruning |
| I4 | 5-Dimension Confidence Scoring | Round 2 | ✅ | `governance/preflight/confidence.py` | 5 axes of confidence evaluation |
| I5 | Critic Auto-Scoring | Round 2 | ✅ | `governance/quality/critic.py` | Automated quality scoring interface |
| I6 | APO (Automatic Prompt Optimization) | Agent Lightning (R8) | ✅ | `governance/apo.py` | APOOptimizer: beam search + textual gradient + rule mutations + early stopping |
| I7 | Self-Evolution (3-phase) | OpenAkita (R4) | ⏸️ | — | Log+review+history → LLM analysis → graded self-repair (tools only, not core). Too ambitious for now |
| I8 | Citation Scoring (memory retrieval) | OpenAkita (R4) | ⏸️ | — | Write-back effectiveness score on memory retrieval. Needs usage data first |
| I9 | Personality Preference Auto-Promotion | OpenAkita (R4) | ⏸️ | — | High-confidence memory → identity file → prompt recompile. SOUL already handles manually |
| I10 | Memory Supersede Chain | OpenAkita (R4) + context | ✅ | `governance/context/memory_supersede.py` | `superseded_by` links; new memory links old, preserving audit trail |
| I11 | Three-Layer Memory (Semantic+Episode+Scratch) | OpenAkita (R4) + ClawHub (R14) | ✅ | `governance/context/memory_tier.py` | 3-tier loading (L0/L1/L2). Upgraded to HOT/WARM/COLD with auto-promotion/demotion (R14 steal) |
| I12 | Sliding Window Auto-Degradation | OpenAkita (R4) | ✅ | `core/llm_router.py` | ModelDegrader: 3 failures→downgrade, 1 success→restore |
| I13 | Dual-Track Extraction (profile vs task) | OpenAkita (R4) | ⏸️ | — | Separate user profile extraction from task experience extraction. Low priority |
| I14 | A/B Testing Framework (model/engine) | Firecrawl (R5) | ✅ | `core/ab_testing.py` | Experiment/ABTestManager: split assignment, result tracking, winner detection |
| I15 | Context Summarization (trajectory) | bytebot (R10) | ✅ | `desktop_use/trajectory.py` | Auto-summarize on window overflow; `_summary` prepended to prompt context |
| I16 | Instinct Learning Pipeline | CC (R29) | ✅ | `src/governance/learning/instinct_pipeline.py` | Auto-extract instincts from successful patterns |
| I17 | Memory 2-Phase Pipeline | Codex CLI (R28c) | ✅ | `SOUL/tools/memory_synthesizer.py` | Observation archive → synthesized context |
| I18 | Memory No-Op Gate | Codex CLI (R28c) | ✅ | `SOUL/tools/memory_noop_gate.py` | Reject low-value memories before storage |
| I19 | Memory Staleness Annotator | CC (R29) | ✅ | `SOUL/tools/memory_staleness.py` | Tag stale memories for refresh or removal |
| I20 | Disposition Parameterization | hindsight (R28e) | ✅ | `config/disposition.yaml` | Configurable personality tuning parameters |
| I21 | Skill Extraction Pipeline | self-improving-agent (R23) | ✅ | `governance/learning/skill_extractor.py` | Auto-extract skills from clustered learnings (≥5 entries + recurrence ≥2) |
| I22 | Fact Confidence Ranking | DeerFlow (R29) | ✅ | `governance/context/confidence_ranker.py` | Token-budgeted injection sorted by confidence (apply_count × recurrence × recency) |
| I23 | Per-Agent Memory Isolation | DeerFlow (R29) | ✅ | `governance/context/memory_tier.py` | Department-scoped memory namespaces with partition_by_agent |
| I24 | Feature Request Auto-Capture | self-improving-agent (R23) | ✅ | `.claude/hooks/correction-detector.sh` | Detect "I wish"/"能不能" patterns, log as feature_request area |
| I25 | Periodic Review Trigger | self-improving-agent (R23) | ✅ | `.claude/hooks/session-stop.sh` | Check pending learnings count at session end, remind if >10 |
| I26 | Negative Feedback Tracker | ClawHub (R14) | ✅ | `governance/stuck_detector.py` | Track failed approaches, force strategy switch after 3 repeated failures |
| I27 | ExperimentLedger (Keep/Discard) | AutoAgent (R38b) | ✅ | `governance/eval/experiment.py` | Score-driven config experiments with simplicity tiebreaker |

---

## 5. Cost & Resource Management

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| C1 | Cost Tracking (per-request + full chain) | Exa/Parallel (R3) + Firecrawl (R5) + OpenFang (R6) | ✅ | `core/cost_tracking.py` + `core/llm_router.py` | R3: `GenerateResult.cost_dollars` + `_estimate_cost()`. R5: full-chain CostTracking with stack trace + `CostLimitExceededError`. R6: per-agent token/hour. **Gap**: stack trace + hard cutoff not yet in our impl |
| C2 | Sub-budget Proportional Allocation | OpenAkita (R4) | ✅ | `core/cost_tracking.py` | create_child_budget(fraction) + report_to_parent() tree structure |
| C3 | Parameter Locking | Tavily (R3) | ✅ | `channels/config.py` | LOCKED_PARAMS + runtime_override/get/reset |
| C4 | Parameter Sanitization | R3 | ✅ | `core/params.py` | `sanitize_params()` + `merge_defaults()` |
| C5 | Warnings (non-silent failure) | Parallel (R3) | ✅ | `core/warnings.py` | Thread-safe WarningCollector; severity levels; `warning_context()` manager |
| C6 | Dual-Layer Concurrency Control | Firecrawl (R5) | ⏸️ | — | Team + Crawl level via Redis Sorted Set. SQLite sufficient for single-machine |
| C7 | Concurrency Queue Promotion | Firecrawl (R5) | ⏸️ | — | `concurrentJobDone()` auto-promotes next waiting task. Scale concern |
| C8 | Agent Semaphore (tiered concurrency) | Round 1 + OpenFang (R6) | ✅ | `governance/safety/agent_semaphore.py` | Tiered concurrency limits. OpenFang has 32-dispatch but we're more granular |

---

## 6. Perception & Vision (desktop_use + cvui)

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| V1 | VLM Zone Stage (semantic first-cut) | Gemini + OmniParser (R7) | 🔲 | — | P0 for cvui. Screenshot → VLM("which regions are UI?") → zones → CV pipeline runs inside zones only |
| V2 | CNN ClassifyStage (replace heuristic) | UIED (R7) | 🔲 | — | P1 for cvui. MobileNetV3-Small (~2M params, <5ms) classify: button/text/slider/icon/checkbox/dropdown |
| V3 | Detection→Feature→Retrieval Pipeline | PaddleX PP-ShiTuV2 (R7) | ⏸️ | — | FAISS vector cache for similar windows. Current exact cache sufficient |
| V4 | Format Converter Plugin (to_coco/yolo) | labelU (R7) | 🔲 | — | P1 for cvui. `DetectionContext.to_coco()`, `to_yolo()`, `to_labelme()` — detection as annotation data generator |
| V5 | Pre-Annotation + Human Correction | labelU (R7) | 🔲 | — | P2 for cvui. AI annotate → human correct on dashboard → retrain. Detection→Correction→Training flywheel |
| V6 | pix2emb Paradigm (embedding decode) | NExT-Chat (R7) | ⏸️ | — | Long-term. Position embedding → decoder → bbox/mask. Better than pix2seq for spatial precision |
| V7 | Image Tiling (large image detection) | DarkHelp (R7) | 🔲 | — | P1 for cvui. `TilingStage`: split large screenshot into NxN tiles → per-tile pipeline → merge dedupe |
| V8 | DOTS OCR Layout Parsing | R7 supplement | 📐 | — | 1.7B VLM, prompt_layout_only outputs bbox + category. Alternative VLMZoneStage backend |
| V9 | Synthetic Data Training | DocLayout-YOLO (R7) | ⏸️ | — | Bin-packing synthetic UI pages for YOLO training. Long-term |
| V10 | Structural CV Filtering (DBSCAN + multi-dim) | R7 supplement | ✅ | cvui `structural_v4` | DBSCAN density + saturation/variance/edge/neighbor anomaly. 56→41 rects, 60ms, 0 models |
| V11 | Takeover + InputCapture (human handoff) | bytebot (R10) | ✅ | `desktop_use/` | pynput monitor + debounce aggregation (click 250ms, typing 500ms, scroll 4x) → inject trajectory |
| V12 | Post-Action Auto Screenshot | bytebot (R10) | ✅ | `desktop_use/actions.py` | Every non-screenshot action → wait 750ms → auto screenshot as tool_result |
| V13 | type vs paste Separation | bytebot (R10) | ✅ | `desktop_use/actions.py` | `type_text` (≤25 char) vs `paste_text` (clipboard+Ctrl+V); `sensitive` flag blocks echo |
| V14 | Text-First Layered Strategy | Carbonyl (R9) | 📐 | — | DOM text / Win32 control text → trust first; OCR only as fallback. Matches Carbonyl TextCaptureDevice |
| V15 | Unicode Pixel Grid Visualization | Carbonyl (R9) | ✅ | `channels/pixel_grid.py` | PixelGrid: ANSI 24-bit color + block chars + heatmap gradient |

---

## 7. Orchestration & Routing

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| O1 | Gateway Intent Routing (3-way) | Round 1 | ✅ | `gateway/` | classifier + complexity + dispatcher + intent + routing |
| O2 | PLAN→ACT→EVAL Loop | Round 1 | ✅ | `governance/pipeline/eval_loop.py` | Closed-loop execution |
| O3 | Stage Pipeline + File IPC | Round 1 + Understand-Anything (R2) | ✅ | `governance/pipeline/stage_pipeline.py` + `scratchpad.py` | Stage gates + scratchpad passing |
| O4 | Transformer Pipeline (pure function chain) | Firecrawl (R5) | ✅ | `core/transformer_pipeline.py` | TransformerPipeline: composable steps with auto-timing + PipelineResult |
| O5 | EventStream Event Bus | Round 2 (OpenHands) | ✅ | `core/event_bus.py` + `governance/events/types.py` | Pub-sub event system |
| O6 | ComponentSpec (config-driven assembly) | Agent Lightning (R8) + OpenFang (R6) | ✅ | `core/component_spec.py` | `ComponentSpec[T]` = instance/class/factory/string/dict; `build_component()` unified resolver. R6 HAND.toml is same concept |
| O7 | ExecutionStrategy (debug/production dual mode) | Agent Lightning (R8) | ✅ | `governance/executor.py` | DebugStrategy (inspect state) + ProductionStrategy (timeout+crash isolation) |
| O8 | LLM Proxy Transparent Layer | Agent Lightning (R8) | ✅ | `core/llm_proxy.py` | Span collection + dynamic model override + middleware hooks |
| O9 | Store Collections Abstraction | Agent Lightning (R8) | ✅ | `core/store_collections.py` | Collection / Queue / KeyValue over SQLite with thread-safe access |
| O10 | Blueprint Declarative Agent | Round 1 + OpenFang (R6) | ✅ | `governance/policy/blueprint.py` | `blueprint.yaml`. **Gap vs HAND.toml**: missing fallback model chain, per-agent resource quota, tool profiles (Minimal/Coding/Research/Full) |
| O11 | Two-Tier Review (tiered_review) | Round 1 | ✅ | `governance/policy/tiered_review.py` + `governance/review.py` | Tiered review dispatch |
| O12 | Cross-Department Signal Protocol | Round 2 | ✅ | `governance/signals/cross_dept.py` | Typed signals + sibling rule + JSONL audit |
| O13 | Conditional Prompt Loading | Round 2 | ✅ | `governance/context/context_assembler.py` | Context-dependent prompt assembly |
| O14 | Fan-Out Parallel Execution | Round 1 | ✅ | `governance/pipeline/fan_out.py` | Parallel task dispatch |
| O15 | Harness Process Orchestration | Firecrawl (R5) | ⏸️ | — | Master process manages child services; auto-restart on crash. docker-compose covers this |
| O16 | Channel 5-Level Routing | OpenFang (R6) | ✅ | `channels/channel_router.py` | 5-level priority: Binding→Direct→UserDefault→ChannelDefault→Global |
| O17 | MCP Endpoint Exposure | bytebot (R10) | ✅ | `desktop_use/mcp_server.py` | DesktopMCPServer: 6 tools (screenshot/click/type/hotkey/scroll/find) |
| O18 | Monotonic Sequence ID | Agent Lightning (R8) | ⏸️ | — | Distributed clock drift fix. Not needed for single-machine |
| O19 | Cheapest-First Gate Chain | CC AutoDream (R28a) | ✅ | `src/core/gate_chain.py` | Escalating cost gates: regex→heuristic→small LLM→large LLM |
| O20 | Address Scheme Registry | CC peerAddress (R28a) | ✅ | `src/core/address_registry.py` | Unified agent/channel/service addressing |
| O21 | Unified Executor Interface | CC backends (R28a) | ✅ | `src/governance/agent_executor_interface.py` | Abstract agent execution backend |
| O22 | Protocol Messages | CC teammateMailbox (R28a) | ✅ | `src/core/protocol_messages.py` | Structured inter-agent communication |
| O23 | Middleware Pipeline | DeerFlow 2.0 (R28) | ✅ | `src/governance/pipeline/middleware.py` | Composable middleware chain for dispatch |
| O24 | Evaluator-Fix Loop | yoyo-evolve (R30) | ✅ | `SOUL/public/prompts/evaluator_fix_loop.md` | Max 9-round evaluate→fix cycle |
| O25 | SSE Progress Streaming | CC (R28a) | ✅ | `dashboard/server.js` | Server-Sent Events for collector progress |
| O26 | Subagent Limit Middleware | CC (R28a) | ✅ | `src/governance/dispatcher.py` | Hard cap on concurrent sub-agents |
| O27 | Methodology Router | PUA (R35) | ✅ | `src/governance/executor_prompt.py` + `SOUL/public/prompts/methodology_router.md` | Task type → thinking framework (RCA/FirstPrinciples/WorkingBackwards/etc). Cognitive mode overrides keyword match |
| O28 | Doctor Self-Diagnostic | AI Designer MCP (R37) | ✅ | `.claude/skills/doctor/SKILL.md` | Container/DB/collector/channel/GPU structured pass/warn/fail diagnosis |
| O29 | System Snapshot Injection | AI Designer MCP (R37) | ✅ | `.claude/hooks/session-start.sh` | Inject container/DB/uncommitted status at session start |
| O30 | Dedup Decision Matrix | Claudeception (R36c) | ✅ | implicit in skill management | 6-scenario dedup for pattern/skill installation |
| O31 | Agent Builder Meta-Tool | LobeHub (R16) | ✅ | `governance/agent_builder.py` | NL description → AgentSpec → blueprint.yaml + SKILL.md; keyword-based capability/authority detection |
| O32 | Skill CAS Distribution | LobeHub (R16) | ✅ | `governance/skill_cas.py` | SHA-256 content hash dedup, version history, rollback, transitive dependency resolution |

---

## 8. Human-AI Collaboration

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| H1 | Compaction Recovery Loop | Round 2 | ✅ | `.claude/hooks/pre-compact.sh` + `session-start.sh` | Pre-compact save + session-start restore |
| H2 | Frontmatter Standardization | Round 2 | ✅ | `blueprint.yaml` | Standardized metadata + explicit routing table |
| H3 | Fast Rule Scan (zero-LLM regex) | OpenAkita (R4) | ✅ | `governance/safety/fast_rule_scan.py` | Regex match strong signal words before context compression; rescue critical rules at zero LLM cost |
| H4 | Renderer Hijacking (output interception) | Carbonyl (R9) | ✅ | `desktop_use/output_interceptor.py` | OutputInterceptor: Win32 control text → UIA → clipboard, before OCR |
| H5 | Terminal as First-Class Display | Carbonyl (R9) | ✅ | `channels/terminal_display.py` | TerminalDisplay: ANSI panels, tables, progress bars |
| H6 | Input Event Backflow | Carbonyl (R9) | ✅ | `channels/event_backflow.py` | EventDispatcher: unified InputEvent model, middleware chain, pattern-based routing |
| H7 | Delegation Span (DELEGATION tracking) | OpenAkita (R4) | ✅ | `governance/audit/delegation_span.py` | DelegationTracker: parent→child chain, depth limits, token aggregation |
| H8 | Ephemeral Agent (temp profile, no disk) | OpenAkita (R4) | ⏸️ | — | Low value for current use case |
| H9 | Task Scheduling (sub-tasks) | bytebot (R10) | ✅ | `governance/task_scheduler.py` | TaskScheduler: priority queue + IMMEDIATE/SCHEDULED + poll loop |
| H10 | Synthesis Discipline | CC System Prompts (R28b) | ✅ | `SOUL/public/prompts/synthesis_discipline.md` | Never delegate understanding; prove comprehension before delegating |
| H11 | Collaboration Mode Switching | Codex CLI (R28c) | ✅ | `SOUL/public/prompts/collaboration_modes.md` | Suggest/auto-edit/full-auto mode switching |
| H12 | Strategic Compact Decision Table | CC+Headroom (R28/R33) | ✅ | `SOUL/public/prompts/compact_template.md` | 9-section mandatory compaction + adaptive pressure |
| H13 | Session Handoff Protocol | CC (R28) | ✅ | `SOUL/public/prompts/session_handoff.md` | Structured inter-session state transfer |
| H14 | Anti-Rationalization Hook (dynamic) | PUA (R35) | ✅ | `.claude/hooks/error-detector.sh` (L2-L4 injections) | Static rationalization-immunity.md upgraded to dynamic: hook injects counter-arguments at escalation thresholds |
| H15 | Failure-Mode → Methodology Switch Chain | PUA (R35) | ✅ | `SOUL/public/prompts/methodology_router.md` | Same error repeating → RCA; different errors → isolate; going in circles → Working Backwards; giving up → Search First |

---

## 9. Data & Search Patterns (from Agentic Search research)

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| D1 | Knowledge Graph + Blast Radius | Understand-Anything (R1-R2) | ✅ | `governance/knowledge_graph.py` | KnowledgeGraph: import-based BFS dependency graph + blast_radius() |
| D2 | Git Hash Incremental Strategy | Understand-Anything (R1-R2) | ✅ | `governance/learning/debt_scanner.py` | Commit hash based incremental scanning |
| D3 | Search→Expand→Trim Context Build | Understand-Anything (R1-R2) | ✅ | `governance/context/context_assembler.py` | HOT/WARM/COLD 3-tier context |
| D4 | Dual-Track Generation (LLM + heuristic) | Understand-Anything (R1-R2) | ✅ | `governance/budget/token_budget.py` | Model degradation chain as heuristic fallback |
| D5 | Objective Semantic Intent | Parallel (R3) | ✅ | `gateway/semantic_intent.py` | SemanticIntent: heuristic classification + department matching |
| D6 | Token Budget Multi-Dimensional Control | Brave (R3) | ✅ | `core/multi_budget.py` | MultiBudget: per-department/model/time-window axes with auto-reset |
| D7 | Hybrid RAG Dual-Source Fusion | Tavily (R3) | ⏸️ | — | For Construct3-RAG. Local + search fusion |
| D8 | Deep Research Multi-Round Loop | Firecrawl (R5) | ✅ | `core/deep_research.py` | ResearchSession: multi-round with dedup, finding cap, status FSM |
| D9 | Index Cache (quality-scored) | Firecrawl (R5) | ⏸️ | — | Quality=1000 highest priority; cache miss → real fetch. Scale concern |
| D10 | Text Tool Call Recovery (6 formats) | OpenFang (R6) | ✅ | `core/tool_call_recovery.py` | JSON block, XML, ReAct, function call, bare JSON, YAML-ish |

---

## 10. Eval & Testing

| # | Pattern | Source | Status | Location | Notes |
|---|---------|--------|--------|----------|-------|
| E1 | LLM-as-Judge + Rubric Scoring | R38 Inspect AI/promptfoo | ✅ | `governance/eval/scoring.py` | Three-level rubric (Satisfied/Partial/Not) + DimensionAwareFilter + evidence-anchored (RULERS) |
| E2 | Agent Trajectory Capture + Scoring | R38 promptfoo/AgentEvals | ✅ | `governance/eval/trajectory.py` | TrajectoryTracker + 3 matching modes (strict/unordered/subset) + efficiency/correctness metrics |
| E3 | Production→Test Corpus | R38 Braintrust | ✅ | `governance/eval/corpus.py` | Failed dispatches auto-feed into eval corpus for regression testing |
| E4 | Approval 5-Decision Chain | R38 Inspect AI | ✅ | `governance/approval.py` | approve/modify/reject/terminate/escalate with glob-based tool matching |
| E5 | Epochs + ScoreReducer | R38 Inspect AI | ✅ | `governance/eval/epochs.py` | Multi-run eval with mean/mode/max/pass_at_k aggregation + variance tracking |
| E6 | EarlyStopping Protocol | R38 Inspect AI | ✅ | `governance/eval/early_stopping.py` | Per-category adaptive stopping on 3 consecutive correct; min_samples guard |
| E7 | Regression Detection (Bootstrap CI) | R38 Braintrust | ✅ | `governance/eval/regression.py` | Bootstrap 10K samples, percentile CI, direction classification (improved/regressed/stable) |
| E8 | Decorator-Registry System | R38 Inspect AI | ✅ | `governance/eval/registry.py` | @register_eval decorator for task/scorer/reducer component discovery |
| E9 | Failure Root-Cause Classification | AutoAgent (R38b) | ✅ | `governance/eval/corpus.py` | Auto-tag rc:* root-cause tags (rc:stuck, rc:gate_failed, rc:doom_loop, etc.) |

---

## Cross-Reference: Source → Patterns

| Source Project | Stars | Round | Pattern IDs |
|---------------|-------|-------|-------------|
| *(32 open-source orchestrators)* | varies | 1 | S1, S3, S5, R1, R7, R14, P1, I1, I2, O1, O2, O3, O5, O10, O11, O14, D2, D3, D4 |
| OpenHands | 69K | 2 | O5, R1, P3, H1 |
| *(18 projects: claude-code-tips, pilot-shell, etc.)* | varies | 2 | S4, S6, S7, S8, S9, S10, R7, P3, P4, P5, I3, I4, I5, O12, O13, H1, H2 |
| Brave Search | — | 3 | P7, D6 |
| Firecrawl | 98K | 3, 5 | P8, P9, P10, P13, R8, R13, C1, C6, C7, O4, O15, S13, S15, I14, D8, D9 |
| Exa AI | — | 3 | C1 |
| Parallel Search Pro | — | 3 | C5, D5 |
| Tavily | — | 3 | P6, C3, D7 |
| OpenAkita | 1.4K | 4 | R1, R2, R4, R5, R6, C2, I6, I7, I8, I9, I11, I12, I13, H3, H7, H8 |
| OpenFang | 15.6K | 6 | S2, S4, S11, S12, S14, R1, R14, P2, C1, C8, O6, O10, O16, D10 |
| *(7 CV/VLM projects: labelU, UIED, OmniParser, etc.)* | varies | 7 | V1, V2, V3, V4, V5, V6, V7, V8, V9, V10 |
| Agent Lightning (Microsoft) | 15.5K | 8 | R3, R11, O6, O7, O8, O9, R9, R10, R12, I6, O18 |
| Carbonyl | 17.1K | 9 | P11, P12, P13, H4, H5, H6, V15 |
| bytebot | 10.6K | 10 | V11, V12, V13, I15, O17, H9 |
| *(Sycophancy research)* | — | — | S16, S17 |
| CC System Prompts | — | 28b | S18, H10 |
| CC AutoDream / peerAddress / backends | — | 28a | P14, O19, O20, O21, O22, O25, O26 |
| Codex CLI | — | 28c | S21, S22, R16, I17, I18, H11 |
| CC+Codex | — | 28 | S20, H12, H13 |
| DeerFlow 2.0 | — | 28 | R15, O23 |
| yoyo-evolve | — | 30 | S19, O24 |
| hindsight | — | 28e | I20 |
| CC (R29) | — | 29 | I16, I19 |
| tanweai/pua | 14K+ | 35 | S23, R17, R18, O27, H14, H15 |
| aresbit/skill-gov | 34 | 36a | R19 |
| blader/Claudeception | 2.2K | 36c | R19, O30 |
| AI Designer MCP | N/A | 37 | O28, O29 |
| Inspect AI / promptfoo / Braintrust | 19.2K | 38 | E1, E2, E3, E4, E5, E6, E7, E8 |
| kevinrgu/autoagent | ~0 | 38b | I27, E9, S25 |
| self-improving-agent (ClawHub) | — | 23 | I21, I24, I25, S24 |
| DeerFlow 2.0 | 55.2K | 29 | P15, P16, I22, I23 |
| ClawHub elite-longterm-memory | 305K | 14 | I26, P17, S26 |
| entrix | — | 15 | R20 |
| LobeHub | — | 16 | O31, O32 |

---

## De-duplication Notes

These patterns appeared across multiple rounds and are consolidated above:

| Pattern | Appeared in | Consolidated as |
|---------|------------|----------------|
| Loop/Stuck Detection | R1 (doom loop), R2 (StuckDetector), R4 (Signature Repeat + Progress Timeout), R6 (result-aware + ping-pong), R8 (Watchdog) | **R1** (core) + **R3** (Watchdog variant) |
| Cost Tracking | R3 (GenerateResult.cost_dollars), R5 (CostTracking with stack trace + cutoff), R6 (per-agent token/hour) | **C1** |
| Context Compression | R2 (4 condensers), R3 (water-level stop hook), R5 (transformer timing) | **P3** |
| Prompt Injection Defense | R2 (test suite), R5 (LLM hardening), R6 (3-level scanner) | **S4** |
| ComponentSpec / Config-Driven | R6 (HAND.toml), R8 (ComponentSpec) | **O6** |
| Audit Hash Chain | R1 (hash chain), R6 (Merkle audit) | **R14** |
| Blueprint / Declarative Agent | R1 (blueprint.yaml), R6 (HAND.toml) | **O10** |
| Loop Detection | R1 (doom loop), R2 (StuckDetector), R4 (Signature Repeat), R6 (result-aware), R8 (Watchdog), R28 (hook) | **R1** (core) + **R3** (Watchdog) + **R15** (hook) |
| Prompt Injection Defense | R2 (test suite), R5 (LLM hardening), R6 (3-level scanner), R30 (boundary nonce) | **S4** (core) + **S19** (nonce variant) |

---

## Priority Summary

### P0 — Do Next

| ID | Pattern | Est. Effort |
|----|---------|-------------|
| V1 | VLM Zone Stage (cvui) | Medium |

### P1 — Near Term (cvui)

| ID | Pattern | Est. Effort |
|----|---------|-------------|
| P11 | LoDPI Adaptive Downscaling (cvui) | Low |
| V2 | CNN ClassifyStage (cvui) | Medium |
| V4 | Format Converter to_coco/yolo (cvui) | Low |
| V7 | Image Tiling (cvui) | Medium |

### P1 — Near Term (Orchestrator)

All 5 patterns implemented ✅ (2026-04-04 steal/p1-cleanup branch)

### DEFER (assigned to separate sessions)

| Pattern | Source | Notes |
|---------|--------|-------|
| Reverse Prompting + Proactive Tracker | R23 | TG bot proactive mode — spec exists (📐) |
| Clarification-First Workflow | R29 | Prompt engineering refactor |

### Previously Deferred → Now Done

| Pattern | Source | Completed |
|---------|--------|-----------|
| Growth Loops (Curiosity/Pattern/Outcome) | R23 | ✅ d050fb6 |
| Ontology Graph Layer | R14 P2 | ✅ 13ab426 |
| Hooks 16-Event Lifecycle Extension | R38 | ✅ ef9bcc8 |
