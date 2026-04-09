# Orchestrator Architecture

## System Overview

Orchestrator is a Claude Code enhancement layer — agents, skills, hooks, and an identity framework that make every session contextually aware. The primary interface is `.claude/agents/*.md` (8 specialized agents auto-discovered by Claude Code) plus skills and hooks. A Docker background service handles data collection, analysis, and dashboard.

## Architecture Diagram

```
                          ┌─────────────┐
                          │  Dashboard   │  ← face (HTTP :23714)
                          └──────┬───────┘
                                 │
  ┌──────────┐   events.db  ┌───┴────────────────────┐
  │ channels │◄────────────►│         core/           │
  │ TG/WX/..│              │  event_bus · llm_router  │
  └──────────┘              │  config · cost_tracking  │
                            │  component_spec          │
                            └──┬──────┬──────┬────────┘
                               │      │      │
              ┌────────────────┤      │      ├────────────────┐
              ▼                ▼      │      ▼                ▼
       ┌────────────┐  ┌──────────┐  │  ┌───────────┐  ┌──────────┐
       │ collectors  │  │ storage  │  │  │ analysis  │  │governance│
       │ git·steam·  │  │ EventsDB │  │  │ profiles  │  │ dispatch │
       │ vscode·...  │  │ vectors  │  │  │ bursts    │  │          │
       └─────────────┘  └──────────┘  │  └───────────┘  └──────────┘
                                      │
                          ┌───────────┴───────────┐
                          │     side modules       │
                          ├────────────┬───────────┤
                          │desktop_use │ browser   │
                          │ GUI auto   │ CDP/tabs  │
                          └────────────┴───────────┘
```

**Data flow**: `collectors → storage → analysis → governance → channels`

## Module Index

### Documented Modules

| Module | Purpose | Key Files | Docs |
|--------|---------|-----------|------|
| `collectors/` | Data collection, 11 sources (Git, Steam, VS Code, browser, etc.) | `base.py`, `registry.py`, `yaml_runner.py` | [collectors.md](modules/collectors.md) |
| `storage/` | EventsDB + vector search + schema management + dedup/hotness scoring | `events_db.py`, `vector_db.py`, `_schema.py` | [storage.md](modules/storage.md) |
| `governance/` | Task dispatch: Governor + Scrutiny + execution | `governor.py`, `dispatcher.py`, `executor.py` | [governance.md](modules/governance.md) |
| `channels/` | Multi-channel interface: Telegram, WeChat, local chat | `telegram/`, `wechat/`, `formatter.py` | [channels.md](modules/channels.md) |
| `desktop_use/` | GUI automation (Windows): ABC injection, CV+OCR perception | `engine.py`, `actions.py`, `perception.py` | [desktop-use.md](modules/desktop-use.md) |
| `core/browser_*` | Chrome CDP wrapper, tab pool management | `browser_cdp.py`, `browser_navigation.py` | [browser-runtime.md](modules/browser-runtime.md) |
| `governance/pipeline/` | Execution pipeline: output compression, phase rollback, fan-out, middleware | `output_compress.py`, `fan_out.py`, `middleware.py` | [middleware_pipeline.md](middleware_pipeline.md) |

### Other Modules (no dedicated docs yet)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `core/` | Infrastructure: event bus, LLM routing, config, cost tracking, gate chain, address registry | `event_bus.py`, `llm_router.py`, `config.py`, `cost_tracking.py`, `gate_chain.py` |
| `analysis/` | Insight extraction, profiling, burst detection | `profile_analyst.py`, `burst_detector.py` |
| `gateway/` | Intent routing + policy config | `routing.py`, `intent_rules.py`, `semantic_intent.py` |
| `voice/` | TTS/STT voice pipeline | — |
| `governance/safety/` | Safety pipeline: injection detection, drift detection, convergence, dual-model verify, prompt lint | `injection_test.py`, `drift_detector.py`, `convergence.py`, `dual_verify.py` |
| `governance/condenser/` | Context compression: 4 strategies (Recent, Amortized, LLMSummarizing, WaterLevel) | `pipeline.py`, `water_level.py`, `amortized_forgetting.py` |
| `governance/audit/` | Audit chain: WAL, evolution chain, execution snapshot, file ratchet, skill vetting | `wal.py`, `evolution_chain.py`, `file_ratchet.py` |
| `governance/context/` | Context engine: structured memory, memory tiers, context assembler, memory bridge | `structured_memory.py`, `memory_tier.py`, `context_assembler.py` |
| `governance/learning/` | Learning pipeline: experience curation, edit learning, debt scanning, instinct pipeline | `learn_from_edit.py`, `experience_cull.py`, `debt_scanner.py` |
| `governance/preflight/` | Pre-flight: 5-dimension confidence scoring | `confidence.py` |
| `governance/quality/` | Quality pipeline: Critic scoring, Fix-First strategy | `critic.py`, `fix_first.py` |
| `SOUL/tools/` | SOUL tools: compiler, memory pipeline (synthesis, gate, staleness) | `compiler.py`, `memory_synthesizer.py` |

## Design Philosophy

- **ABC Injection** — All core components define interfaces through abstract base classes. `ScreenCapture`, `WindowManager`, `OCREngine`, `ActionExecutor` can all be swapped at construction time. No lock-in to any specific backend.

- **Two-Layer Agent Architecture** — Agents (WHO) and capabilities (WHAT) are separated. 8 agents in `.claude/agents/*.md` declare their identity, tools, model, and permissions via frontmatter — Claude Code auto-discovers them. The Docker governance layer (Governor → Scrutiny → Execution) provides an additional autonomous dispatch path. Authority levels from `READ` to `MUTATE` are enforced via tool allowlists. Management philosophy: [SOUL/management.md](../../SOUL/management.md).

- **SOUL Inheritance** — `compiler.py` compiles identity source files into `boot.md`. New instances read it to restore judgment and attitude. Not imitation — inheritance. Short-term continuity uses `--resume` (same instance); long-term continuity uses SOUL files across instances. Details: [SOUL/README.md](../../SOUL/README.md).

## Knowledge Base

- [PATTERNS.md](PATTERNS.md) — Pattern library (217 patterns from 46 rounds of research across 100+ open-source projects)
- [ROADMAP.md](ROADMAP.md) — Implementation roadmap
- [fact-expression-split.md](fact-expression-split.md) — Original research: anti-sycophancy architecture (fact-expression separation)
