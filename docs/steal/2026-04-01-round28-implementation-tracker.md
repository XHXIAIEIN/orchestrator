# Round 28 Implementation Tracker

> Date: 2026-04-01
> Branches: steal/round23-p1, steal/digest-apr01
> Sources: 6 sub-rounds + 8 new reports, ~93 + 70 patterns total

## Quick Comparison: All P0 Patterns

| # | Pattern | Source | Category | Status | Impact |
|---|---------|--------|----------|--------|--------|
| 1 | Governor Synthesis Discipline | CC System Prompts | Prompt | ✅ Done | Agent output quality |
| 2 | Verification Gate Adversarial | CC Verification Agent | Prompt | ✅ Done | Bug escape rate |
| 3 | PreCompact 9-Section Structure | CC Compact Service | Hook | ✅ Done | Context continuity |
| 4 | Collaboration Mode Switching | Codex CLI | Prompt | ✅ Done | Task precision |
| 5 | Cheapest-First Gate Chain | CC AutoDream | Code | ✅ Done | Background task efficiency |
| 6 | Address Scheme Registry | CC peerAddress | Code | ✅ Done | Unified routing |
| 7 | Unified Executor Interface | CC backends/types | Code | ✅ Done | Agent abstraction |
| 8 | Protocol Messages | CC teammateMailbox | Code | ✅ Done | Structured comms |
| 9 | Agent Registry | CC concurrentSessions | Code | ✅ Done | Agent discovery |
| 10 | Guard.sh Banned Prefixes | Codex ExecPolicy | Security | ✅ Done | Command injection defense |
| 11 | Guardian Risk Assessment | Codex policy.md | Security | ✅ Done | Semantic risk eval |
| 12 | Events-Before-Container | CC Teleport | Code | 📋 Pending | Dispatch race elimination |
| 13 | Lock File mtime = State | CC consolidationLock | Code | 📋 Pending | Zero-dep state tracking |
| 14 | Unified Message Router | CC SendMessageTool | Code | 📋 Pending | Single entry routing |
| 15 | Stateful Event Stream Classifier | CC ExitPlanModeScanner | Code | 📋 Pending | Output parsing |
| 16 | Self-Injection Defense | CC YOLO Classifier | Security | 📋 Pending | Transcript filtering |
| 17 | Bones-Soul Split Persistence | CC Buddy types | Architecture | 📋 Pending | State persistence |
| 18 | Untrusted-Source Setting Exclusion | CC paths.ts | Security | 📋 Pending | Config trust layers |
| 19 | Progressive Bundle Fallback | CC gitBundle | Code | 📋 Pending | Context shipping |
| 20 | Session Overage Confirmation | CC ultrareview | UX | 📋 Pending | One-time consent |
| 21 | Self-Contained Snapshot Coalescing | CC ccrClient | Code | 📋 Pending | Dashboard streaming |
| 22 | Three-Tier Feature Read | CC GrowthBook | Code | 📋 Pending | Config caching |
| 23 | Snapshot-Based Immutable Registry | claw-code | Code | 📋 Pending | Startup perf |
| 24 | Token-Based Routing + Diversity | claw-code | Code | 📋 Pending | Route intelligence |
| 25 | Permission Denial Inference | claw-code | Code | 📋 Pending | Pre-execution gates |
| 26 | Hierarchical Config Deep Merge | claw-code | Config | 📋 Pending | Config flexibility |
| 27 | 4-Way Parallel Retrieval + RRF | hindsight | Code | 📋 Pending | Recall quality |
| 28 | Retain-Time Link Bounding | hindsight | Architecture | 📋 Pending | Graph governance |
| 29 | Token Budget Semantic Layers | hindsight | Code | 📋 Pending | Cost control |
| 30 | Disposition Parameterization | hindsight | Prompt | 📋 Pending | Persona tuning |
| 31 | Memory Pipeline 2-Phase | Codex CLI | Code | 📋 Pending | Auto memory |
| 32 | Memory No-Op Gate | Codex CLI | Prompt | 📋 Pending | Memory quality |
| 33 | Exec Policy Rule Engine | Codex CLI | Security | 📋 Pending | Command parsing |
| 34 | babysit-pr Skill | Codex CLI | Skill | 📋 Pending | PR automation |
| 35 | Compaction as Handoff Summary | Codex CLI | Prompt | ✅ Done | Session continuity |

