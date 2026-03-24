# Attribution — Standing on the Shoulders of Giants

This project draws inspiration, patterns, and architectural ideas from many
open-source projects. We believe in giving credit where credit is due.

> "Good artists copy, great artists steal." — Picasso (probably)
>
> We steal, then we document it.

All URLs verified 2026-03-24. One project (Lucentia) has since been deleted.

---

## Tier S — Core Architectural Influences

### [edict](https://github.com/cft0808/edict)
**What we took:** The 三省六部 governance model for AI orchestration. Their
implementation of 门下省 (Menxia) as a mandatory quality gate with veto authority
directly shaped our Scrutinizer. Proved that imperial bureaucratic structures
are not just a metaphor — they encode real separation-of-powers constraints.
**Where it lives:** The entire governance pipeline — `src/governance/scrutiny.py`,
`src/governance/executor.py`, `src/governance/dispatcher.py`.

### [danghuangshang](https://github.com/wanikua/danghuangshang)
**What we took:** Multi-regime governance concept (Tang three-branch vs Ming
cabinet system), persistent per-agent memory via SQLite, automated code review
on state transitions, 14-18 specialized agents coordinated through hierarchical
channels. Validated that the 三省六部 model scales beyond toy examples.
**Where it lives:** Per-department `run-log.jsonl`, governance model flexibility,
`departments/*/blueprint.yaml` declarative config.

### [organvm-engine](https://github.com/meta-organvm/organvm-engine)
**What we took:** Seed Contract pattern, Authority Ceiling (READ → PROPOSE →
MUTATE → APPROVE hierarchy), Punch-in/Punch-out coordination for parallel agents.
**Where it lives:** `AuthorityCeiling` enum in `src/governance/policy/blueprint.py`.

### [Paperclip](https://github.com/paperclipai/paperclip)
**What we took:** Atomic Checkout (file-level locking to prevent concurrent
conflicts), Heartbeat Protocol, Budget Hard Stop pattern.
**Where it lives:** `PunchClock` in `src/governance/executor.py`,
`TokenAccountant` in `src/governance/budget/`.

### [Ferment](https://github.com/diapod/ferment)
**What we took:** Intent-based routing — mapping user intents to capabilities
rather than hardcoding department names. Quality-aware scheduling with policy profiles.
**Where it lives:** `IntentRoute` in `src/gateway/routing.py`,
`PolicyProfile` (LOW_LATENCY / BALANCED / HIGH_QUALITY).

### [SoulFlow-Orchestrator](https://github.com/berrzebb/SoulFlow-Orchestrator)
**What we took:** Gateway three-tier classification (NO_TOKEN / DIRECT / AGENT),
Phase Loop, Critic Gate, Novelty Policy. Most importantly: the **Soul/Heart
separation** — agent identity split into soul (principles) + heart (expression
style) + extra_instructions, forkable and scopeable. This directly inspired
our `SOUL/` directory architecture (public vs private, boot.md compilation).
**Where it lives:** `RequestTier` in `src/gateway/classifier.py`,
`check_novelty()` in `src/governance/policy/novelty_policy.py`,
`SOUL/` directory structure (identity/prompts/experiences).

### [Lumina OS](https://github.com/fractalsense-ai/lumina-os)
**What we took:** Domain Pack concept (self-contained department configs),
deterministic template fallback when LLM fails, hash-chain audit logs.
**Where it lives:** `departments/*/` directory structure,
`get_deterministic_fallback()` in `src/governance/policy/deterministic_resolver.py`.

### [ComposioHQ agent-orchestrator](https://github.com/ComposioHQ/agent-orchestrator)
**What we took:** Eight-slot plugin system concept, reactive YAML lifecycle.
**Where it lives:** Influenced `blueprint.yaml` schema design.

---

## Tier A — Significant Pattern Contributions

### [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist)
**What we took:** Manifest-driven plugin discovery — each plugin declares its
capabilities, semantic tags, and function definitions in a manifest file.
The engine scans plugin directories at startup and auto-registers everything.
**Where it lives:** `manifest.yaml` files in `departments/*/`,
`registry.py` in `src/governance/registry.py`. Tags field for semantic
intent matching in LLM routing prompts.
**Date stolen:** 2026-03-24

### [OpenHands](https://github.com/All-Hands-AI/OpenHands)
**What we took:** EventStream typed event bus (Action/Observation pattern),
Condenser context compression (composable strategies),
StuckDetector (5-pattern loop detection).
**Where it lives:** `src/governance/pipeline/fan_out.py` (event emission),
`src/core/condenser/` (compression pipeline),
`src/governance/stuck_detector.py`.

### [pilot-shell](https://github.com/maxritter/pilot-shell)
**What we took:** Compaction recovery — PreCompact hook saves context snapshot
before compression, enables rollback if compacted context loses critical info.
Conditional prompt loading based on task type.
**Where it lives:** `src/core/condenser/compaction_recovery.py`.

### [spencermarx/orc](https://github.com/spencermarx/orc)
**What we took:** Scout-Synthesize pattern (orchestrator never reads raw data,
sends scouts), two-layer review, file signal protocol.
**Where it lives:** Influenced executor's context protection strategy.

### [workflow-orchestration](https://github.com/barkain/claude-code-workflow-orchestration)
**What we took:** Scratchpad file passing between agents (pass paths not content),
`DONE|{path}` protocol, token three-layer compression.
**Where it lives:** Influenced inter-department context passing design.

