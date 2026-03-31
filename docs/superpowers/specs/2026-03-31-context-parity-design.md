# Context Parity: Sub-Agent ≈ Main Process

**Date**: 2026-03-31
**Status**: Draft
**Goal**: Redesign ContextEngine + Executor so Governor sub-agents achieve parity with the main Claude process in context access, tool availability, and reasoning depth.

## Problem

Governor sub-agents operate with ~2000 tokens of injected context and no access to conversation history, session state, or on-demand file retrieval. This causes structural failures on tasks requiring:

- **Retrieval**: Agent can't search codebases (ret-01: 2/10 — answered with fabricated error message)
- **Memory**: Agent loses details from long context (mem-36: 0/10 — hallucinated function name and path)
- **Reasoning**: Insufficient context leads to wrong logical conclusions (rea-41: 0/10 — chose B, correct D)

Evidence: Clawvard practice scored 95% on pure-knowledge dimensions but 45-60% on context-dependent ones. The gap is not capability — it's architecture.

## Design Principles

1. **Progressive Disclosure** — Context revealed in layers, not dumped upfront. Agent discovers what it needs, like the main process does (Read → Grep → search).
2. **Agent-Initiated Pull** — Shift from "pipeline injects context into prompt" to "agent pulls context from DB on demand". The agent decides what's relevant.
3. **Per-Task Pricing** — Different task types get different context budgets. Exam practice can burn tokens; daily patrol uses minimal context.
4. **DB as Shared State** — All context lives in `context_store` table. Main process writes, sub-agents read. Single source of truth.

## Architecture

```
Main Process (Claude Code)
    │
    ├── writes context to DB ──→ context_store table
    │     ├── Layer 0: briefing (identity, task, context catalog)
    │     ├── Layer 1: session state (recent conversation, git diff, chain outputs)
    │     ├── Layer 2: deep context (file contents, memory entries, conversation fragments)
    │     └── Layer 3: full archive (complete transcript, embedding search, dept history)
    │
    ├── dispatch.py ──→ Governor ──→ Executor
    │                                    │
    │                                    ├── Injects Layer 0 into prompt (always)
    │                                    ├── Makes ctx_read tool available
    │                                    └── Sets context_budget per task tier
    │
    └── Sub-Agent (Agent SDK)
          │
          ├── Reads Layer 0 from prompt (knows what's available)
          ├── Calls ctx_read("session") → gets Layer 1
          ├── Calls ctx_read("file:src/main.py") → gets Layer 2
          ├── Calls ctx_read("conversation:full") → gets Layer 3
          └── Agent decides what to pull based on task needs
```

## Component Design

### 1. Context Store (DB)

New table in `events.db`:

```sql
CREATE TABLE context_store (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    layer       INTEGER NOT NULL CHECK (layer BETWEEN 0 AND 3),
    key         TEXT NOT NULL,
    content     TEXT NOT NULL,
    token_est   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    UNIQUE(session_id, key)
);

CREATE INDEX idx_context_session_layer ON context_store(session_id, layer);
CREATE INDEX idx_context_key ON context_store(key);
```

**Key naming convention**:
- `identity:briefing` — one-line identity
- `identity:voice` — voice calibration params
- `session:state` — current session key-value state (JSON)
- `session:conversation_summary` — recent N turns summarized
- `session:git_diff` — current uncommitted changes
- `conversation:<topic>` — embedding-retrieved conversation fragments
- `file:<relative_path>` — file content snapshot
- `memory:<category>` — structured memory entries
- `chain:<task_id>` — output from a predecessor task
- `codebase:<query>` — embedding search results from codebase
- `history:<dept>` — recent task history for department

### 2. Context Writer (Main Process Side)

A `ContextWriter` class that the main process (or dispatch.py) calls before dispatching a task. Responsible for populating context_store with everything the sub-agent might need.

```python
class ContextWriter:
    """Writes context layers to DB before task dispatch."""

    def __init__(self, db: EventsDB, session_id: str):
        self.db = db
        self.session_id = session_id

    def write_layer0(self, task: dict, dept_key: str):
        """Always written. Minimal identity + task + context catalog."""
        # Identity briefing
        self.upsert("identity:briefing", _load_identity_briefing(dept_key))
        # Context catalog — tells agent what's available
        catalog = self._build_catalog()
        self.upsert("catalog", catalog)

    def write_layer1(self, conversation_summary: str = "",
                     git_diff: str = "", chain_outputs: dict = None):
        """Session state. Written by dispatch pipeline."""
        if conversation_summary:
            self.upsert("session:conversation_summary", conversation_summary)
        if git_diff:
            self.upsert("session:git_diff", git_diff)
        for task_id, output in (chain_outputs or {}).items():
            self.upsert(f"chain:{task_id}", output)

    def write_layer2_file(self, path: str, content: str):
        """On-demand file content. Written when dispatch knows relevant files."""
        self.upsert(f"file:{path}", content)

    def write_layer2_memory(self, category: str, content: str):
        self.upsert(f"memory:{category}", content)

    def write_layer3_conversation(self, transcript: str):
        """Full conversation transcript. Expensive — only written for heavy tasks."""
        self.upsert("conversation:full", transcript)

    def upsert(self, key: str, content: str):
        layer = _key_to_layer(key)
        token_est = max(1, len(content) // 4)
        self.db.upsert_context(self.session_id, layer, key, content, token_est)

    def _build_catalog(self) -> str:
        """List all available context keys for this session."""
        rows = self.db.list_context_keys(self.session_id)
        lines = ["Available context (use ctx_read to access):"]
        for layer, key, tokens in rows:
            lines.append(f"  L{layer} | {key} (~{tokens} tokens)")
        return "\n".join(lines)
```

