# Orchestrator

Every time you start a new Claude Code session, it's a stranger. It doesn't know what you were working on yesterday, what keeps breaking, or that you've been pushing commits at 3am for the past week.

Orchestrator fixes that.

It runs 24/7 on your machine — collecting activity from Git, Chrome, VS Code, and more, analyzing behavioral patterns, and dispatching tasks to specialized agent departments that actually do the work. When you come back, it already knows what happened while you were gone.

**What it does:**
- **Collects** — 11 data collectors (Git, browser, editor, Steam, music...) that only grab what exists on your machine
- **Analyzes** — behavioral pattern detection, daily insight reports, activity profiling
- **Governs** — six agent departments with isolated permissions, pre-flight checks, and a review layer before execution
- **Remembers** — SOUL identity framework that carries personality and context across sessions
- **Communicates** — Telegram, WeChat, and desktop notifications for remote control and approval

## Quick Start

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

### Without Docker

```bash
# Terminal 1: scheduler
pip install -r requirements.txt
python -m src.scheduler

# Terminal 2: dashboard
cd dashboard && npm install && node server.js
```

## Architecture

```
Collectors (11)  →  EventsDB  →  Analysis  →  Governance
                                                  ↓
                                            Decision Layer
                                                  ↓
                                            Review Layer
                                                  ↓
                                          Execution (6 depts, parallel)
                                                  ↓
                                             Dashboard
```

Orchestrator uses a three-tier governance model for task dispatch:

| Layer | Component | Role |
|-------|-----------|------|
| Decision | Governor | Extracts tasks from insights, selects cognitive mode, assigns departments |
| Review | Scrutiny | Quick feasibility check — blast radius, reversal risk, confidence scoring |
| Execution | Six Departments | Parallel task execution, isolated by project, constrained by policies |

Each department is a specialized agent with its own permissions and model:

| Department | Role | Model |
|------------|------|-------|
| Engineering | Code: write, fix, refactor | Sonnet |
| Operations | System ops: collector fixes, DB, performance | Sonnet |
| Protocol | Attention audit: forgotten TODOs, unclosed issues | Haiku |
| Security | Defense: secret leaks, permissions, dependency audit | Haiku |
| Quality | Acceptance: code review, testing, logic errors | Sonnet |
| Personnel | Performance: collector health, success rates, trends | Haiku |

> The governance model is inspired by the Tang Dynasty's Three Departments and Six Ministries (三省六部) system. See [docs/architecture/README.md](docs/architecture/README.md) for the cultural context and design rationale.

### How Tasks Flow

```
Create → Classify → Preflight (policy check) → Review → Execute
```

Governor automatically selects a cognitive mode based on task complexity:

| Mode | When | Approach |
|------|------|----------|
| Direct | Fix a typo, tweak a param | Execute immediately |
| ReAct | Fix a bug, add a feature | Think → Act → Observe → Loop |
| Hypothesis | "Why doesn't X work?" | Hypothesize → Verify → Confirm/Refute |
| Designer | Refactor, new subsystem | Design first → Review → Then implement |

### Department Configuration

Each department is defined by three files:

| File | Read by | Controls |
|------|---------|----------|
| `manifest.yaml` | Registry (startup scan) | Identity, routing tags, policies, execution config |
| `SKILL.md` | Agent (LLM) | Behavioral guidelines, red lines, completion criteria |
| `blueprint.yaml` | Governor (code) | Permissions, preflight rules, blast radius limits |

Adding a new department: create a directory under `departments/` with a `manifest.yaml`. Zero code changes.

<details>
<summary>Policy example (manifest.yaml)</summary>

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

blast_radius:
  max_files_per_run: 15
  forbidden_paths: [".env", "*.key", "SOUL/private/identity.md"]
```

</details>

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

## Dashboard

Three pages, all real-time via WebSocket:

- **Dashboard** `/` — daily report, department status, insight analysis, attention debts, activity heatmap
- **Pipeline** `/pipeline` — data flow visualization, collector → analysis → governance full-chain animation, system logs
- **Agents** `/agents` — agent observability: event stream, tool calls, thinking process, parallel scenario control

## Channel Layer

Multi-platform message bus for remote control:

| Channel | Outbound | Inbound | Approval |
|---------|----------|---------|----------|
| Telegram | Yes | Yes (polling) | Inline keyboard |
| WeChat | Yes | Yes | Text commands |
| WeCom | Yes (webhook) | — | — |

Commands: `/status`, `/tasks`, `/run <scenario>`, `/approve <id>`, `/deny <id>`, `/pending`, `/yolo`, `/noyolo`

All channels are optional — the system works fully without any of them configured.

### Approval Gateway

Human approval for authority escalation. Only fires when a task requires `APPROVE`-level authority (normal departments cap at `MUTATE`, so this rarely triggers).

```
Task needs elevated authority
  → ApprovalGateway.request_approval()
    ├─ Claw: Windows Toast notification
    ├─ Telegram: Inline keyboard
    └─ WeChat: Text command
  → First response wins (5min timeout = auto-deny)
