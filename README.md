# Orchestrator

Every time you start a new Claude Code session, it's a stranger. It doesn't know what you were working on yesterday, what keeps breaking, or that you've been pushing commits at 3am for the past week.

Orchestrator fixes that.

It's a Claude Code enhancement layer — skills, hooks, agents, and an identity framework that make every session start where the last one left off. Plus a background service for data collection and analysis when you need it.

**What it does:**
- **Agents** — 8 specialized agents (`.claude/agents/*.md`) with isolated permissions and models, auto-discovered by Claude Code
- **Skills** — `/steal` (systematic knowledge extraction), `/doctor` (full-stack diagnostics), verification gates, and more
- **Identity** — SOUL framework that carries personality, voice calibration, and relationship context across sessions
- **Hooks** — guard rails that catch dangerous operations before they execute
- **Collectors** — 11 background data collectors (Git, browser, editor, Steam, music...) that only grab what exists on your machine
- **Channels** — Telegram, WeChat, and desktop notifications for remote control and approval

## Quick Start

### As a Claude Code Plugin (Primary)

The agents, skills, hooks, and SOUL system work directly in Claude Code — no Docker needed:

```
orchestrator/
├── .claude/agents/     # 8 agents: engineer, architect, reviewer, sentinel, operator, analyst, inspector, verifier
├── .claude/skills/     # /steal, /doctor, /status, /collect, verification-gate, etc.
├── .claude/hooks/      # guard rules, audit logging
├── SOUL/               # Identity persistence framework
└── CLAUDE.md           # Project-level instructions
```

Just open Claude Code in the orchestrator directory. Agents are auto-discovered, skills are available via `/slash` commands, hooks activate on matching events.

### With Docker (Background Service)

For 24/7 data collection, analysis, and dashboard:

```bash
# Clone
git clone git@github.com:XHXIAIEIN/orchestrator.git
cd orchestrator

# Configure
cp .env.example .env
# Edit .env — at minimum, set ANTHROPIC_API_KEY

# Start
docker compose up --build -d

# Verify
curl -s http://localhost:23714/api/health
# → {"status":"ok"}
```

Dashboard: http://localhost:23714

## Agents

8 agents in `.claude/agents/`, each a markdown file with frontmatter declaring tools, model, and permissions. Claude Code auto-discovers them — drop a new `.md` file in and it's available next session.

| Agent | Role | Model | Authority |
|-------|------|-------|-----------|
| `engineer` | Write code, fix bugs, run tests | Sonnet | MUTATE (Read + Write + Edit + Bash) |
| `architect` | Design solutions, plan implementations, refactor | Opus | MUTATE |
| `reviewer` | Code review, spec compliance, anti-sycophancy | Sonnet | READ-ONLY (Read + Glob + Grep) |
| `sentinel` | Security audit, injection scanning, CVE checks | Sonnet | READ + Bash |
| `operator` | Infrastructure: Docker, DB, collector repairs | Sonnet | MUTATE |
| `analyst` | Metrics, health assessment, anomaly detection | Haiku | READ + Bash |
| `inspector` | Doc rot, config drift, expression rewriting | Haiku | READ-ONLY |
| `verifier` | End-to-end verification, evidence chains | Sonnet | READ + Bash |

Authority is enforced via tool allowlists in each agent's frontmatter — a READ-ONLY agent literally cannot call Write or Edit.

### How Tasks Flow

When you work in Claude Code, the model decides when to dispatch agents based on context:

```
Your request → Model selects agent → Agent executes with constrained tools → Result returned
```

For multi-step workflows, skills like `subagent-driven-development` orchestrate the sequence: implement → spec review → quality review → commit.

## Skills

| Skill | What it does |
|-------|-------------|
| `/steal` | Systematic knowledge extraction from open-source projects (46 rounds, 217 patterns) |
| `/doctor` | Full-stack diagnostics: container, DB, collectors, channels, GPU, disk |
| `/status` | Runtime status and recent collection summary |
| `/collect` | Manually trigger a data collection run |
| `/analyze-ui` | UI detection via cvui pipeline |
| `verification-gate` | Five-step evidence chain before declaring any task complete |
| `systematic-debugging` | Structured debugging: investigate → isolate → fix → verify |

## Collectors

11 collectors, each independent. Missing data sources are silently skipped — no errors, no configuration needed:

| Collector | What it collects |
|-----------|-----------------|
| Claude | Claude Code conversation history |
| Claude Memory | Claude memory artifacts |
| Browser | Chrome browsing history |
| Git | Local repository commits |
| VS Code | Editor usage time |
| Codebase | Project's own git history |
| Network | Locally running services (port scan) |
| Steam | Game playtime |
| QQ Music | Playback history |
| YouTube Music | Playback history |
| System Uptime | System uptime (YAML-driven, experimental) |

Collectors come in two flavors:
- **Python collectors** — subclass `ICollector`, implement `collect()`. See `src/collectors/_example/` for a template.
- **YAML collectors** — declare source, extraction, and transform rules in `manifest.yaml`. The `yaml_runner` engine handles execution. No Python needed.