## P1 Notable Patterns (Next Wave)

| Pattern | Source | Description |
|---------|--------|-------------|
| Two-State Delivery | CC InboxPoller | Busy→queue, idle→drain |
| Auto-Resume on Message | CC SendMessageTool | Stopped agents auto-wake |
| Tick-Driven Proactive Loop | CC Kairos | Periodic tick + blocking budget |
| Control Protocol | CC Bridge | Dashboard→Agent interrupt/set_model |
| Permission Bridge with updatedInput | CC leaderPermission | Modify tool args then approve |
| Closure-Scoped Agent State | CC autoDream | Testability via closure init |
| Background-Agent-as-Visible-Task | CC DreamTask | UI transparency for bg agents |
| 4-Phase Consolidation | CC consolidationPrompt | Orient→Gather→Consolidate→Prune |
| Keyword Trigger w/ Context Exclusion | CC keyword.ts | Smart intent routing |
| Agent Summary 1-sentence | CC agent_summary | Haiku micro-service progress |
| Explore Agent Read-Only | CC explore_agent | Tool permission isolation |
| Simplify 3-Agent Parallel | CC simplify_skill | Dimension-separated review |
| Agentic Loop Max Iterations | claw-code | 16-iteration cap |
| History Log Milestones | claw-code | Phase-level run records |
| Frozen Dataclass Convention | claw-code | Immutable models |
| Compat-Harness Methodology | claw-code | Evidence-driven steal |
| MPFP Sub-linear Graph Traversal | hindsight | Budget-aware graph search |
| Mental Model Auto-Synthesis | hindsight | Auto-update SOUL/memory |
| Extension Triple | hindsight | Code-level validators |
| Per-Operation LLM Config | hindsight | Task→model mapping |
| Agent Role Config Layers | Codex CLI | Config-based roles |
| Agent Registry Depth Limits | Codex CLI | Nesting cap |
| Review 8 Bug Criteria | Codex CLI | Precise review rules |
| Orchestrator Coordinator-Only | Codex CLI | Don't work while coordinating |

## Digest Session: steal/digest-apr01 (10 new patterns)

| # | Pattern | Source | Category | Status |
|---|---------|--------|----------|--------|
| D1 | Loop Detection Hook | DeerFlow 2.0 | Hook | ✅ Done |
| D2 | Config Protection Hook | Everything CC | Hook | ✅ Done |
| D3 | Boundary Nonce (injection defense) | yoyo-evolve | Security | ✅ Done |
| D4 | Strategic Compact Decision Table | Everything CC | Prompt | ✅ Done |
| D5 | Adaptive Pressure Levels | Headroom | Prompt | ✅ Done |
| D6 | Session Handoff Protocol | Everything CC | Prompt | ✅ Done |
| D7 | Evaluator-Fix Loop | yoyo-evolve | Prompt | ✅ Done |
| D8 | Middleware Pipeline | DeerFlow 2.0 | Code | ✅ Done |
| D9 | Memory Staleness Annotator | CC R29 | Tool | ✅ Done |
| D10 | Instinct Learning Pipeline | Everything CC | Code | ✅ Done |

## Implementation Log

| Time | Action | Commit |
|------|--------|--------|
| 23:xx | Raw steal docs committed | e4b884c |
| 23:xx | 6 parallel agents dispatched (R28 p1) | — |
| 01:xx | R28 p1 agents complete: synthesis/verification/compact/security/core4 | e844321→e94b0ef |
| 15:xx | Digest session: 3 security hooks | bc0816b |
| 15:xx | Digest session: compact template upgrade | 7d166fa |
| 15:xx | Digest session: architecture (handoff/evaluator/middleware) | 979d117 |
| 15:xx | Digest session: learning pipeline + staleness | 678c582 |
| 15:xx | Merged steal/digest-apr01 → main | — |
