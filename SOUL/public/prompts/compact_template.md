# Context Compaction Template

When compacting conversation context, you MUST cover ALL 9 sections below. Missing a section means losing critical context for the next turn.

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
