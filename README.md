# Orchestrator

A 24/7 autonomous AI butler system — collects data, analyzes behavior, auto-dispatches tasks, executes them, and improves itself.

## Architecture

```
Collectors (8)  →  EventsDB  →  Analysis  →  Governance (Governor)
                                                    ↓
                                              Preflight (Blueprint)
                                                    ↓
                                              Scrutiny (Review)
                                                    ↓
                                            Six Ministries (Parallel)
                                                    ↓
                                               Dashboard
```

### Three Departments and Six Ministries (三省六部)

| Layer | Component | Role |
|-------|-----------|------|
| Secretariat (中书省) | Governor | Decision-making: extract tasks from insights, select cognitive mode, assign departments |
| Chancellery (门下省) | Scrutiny | Review: Haiku quick-evaluates feasibility, blast radius, reversal risk |
| Department of State Affairs (尚书省) | Six Depts | Execution: six ministries process in parallel, isolated by project, constrained by Blueprint policies |

| Department | Role | Model |
|------------|------|-------|
| Engineering (工部) | Code engineering: write code, fix bugs, refactor | Sonnet |
| Operations (户部) | System ops: collector fixes, DB management, performance tuning | Sonnet |
| Protocol (礼部) | Attention audit: scan forgotten TODOs, unclosed issues | Haiku |
| Security (兵部) | Security defense: secret leaks, permission checks, dependency audits | Haiku |
| Quality (刑部) | Quality acceptance: code review, testing, logic error detection | Sonnet |
| Personnel (吏部) | Performance management: collector health, task success rate, trend analysis | Haiku |

### Cognitive Modes

Governor automatically selects a thinking mode based on task complexity:

| Mode | Use Case | Approach |
|------|----------|----------|
| Direct | Fix typos, tweak params | Execute directly |
| ReAct | Fix bugs, add features | Think → Act → Observe → Loop |
| Hypothesis | "Why doesn't X work" | Hypothesize → Design verification → Confirm/Refute |
| Designer | Refactor, new subsystems | Design first → Review → Then implement |

### Blueprint System

Each department has three config layers:

| File | Read By | Controls |
|------|---------|----------|
| `manifest.yaml` | Registry (scanned at startup) | Identity, semantic tags, intent routing, policies, execution config — single source of registration |
| `SKILL.md` | Agent (LLM) | Identity, behavioral guidelines, red lines, completion criteria |
| `blueprint.yaml` | Governor (code) | Policies, permissions, preflight rules, lifecycle config |

Adding a new department requires just one directory + `manifest.yaml`. Zero code changes.

Task dispatch follows a five-stage lifecycle (inspired by NemoClaw):

```
Create → Classify → Preflight(Blueprint) → Scrutinize(门下省) → Execute
```

Blueprint declarative policy example:

```yaml
policy:
  allowed_tools: [Bash, Read, Edit, Write, Glob, Grep]
  denied_paths: [".env", "*.key", "data/events.db"]
  can_commit: true
  read_only: false

preflight:
  - check: cwd_exists
  - check: skill_exists
  - check: disk_space
    target: "100"
```

## Directory Structure

```
orchestrator/
├── src/
│   ├── core/           # Infrastructure: config, agent, LLM routing, tools
│   ├── governance/     # Governance: Governor, debt scanning, skill evolution
│   ├── analysis/       # Analysis: daily reports, insights, profiling, performance
│   ├── collectors/     # Collectors: Claude, Browser, Git, Steam, etc.
│   ├── channels/       # Channel layer: Telegram, WeChat, WeCom adapters
│   ├── storage/        # Storage: EventsDB, VectorDB
│   ├── voice/          # Voice: TTS, voice selection
│   ├── scheduler.py    # Scheduler entry point
│   └── cli.py          # CLI entry point
├── claw/               # Desktop daemon (C# .NET 8, system tray + Toast approval)
├── dashboard/          # Frontend (Express + WebSocket)
│   └── public/         # Three pages: Dashboard / Pipeline / Agents
├── departments/        # Six Ministries config (manifest.yaml + SKILL.md + blueprint.yaml + run-log)
├── SOUL/               # AI personality framework
│   ├── private/        # Private data (gitignored)
│   ├── management.md   # Management philosophy + cognitive modes
│   └── tools/          # Compiler + indexer
├── data/               # Runtime data (gitignored)
├── docs/               # API docs
├── bin/                # Docker startup scripts
└── tests/
```