```

`/yolo` disables all approval prompts. `/noyolo` re-enables them.

## SOUL (Identity Persistence)

AI personality framework. Each new session reads the compiled `boot.md` to restore identity, voice calibration, and relationship context. Not a perfect clone — but close enough to maintain continuity.

```
Short-term: claude --resume (same instance, full memory)
Long-term:  SOUL files (new instance, reconstructed identity)
```

See [SOUL/README.md](SOUL/README.md) for the full framework design, experience types, and prior art comparison.

## Claw (Desktop Daemon)

C# .NET 8 system tray daemon. No UI — just a WebSocket bridge to `ws://localhost:23714` with Windows Toast notifications for approval flow. Auto-reconnects on disconnect.

```bash
cd claw/Claw && dotnet run
```

## API

Interactive docs: http://localhost:23714/api-reference (Swagger UI)

OpenAPI spec: http://localhost:23714/openapi.json

```bash
# Global status
curl -s http://localhost:23714/api/brief

# Open attention debts
curl -s 'http://localhost:23714/api/debts?status=open'

# Agent live status
curl -s http://localhost:23714/api/agents/live

# Trigger parallel audit (Security + Quality + Protocol simultaneously)
curl -s -X POST http://localhost:23714/api/scenarios/full_audit/run \
  -H 'Content-Type: application/json' -d '{"project":"orchestrator"}'

# Task execution replay (full thinking chain + tool calls)
curl -s http://localhost:23714/api/agents/42/trace
```

### Integrating with Other Projects

Add to your other project's `CLAUDE.md`:

```markdown
## Orchestrator

Global status: `curl -s http://localhost:23714/api/brief`
Open debts: `curl -s http://localhost:23714/api/debts?status=open`
Agent live status: `curl -s http://localhost:23714/api/agents/live`
Full API: http://localhost:23714/api-reference
```

## Parallel Scheduling

Governor supports two dispatch modes:

| Method | Purpose |
|--------|---------|
| `run_batch()` | Auto batch: pick tasks from recommendations, deduplicate by department + project, run in parallel |
| `run_parallel_scenario()` | Manually trigger predefined scenarios |

Isolation: same department + same project runs serially. Same department + different projects can parallelize. Different departments always parallelize.

## Directory Structure

```
orchestrator/
├── src/
│   ├── core/           # Infrastructure: config, event bus, LLM routing, cost tracking
│   ├── governance/     # Three-tier governance: Governor, scrutiny, departments
│   ├── analysis/       # Daily reports, insights, profiling, burst detection
│   ├── collectors/     # Data collectors (Python + YAML-driven)
│   ├── channels/       # Telegram, WeChat, WeCom adapters
│   ├── storage/        # EventsDB (SQLite), VectorDB
│   ├── voice/          # TTS, voice selection
│   ├── scheduler.py    # Scheduler entry point
│   └── cli.py          # CLI entry point
├── claw/               # Desktop daemon (C# .NET 8, system tray + Toast)
├── dashboard/          # Frontend (Express + WebSocket)
│   └── public/         # Three pages: Dashboard / Pipeline / Agents
├── departments/        # Six departments (manifest.yaml + SKILL.md per dept)
├── SOUL/               # AI personality framework
├── data/               # Runtime data (gitignored)
├── docs/               # Architecture docs, pattern library
├── bin/                # Docker startup scripts
└── tests/
```

## Prerequisites

Three things:

- **Python 3.10+**
- **Node.js 18+**
- **Claude Code** ([install guide](https://docs.anthropic.com/en/docs/claude-code))

Database is SQLite (built into Python). Docker is optional.

### Optional Components

Not required. The system adapts automatically:

| Component | With it | Without it |
|-----------|---------|------------|
| **Docker** | One-click `docker compose up` | Manual `python + node` startup |
| **Ollama** | Scrutiny and debt scanning use local models, saves tokens | Falls back to Claude API |
| **Fish Speech** | Dashboard daily report plays as audio | Voice button hidden, everything else works |

## Design References

Architecture patterns researched from 100+ open-source projects across 44 rounds. 217 patterns total, 194 implemented. Full pattern library: [docs/architecture/PATTERNS.md](docs/architecture/PATTERNS.md).

Key influences:

| Source | What we learned |
|--------|----------------|
| [autonomous-claude](https://github.com/matthewbergvinson/autonomous-claude) | Foundation for 24/7 autonomous operation |
| [edict](https://github.com/cft0808/edict) / [danghuangshang](https://github.com/wanikua/danghuangshang) | Multi-tier governance model |
| [soul.md](https://github.com/aaronjmars/soul.md) | Identity persistence framework |
| [NVIDIA G-Assist](https://github.com/NVIDIA/g-assist) | Manifest-driven component auto-discovery |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | Context compression + stuck detection |
| [OpenClaw](https://github.com/openclaw/openclaw) | Channel layer design |
| [Agent-S](https://github.com/simular-ai/Agent-S) / [UI-TARS](https://github.com/bytedance/UI-TARS) | GUI desktop automation |
| [Fish Speech](https://github.com/fishaudio/fish-speech) | Voice system (TTS + emotion tags) |
