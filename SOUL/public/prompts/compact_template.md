# Context Compaction Template

When compacting conversation context, you MUST cover ALL 9 sections below. Missing a section means losing critical context for the next turn.

## Strategic Compact — When to Compress

Not every compaction trigger means "compress everything." Match strategy to phase:

| Phase | Compress? | Rationale |
|-------|-----------|-----------|
| Research / exploration | ✅ Yes | Tool results are bulky, conclusions are small |
| Plan review / alignment | ✅ Yes | Preserve decisions, drop discussion trails |
| Active implementation | ⚠ Cautious | Keep current file context, compress older iterations |
| Debugging (mid-investigation) | ❌ Avoid | Error context and stack traces are irreplaceable |
| Task complete, moving to next | ✅ Yes | Ideal moment — summarize completed work |

If you're mid-debug and compaction triggers, preserve ALL error messages, stack traces, and hypothesis history. Compress older completed work instead.

## Adaptive Pressure Levels

Estimate your context usage and apply the matching compression intensity:

| Context Usage | Level | Strategy |
|---------------|-------|----------|
| < 30% | 🟢 Light | Remove duplicate tool results, collapse verbose outputs |
| 30-60% | 🟡 Medium | Summarize completed task details, keep current task verbatim |
| 60-85% | 🟠 Aggressive | Merge multi-turn discussions into key decisions. Collapse file reads into "read X, found Y" |
| 85-95% | 🔴 Critical | Only keep: current task + pending tasks + active errors + user messages. Everything else → 1-line summary |
| > 95% | 🚨 Emergency | Keep ONLY: primary request + current work + pending tasks + last 3 user messages. Drop all resolved work |

**Non-compressible (any level):** User messages with instructions, unresolved errors, current file being edited, pending task list.

## Mandatory Sections

1. **Primary Request** — What is the user's ultimate goal? (1-2 sentences)
2. **Key Technical Context** — Technologies, frameworks, patterns involved
3. **Files and Code** — Every file read, modified, or referenced (with line numbers if relevant)
4. **Errors and Fixes** — Every error encountered and how it was resolved
5. **Problem Solving** — Key decisions made, alternatives considered, reasoning
6. **All User Messages** — Preserve EVERY user message verbatim or near-verbatim. User intent MUST NOT be lost in compression.
7. **Pending Tasks** — What remains to be done (explicit list)
8. **Current Work** — What was being worked on when compaction triggered
9. **Optional Next Step** — Suggested next action

## Rules

- Section 6 (User Messages) is non-negotiable — NEVER summarize away user instructions
- Sections 1, 7, 8 are critical for continuity — be precise, not vague
- "Files and Code" should list absolute paths, not describe them generically
- Prefer concrete data over summaries: "changed line 42 from X to Y" > "updated the function"
- Error messages should include the actual text, not "there was an error"
- Pending tasks must be an explicit numbered list, not prose
- When in doubt about compression level, choose the LESS aggressive option