### 3. ctx_read Tool (Sub-Agent Side)

A CLI script that sub-agents call via bash to read from context_store.

```bash
# Read specific key
python scripts/ctx_read.py --session <session_id> --key "session:conversation_summary"

# List available keys for a layer
python scripts/ctx_read.py --session <session_id> --list --layer 1

# Read all Layer 1 context
python scripts/ctx_read.py --session <session_id> --layer 1

# Search conversation by topic (embedding similarity)
python scripts/ctx_read.py --session <session_id> --search "Clawvard practice hash chain"
```

The script reads from `context_store` and prints to stdout. The sub-agent captures it as bash output.

**Budget enforcement**: ctx_read tracks cumulative tokens read per session. When budget is exhausted, it returns a warning instead of content:
```
[BUDGET] Context budget exhausted (12000/12000 tokens used).
Remaining keys available but blocked by budget.
```

### 4. Task Tier System (Per-Task Pricing)

Three tiers that control context budget, model, and max turns:

| Tier | Context Budget | Model | Max Turns | Use Case |
|------|---------------|-------|-----------|----------|
| **light** | 4K tokens | haiku | 10 | Daily patrol, status checks, simple lookups |
| **standard** | 24K tokens | sonnet | 25 | Code tasks, bug fixes, feature work |
| **heavy** | 128K tokens | opus | 50 | Exams, complex reasoning, multi-file refactors |

Tier assignment:
- Explicit: `dispatch.py --tier heavy` or `spec.tier = "heavy"`
- Auto-classified by `classify_task_tier(action, spec)`:
  - Keywords: "exam", "practice", "clawvard", "analyze" → heavy
  - Keywords: "check", "status", "patrol" → light
  - Default → standard
- Blueprint override: `blueprint.yaml` can set `tier: heavy` per department

```python
@dataclass
class TaskTier:
    name: str
    context_budget: int    # max tokens for ctx_read
    model: str             # claude model
    max_turns: int
    prompt_budget: int     # max tokens for initial prompt injection

TIERS = {
    "light":    TaskTier("light",    4000,   "haiku",  10, 1000),
    "standard": TaskTier("standard", 24000,  "sonnet", 25, 4000),
    "heavy":    TaskTier("heavy",    128000, "opus",   50, 16000),
}
```

### 5. Executor Changes

Changes to `executor.py` and `executor_prompt.py`:

**executor_prompt.py** — `build_execution_prompt()`:
- Layer 0 always injected into prompt (identity briefing + context catalog + task description)
- Remove hardcoded context budget; use `tier.prompt_budget` instead
- Inject `ctx_read` usage instructions into system prompt:

```
## Context Access
You have access to additional context via the ctx_read tool.
Run: python scripts/ctx_read.py --session {session_id} --key <key>

{context_catalog}

Read what you need. Don't read everything — pull context relevant to your task.
Start with Layer 1 (session state) if you need background.
```

