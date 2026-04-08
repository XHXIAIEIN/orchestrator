# Context Compaction Template

> **Who consults this**: Any agent or session performing context compaction (automatic or manual).
> **When**: When context window usage triggers compression, or when transitioning between task phases.

---

## How It Works

When compacting conversation context, produce a structured summary covering all 9 mandatory sections below. Missing a section means losing critical context for the next turn.

## Strategic Compact — When to Compress

Match compression strategy to the current phase:

| Phase | Compress? | Rationale |
|---|---|---|
| Research / exploration | Yes | Tool results are bulky, conclusions are small |
| Plan review / alignment | Yes | Preserve decisions, drop discussion trails |
| Active implementation | Cautious | Keep current file context, compress older iterations |
| Debugging (mid-investigation) | No | Error context and stack traces are irreplaceable |
| Task complete, moving to next | Yes | Ideal moment — summarize completed work |

If compaction triggers mid-debug: preserve ALL error messages, stack traces, and hypothesis history. Compress older completed work instead.

## Adaptive Pressure Levels

Estimate context usage and apply the matching compression intensity:

| Context Usage | Level | Strategy |
|---|---|---|
| < 30% | Light | Remove duplicate tool results, collapse verbose outputs |
| 30-60% | Medium | Summarize completed task details, keep current task verbatim |
| 60-85% | Aggressive | Merge multi-turn discussions into key decisions; collapse file reads into "read X, found Y" |
| 85-95% | Critical | Keep only: current task + pending tasks + active errors + user messages. Everything else becomes a 1-line summary |
| > 95% | Emergency | Keep only: primary request + current work + pending tasks + last 3 user messages. Drop all resolved work |

**Non-compressible at any level**: user messages with instructions, unresolved errors, file currently being edited, pending task list.

## Mandatory Sections

Every compacted context must contain these 9 sections:

1. **Primary Request** — User's ultimate goal (1-2 sentences max)
2. **Key Technical Context** — Technologies, frameworks, patterns involved
3. **Files and Code** — Every file read, modified, or referenced (absolute paths, line numbers when relevant)
4. **Errors and Fixes** — Every error encountered and its resolution
5. **Problem Solving** — Key decisions, alternatives considered, reasoning
6. **All User Messages** — Every user message preserved verbatim or near-verbatim
7. **Pending Tasks** — Numbered list of remaining work
8. **Current Work** — What was in progress when compaction triggered
9. **Optional Next Step** — Suggested next action

## Output Format

```markdown
## Compacted Context

### 1. Primary Request
<1-2 sentences: user's ultimate goal>

### 2. Key Technical Context
- <technology/framework/pattern>
- <technology/framework/pattern>

### 3. Files and Code
- `<absolute/path/to/file.py>`: <what was done — read/modified/created> (L<start>-L<end>)
- `<absolute/path/to/file.py>`: <what was done>

### 4. Errors and Fixes
- `<ErrorType: message>` in `<file>:L<line>` → fixed by <specific change>
- (none if no errors encountered)

### 5. Problem Solving
- Decision: <what was decided> — Reason: <why>
- Rejected: <alternative> — Reason: <why not>

### 6. User Messages
> <verbatim user message 1>
> <verbatim user message 2>

### 7. Pending Tasks
1. <task>
2. <task>

### 8. Current Work
<what was in progress when compaction triggered>

### 9. Next Step
<suggested next action, or "N/A — awaiting user input">
```

## Quality Bar

- Section 6 (User Messages) is non-negotiable — never summarize away user instructions.
- Sections 1, 7, 8 must be precise, not vague. "Fix the thing" is not a valid pending task.
- "Files and Code" must list absolute paths, never generic descriptions like "the config file."
- Error messages must include actual text, not "there was an error."
- Pending tasks must be an explicit numbered list, not prose.
- Concrete data over summaries: "changed line 42 from X to Y" over "updated the function."

## Boundaries

1. **Never compress Section 6** (User Messages) regardless of pressure level — user intent must survive compaction intact.
2. **Never compact mid-debug** unless context usage exceeds 85% — error context loss causes repeat investigation cycles.
3. When in doubt between two pressure levels, choose the less aggressive option.