## SOUL (Identity Persistence)

AI personality framework. Each new session reads the compiled `boot.md` to restore identity, voice calibration, and relationship context. Not a perfect clone — but close enough to maintain continuity.

```
Short-term: claude --resume (same instance, full memory)
Long-term:  SOUL files (new instance, reconstructed identity)
```

See [SOUL/README.md](SOUL/README.md) for the full framework design.

## Dashboard

Three pages, all real-time via WebSocket:

- **Dashboard** `/` — daily report, agent status, insight analysis, attention debts, activity heatmap
- **Pipeline** `/pipeline` — data flow visualization, collector → analysis → governance full-chain animation, system logs
- **Agents** `/agents` — agent observability: event stream, tool calls, thinking process

## Channel Layer

Multi-platform message bus for remote control:

| Channel | Outbound | Inbound | Approval |
|---------|----------|---------|----------|
| Telegram | Yes | Yes (polling) | Inline keyboard |
| WeChat | Yes | Yes | Text commands |
| WeCom | Yes (webhook) | — | — |

Commands: `/status`, `/tasks`, `/run <scenario>`, `/approve <id>`, `/deny <id>`, `/pending`, `/yolo`, `/noyolo`

All channels are optional — the system works fully without any of them configured.

## Governance (Docker Service)

The Docker service includes a governance layer for autonomous task dispatch:

| Layer | Component | Role |
|-------|-----------|------|
| Decision | Governor | Extracts tasks from insights, selects cognitive mode |
| Review | Scrutiny | Feasibility check — blast radius, reversal risk, confidence scoring |
| Execution | Departments | Parallel task execution, constrained by policies |

Governor automatically selects a cognitive mode based on task complexity:

| Mode | When | Approach |
|------|------|----------|
| Direct | Fix a typo, tweak a param | Execute immediately |
| ReAct | Fix a bug, add a feature | Think → Act → Observe → Loop |
| Hypothesis | "Why doesn't X work?" | Hypothesize → Verify → Confirm/Refute |
| Designer | Refactor, new subsystem | Design first → Review → Then implement |

## API

Interactive docs: http://localhost:23714/api-reference (Swagger UI)

```bash
# Global status
curl -s http://localhost:23714/api/brief

# Open attention debts
curl -s 'http://localhost:23714/api/debts?status=open'

# Agent live status
curl -s http://localhost:23714/api/agents/live

# Task execution replay (full thinking chain + tool calls)
curl -s http://localhost:23714/api/agents/42/trace
```

## Directory Structure

```
orchestrator/
├── .claude/
│   ├── agents/         # 8 agents (auto-discovered by Claude Code)
│   ├── skills/         # Slash commands and skill definitions
│   ├── hooks/          # Guard rules, audit logging
│   └── boot.md         # Compiled SOUL identity (generated)
├── src/
│   ├── core/           # Infrastructure: config, event bus, LLM routing, cost tracking
│   ├── governance/     # Governance pipeline (Docker service)
│   ├── analysis/       # Daily reports, insights, profiling, burst detection
│   ├── collectors/     # Data collectors (Python + YAML-driven)
│   ├── channels/       # Telegram, WeChat, WeCom adapters
│   ├── storage/        # EventsDB (SQLite), Qdrant vector store
│   └── scheduler.py    # Scheduler entry point
├── departments/        # Department definitions (Docker governance layer)
├── SOUL/               # AI personality framework (source files)
├── dashboard/          # Frontend (Express + WebSocket)
├── data/               # Runtime data (gitignored)
├── docs/               # Architecture docs, pattern library, steal reports
└── tests/
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **Claude Code** ([install guide](https://docs.anthropic.com/en/docs/claude-code))

Database is SQLite (built into Python). Docker is optional.

### Optional Components

| Component | With it | Without it |
|-----------|---------|------------|
| **Docker** | Background collection + dashboard + governance | Claude Code plugin layer works standalone |
| **Ollama** | Scrutiny uses local models, saves tokens | Falls back to Claude API |
| **Fish Speech** | Dashboard daily report plays as audio | Voice button hidden |

## Design References

Architecture patterns from 100+ open-source projects across 46 rounds. 217 patterns implemented. Full library: [docs/architecture/PATTERNS.md](docs/architecture/PATTERNS.md).

| Source | What we learned |
|--------|----------------|
| [autonomous-claude](https://github.com/matthewbergvinson/autonomous-claude) | Foundation for 24/7 autonomous operation |
| [edict](https://github.com/cft0808/edict) / [danghuangshang](https://github.com/wanikua/danghuangshang) | Multi-tier governance model |
| [soul.md](https://github.com/aaronjmars/soul.md) | Identity persistence framework |
| [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist) | Manifest-driven component auto-discovery |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | Context compression + stuck detection |
| [career-ops](https://github.com/santifer/career-ops) | Data contracts, adaptive pipelines |
| [Agent-S](https://github.com/simular-ai/Agent-S) / [UI-TARS](https://github.com/bytedance/UI-TARS) | GUI desktop automation |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | Voice system (TTS + emotion tags) |