### [claude-prove](https://github.com/mjmorales/claude-prove)
**What we took:** ACB Intent Manifest, Negative Space testing, CAFI file index.
**Where it lives:** `src/governance/learning/cafi_index.py`.

---

## Tier B — Specific Pattern Pickups

| Project | URL | Pattern |
|---------|-----|---------|
| [Conitens](https://github.com/seunghwaneom/Conitens) | Verify Gate hard constraints, Typed Handoff state machine |
| [claude-swarm](https://github.com/AudiRamadyan/claude-swarm) | Notebook Pattern (externalized state), Immutable Base Constraints |
| [codingbuddy](https://github.com/JeremyDev87/codingbuddy) | PLAN→ACT→EVAL loop, Anti-Sycophancy, Complexity Classifier |
| [swarm-tools](https://github.com/FelipeDaza7/swarm-tools) | Event Sourcing + WorkerHandoff contract |
| [safethecode/orc](https://github.com/safethecode/orc) | Doom Loop Detection, Tournament Optimizer |
| [Orchestra](https://github.com/Traves-Theberge/Orchestra) | Claim-Execute-Release, Provider Cascade |
| [bored](https://github.com/TannerBurns/bored) | Stage Pipeline + Deslop (anti-AI-smell) |
| [project-artemis](https://github.com/ajansen7/project-artemis) | Two-tier memory (hot/extended), Learn-from-edit loop |
| [Lucentia](https://github.com/wngfra/Lucentia) | TokenAccountant budget degradation chain *(repo deleted, patterns preserved in local notes)* |

### Second Round (2026-03-24)

| Project | URL | Pattern |
|---------|-----|---------|
| [claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice) | RPI gating + 3-tier permissions |
| [claude-code-tips](https://github.com/ykdojo/claude-code-tips) | Stop hook context watermark 85% |
| [CCPlugins](https://github.com/brennercruvinel/CCPlugins) | Checkpoint resume |
| [prompt-master](https://github.com/nidhinjs/prompt-master) | PAC position structure 30/55/15, anti-pattern lint |
| [pro-workflow](https://github.com/rohitg00/pro-workflow) | Phase rollback, 5-dimension confidence scoring |
| [claude-cognitive](https://github.com/GMaN1911/claude-cognitive) | Attention decay HOT/WARM/COLD, usage-based experience eviction |
| [claude-bug-bounty](https://github.com/shuvonsec/claude-bug-bounty) | 4-Gate validation framework, A→B signal method |
| [my-claude-code-setup](https://github.com/centminmod/my-claude-code-setup) | Prompt injection test suite, Dual-AI cross-validation |
| [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | Frontmatter standardization + explicit route tables |

### Earlier Influences (pre-steal-sheet)

| Project | URL | Pattern |
|---------|-----|---------|
| [gstack](https://github.com/gstack-ai/gstack) | **SOUL cognitive system**: CEO decision principles, 4 cognitive modes (Direct/ReAct/Hypothesis/Designer) that form the core of `SOUL/public/prompts/cognitive_modes.md` and `classify_cognitive_mode()` |
| [Axe](https://github.com/axe-ai/axe) | Department memory via run-logs, GC feedback loop, opaque boundary principle |
| [Parlant](https://github.com/parlant-ai/parlant) | Dynamic context trimming (Contextual Matching Engine) |
| [Letta/MemGPT](https://github.com/letta-ai/letta) | Structured persistent memory blocks — influenced `SOUL/` architecture (experiences.jsonl, identity.md, hall-of-instances) |
| [Understand-Anything](https://github.com/Lum1104/Understand-Anything) | Stage-gated pipeline, Git hash incremental strategy |

---

## Conceptual References

| Concept | Source | Status |
|---------|--------|--------|
| Think-Act-Observe loop | ReAct (LangChain) | Implemented in ReAct cognitive mode |
| Hypothesis-Driven Agent | DATAGEN | Implemented in Hypothesis cognitive mode |
| Design-First Agent | gstack plan-review | Implemented in Designer cognitive mode |
| Checkpoint-resume | Trigger.dev | Referenced |
| Sandbox diff review | Plandex | Referenced |
| Session rewind | Google ADK | Referenced for compaction recovery |
| Beam multi-model verification | big-AGI | Referenced |

---

## Philosophy

> "Good artists copy, great artists steal." — Picasso (probably)

We don't just copy code — we study *patterns* and *principles*, then adapt
them to our architecture. The specific mechanisms that make it all work are
often inspired by others.

This kind of selection is itself a design decision — for every pattern we
adopted, three alternatives were discarded.

What each project contributed is documented above. What we contributed is the
integration: stitching imperial bureaucracy, AI identity systems, manifest-driven
discovery, and intent routing into something that actually runs 24/7 as a
butler in Docker.

Every pattern listed here has been significantly adapted:
- G-Assist uses JSON-RPC over stdin; we use YAML manifests loaded at import time
- OpenHands has a monolithic EventStream; we have department-scoped fan-out
- Paperclip's Atomic Checkout is per-file; our PunchClock is per-department
- edict/danghuangshang run on Discord/Feishu; we run Agent SDK in Docker

The best ideas are the ones you can't tell where they came from.

This document exists because we'd rather be honest about where things came
from than pretend we're geniuses. If you see your project listed here and
think we got the attribution wrong, open an issue.