**executor.py** — `execute_task()`:
- Before execution: call `ContextWriter.write_layer0()` and `write_layer1()`
- Pass `session_id` to prompt builder
- Tier-aware: resolve tier → set model, max_turns, context_budget
- `ctx_read` added to `allowed_tools` automatically (it's a bash script, not a blocked tool)

**dispatch.py**:
- New `--tier` flag: `--tier light|standard|heavy`
- `ContextWriter` called before dispatch to pre-populate context_store
- Conversation summary injected from caller (main process passes it)

### 6. ContextEngine Migration

Current ContextEngine (Provider/Processor pipeline) role changes:

**Before**: Assemble context → inject into prompt (pre-execution)
**After**: Assemble context → write to context_store (pre-dispatch)

The existing Providers become Writers:
- `SystemPromptProvider` → writes `identity:briefing` + `identity:voice`
- `GuidelinesProvider` → writes `memory:guidelines`
- `MemoryProvider` → writes `memory:*` entries
- `HistoryProvider` → writes `history:<dept>`
- `CodeRetrievalProvider` → writes `codebase:<query>` on demand
- `TwoStageRAGProvider` → backs the `--search` mode of ctx_read

The Processors (PriorityProcessor, TruncateProcessor) are replaced by:
- ctx_read's budget tracking (per-read truncation)
- Task tier system (global budget)

### 7. Conversation History Pipeline

How conversation context flows from main process to sub-agent:

```
Main Process conversation
    │
    ├── on dispatch: summarize recent N turns → write to session:conversation_summary (L1)
    ├── on dispatch: extract topic-relevant fragments → write to conversation:<topic> (L2)
    ├── for heavy tier: dump full transcript → write to conversation:full (L3)
    │
Sub-Agent
    ├── reads session:conversation_summary (always, via L1)
    ├── if needs more: ctx_read("conversation:clawvard") → topic fragments
    └── if still needs more: ctx_read("conversation:full") → full transcript
```

**Conversation summarizer**: A lightweight function that takes the last N messages and produces a ~500 token summary. Runs at dispatch time. For heavy tasks, also stores the full transcript.

```python
def summarize_conversation(messages: list[dict], max_tokens: int = 500) -> str:
    """Summarize recent conversation for sub-agent context injection."""
    # Take last 10 messages, extract key decisions and context
    recent = messages[-10:]
    parts = []
    for msg in recent:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:200]
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)[-max_tokens * 4:]  # rough char limit
```

For production, this should use an LLM call (haiku-tier) to produce a proper summary. But the naive version works as v0.

### 8. Chain Context (Task-to-Task State Passing)

Solves the Clawvard hash chain problem directly:

- When a task completes, its full output is written to `chain:<task_id>` in context_store
- The next task in a chain can read `chain:<prev_task_id>` to get the predecessor's output
- `dispatch.py` accepts `--chain-from <task_id>` to explicitly link tasks

```python
# In executor.py, after task completion:
if output and session_id:
    writer = ContextWriter(db, session_id)
    writer.upsert(f"chain:{task_id}", output)
```

The Clawvard runner no longer needs to parse nextBatch from compressed output — it just tells the next dispatch to read `chain:<prev_task_id>`.

## Data Flow Example: Clawvard Practice

```
1. Main process starts practice session
   → writes to context_store:
     - identity:briefing (Orchestrator identity)
     - session:state (practiceId, hash, taskOrder)
     - session:conversation_summary ("User requested Clawvard practice, 8 dimensions")

2. Dispatch batch 1 (understanding)
   → Executor injects Layer 0: identity + catalog + task description
   → Agent starts, reads catalog, sees session:state available
   → Agent calls ctx_read("session:state") → gets practiceId, hash, taskOrder
   → Agent answers questions, submits to API
   → Agent outputs full API response (scores + nextBatch)

3. Executor stores output
   → chain:382 = full API response (including nextBatch JSON)

4. Dispatch batch 2 (reflection)
   → dispatch.py --chain-from 382
   → Executor injects Layer 0 + catalog includes chain:382
   → Agent calls ctx_read("chain:382") → gets previous response with hash + nextBatch
   → Agent has the questions, answers them, submits
   → Repeat until practiceComplete
```

No more lost nextBatch. No more broken hash chains. No more JSON parsing hacks.

## Migration Plan

### Phase 1: Foundation (context_store + ctx_read)
- Add `context_store` table to EventsDB
- Implement `ContextWriter` class
- Implement `ctx_read.py` CLI script
- Add session_id to task dispatch flow

### Phase 2: Executor Integration
- Modify `build_execution_prompt()` to inject Layer 0 + ctx_read instructions
- Modify `execute_task()` to call ContextWriter before execution
- Add chain context auto-writing after task completion
- Add `--tier` flag to dispatch.py

### Phase 3: Task Tier System
- Implement `classify_task_tier()` auto-classification
- Implement ctx_read budget tracking
- Wire tier → model/turns/budget in executor

### Phase 4: Conversation Pipeline
- Implement conversation summarizer
- Wire main process → context_store conversation writes
- Add `--search` embedding mode to ctx_read

### Phase 5: ContextEngine Migration
- Convert existing Providers to Writers
- Deprecate prompt-injection path
- Remove old TruncateProcessor / budget logic

## Success Criteria

- Clawvard practice scores ≥90% across ALL 8 dimensions (currently 79%)
- Specifically: retrieval ≥80%, reasoning ≥80%, memory ≥80%
- No information loss between chained tasks (hash chain intact)
- Heavy-tier tasks get full context access without artificial truncation
- Light-tier tasks cost <$0.05 per execution

## Open Questions

1. **Session ID lifecycle**: When does a session start/end? Per conversation? Per dispatch batch?
   → Proposal: per conversation. Main process generates UUID at start, passes to all dispatches.

2. **Context eviction**: When to clean up expired context?
   → Proposal: on session end + daily cron. Layer 3 entries expire after 1 hour.

3. **Embedding backend for search**: Use existing TwoStageRAG infrastructure or new?
   → Proposal: reuse TwoStageRAGProvider's embedding pipeline, just change output target from prompt to DB.