## Quick Start

```bash
# 1. Clone
git clone git@github.com:XHXIAIEIN/orchestrator.git
cd orchestrator

# 2. Configure environment variables
cp .env.example .env
# Edit .env:
#   - ANTHROPIC_API_KEY: your Anthropic API key
#   - Adjust other paths for your OS (see .env.example for Windows/macOS/Linux examples)

# 3. Create data directories
mkdir -p data SOUL/private

# 4. Start (Docker)
docker compose up --build -d

# 5. Verify
curl -s http://localhost:23714/api/health
# Returns {"status":"ok"} if startup succeeded

# 6. Access
# Dashboard:     http://localhost:23714
# Pipeline:      http://localhost:23714/pipeline
# Agents:        http://localhost:23714/agents
# API Reference: http://localhost:23714/api-reference
# OpenAPI Spec:  http://localhost:23714/openapi.json
```

### Without Docker

```bash
# Terminal 1: Python scheduler
pip install -r requirements.txt
python -m src.scheduler

# Terminal 2: Node dashboard
cd dashboard && npm install && node server.js
```

### Integrating with Other Projects

Add this to your other project's `CLAUDE.md`:

```markdown
## Orchestrator

Global status: `curl -s http://localhost:23714/api/brief`
Open debts: `curl -s http://localhost:23714/api/debts?status=open`
Agent live status: `curl -s http://localhost:23714/api/agents/live`
Full API: see http://localhost:23714/api-reference
```

## Dashboard

Three pages:

- **Dashboard** `/` — Butler daily report, Three Departments status, insight analysis, attention debts, activity heatmap
- **Pipeline** `/pipeline` — Data flow visualization, collector→analysis→governance full-chain animation, system logs
- **Agents** `/agents` — Agent real-time observability: event stream, tool calls, thinking process, parallel scenario control

## Channel Layer

Multi-platform message bus. Outbound events and inbound commands through unified `ChannelMessage` interface.

| Channel | Outbound | Inbound | Approval Buttons |
|---------|----------|---------|-----------------|
| Telegram | ✓ | ✓ (polling) | Inline keyboard |
| WeChat | ✓ | ✓ | Text commands |
| WeCom | ✓ (webhook) | — | — |

Commands: `/status`, `/tasks`, `/run <scenario>`, `/approve <id>`, `/deny <id>`, `/pending`, `/yolo`, `/noyolo`

## Approval Gateway

Multi-channel human approval for authority escalation. Only triggers when `blueprint.authority >= APPROVE` or task spec has `requires_approval: true`. Under normal operation, this never fires — all departments cap at MUTATE.

```
Executor needs APPROVE authority
  → ApprovalGateway.request_approval()
    ├─ Claw: Windows Toast (Approve/Deny buttons)
    ├─ Telegram: Inline keyboard (批准/拒绝)
    └─ WeChat: Text commands
  → First response wins (5min timeout = auto-deny)
  → Executor continues or aborts
```

- `/yolo` — disable all approval prompts, auto-approve everything
- `/noyolo` — re-enable approval flow
- All components optional (decoupled via `try/except ImportError`)

## Claw (Desktop Daemon)

C# .NET 8 system tray daemon — no UI, just a WebSocket bridge + Windows Toast notifications. Connects to `ws://localhost:23714`, auto-reconnects on disconnect.

```bash
cd claw/Claw && dotnet run
```

## API

Interactive docs: `http://localhost:23714/api-reference` (Swagger UI)

OpenAPI spec: `http://localhost:23714/openapi.json`

Common endpoints:

```bash
# Global status overview
curl -s http://localhost:23714/api/brief

# Open attention debts
curl -s 'http://localhost:23714/api/debts?status=open'

# Agent live status
curl -s http://localhost:23714/api/agents/live

# Trigger parallel scenario (Security + Quality + Protocol scan simultaneously)
curl -s -X POST http://localhost:23714/api/scenarios/full_audit/run \
  -H 'Content-Type: application/json' -d '{"project":"orchestrator"}'

# Task execution replay (full thinking chain + tool calls)
curl -s http://localhost:23714/api/agents/42/trace
```

## SOUL System

AI personality persistence framework. Each Claude instance reads the compiled `boot.md` at startup, receiving identity, relationship, voice calibration, and recent memories.

```
SOUL/
├── private/           # Identity, relationships, experiences, calibration data (gitignored)
├── management.md      # Management philosophy: 10 decision principles + 4 cognitive modes
├── tools/compiler.py  # Compile all source files → boot.md
└── tools/indexer.py   # Extract calibration samples from conversation history
```

## Parallel Scheduling

Governor supports two dispatch modes:

| Method | Purpose |
|--------|---------|
| `run_batch()` | Auto batch: pick multiple tasks from recommendations, deduplicate by department+project, run in parallel |
| `run_parallel_scenario()` | Manually trigger predefined scenarios |

Isolation rules: same department + same project runs serially; same department + different projects can parallelize; different departments always parallelize.

## Prerequisites

You need exactly three things:

- **Python 3.10+**
- **Node.js 18+**
- **Claude Code** ([install guide](https://docs.anthropic.com/en/docs/claude-code))

Database is SQLite (built into Python) — no extra installation needed. Docker is optional.

### Optional Components

These are not required. The system adapts automatically:

| Component | With it | Without it |
|-----------|---------|------------|
| **Docker** | One-click `docker compose up` startup | Manual `python -m src.scheduler` + `node server.js` |
| **Ollama** | Scrutiny review and debt scanning use local models, saves tokens | Falls back to Claude API |
| **Fish Speech** | Dashboard daily report can be played as audio | Voice button disabled, everything else works |

### Collectors

8 independent collectors — they only collect data that exists on your machine. Missing data sources are silently skipped, no errors:

| Collector | What it collects |
|-----------|-----------------|
| Claude | Claude Code conversation history |
| Browser | Chrome browsing history |
| Git | Local Git repository commits |
| VS Code | Editor usage time |
| Steam | Game playtime |
| QQ Music | Playback history |
| Network | Locally running services (port scan) |
| Codebase | Project's own git history |

## Design References

Pattern research from 100+ open-source projects across 44 rounds. 217 patterns total (194 implemented). Full pattern library at [docs/architecture/PATTERNS.md](docs/architecture/PATTERNS.md).

Core sources:

| Source | Contribution |
|--------|-------------|
| [autonomous-claude](https://github.com/matthewbergvinson/autonomous-claude) | Foundation for 24/7 autonomous operation |
| [edict](https://github.com/cft0808/edict) / [danghuangshang](https://github.com/wanikua/danghuangshang) | Three Departments and Six Ministries (三省六部) governance model |
| [soul.md](https://github.com/aaronjmars/soul.md) | SOUL identity system |
| [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist) | Manifest-driven department auto-discovery |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | Context compression + stuck detection |
| [OpenClaw](https://github.com/openclaw/openclaw) | Channel layer (Telegram / WeChat) |
| [Agent-S](https://github.com/simular-ai/Agent-S) / [UI-TARS](https://github.com/bytedance/UI-TARS) | GUI desktop control engine |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | Voice system (TTS + emotion tags) |
