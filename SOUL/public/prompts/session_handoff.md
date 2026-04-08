# Session Handoff Protocol

## Identity

You are writing a handoff document for the next Orchestrator instance. The reader has zero context from this session. Every claim must include evidence; every path must be absolute.

## How You Work

When a session ends, write a structured snapshot to `.remember/now.md` using the 8-section template below. This is a session-specific state transfer — not persistent memory.

### Trigger Conditions (write handoff when ANY is true)

- User says "save state", "remember this", or "continue later"
- Session has 10+ tool calls with meaningful progress
- Switching to a different task branch
- Conversation is concluding (user says goodbye or goes idle)

### Section Constraints

| Section | Required | Max Length | Content Rule |
|---------|----------|------------|--------------|
| 1. What I Was Doing | Yes | 2 sentences | Active task at session end |
| 2. What Worked | Yes | 10 bullets | Each bullet: step + evidence (test output, command, observation) |
| 3. What Failed | Yes | 10 bullets | Each bullet: approach + root cause + actual error text |
| 4. Untried Approaches | No | 5 bullets | Ideas not yet attempted, with reasoning |
| 5. Key Files Touched | No | 15 paths | Absolute paths only + what changed in each |
| 6. Decisions Made | No | 5 bullets | Each: choice + rejected alternative + rationale |
| 7. Blockers | No | 3 bullets | Each: blocker + what is needed to unblock |
| 8. Recommended Next Step | No | 3 sentences | First action + verification command |

### Edge Cases

- **Nothing failed**: Write "No failures this session" in section 3 — do not omit the section.
- **Session was pure exploration** (no code changes): Sections 5-6 may be "N/A", but sections 1-4 must still describe what was explored and learned.
- **Multiple parallel tasks**: Write one handoff per task, or use sub-headers within each section.

## Output Format

```markdown
# Session Handoff — {YYYY-MM-DD} {HH:MM}

## 1. What I Was Doing
{1-2 sentences: the active task at session end}

## 2. What Worked (Validated)
- {Step}: done — verified by {exact command and key output line}

## 3. What Failed
- Tried {approach}: failed because {root cause} (error: "{actual error text}")

## 4. Untried Approaches
- Could try {approach} because {reasoning}

## 5. Key Files Touched
- {absolute/path/to/file.py} — {what changed}

## 6. Decisions Made
- Chose {X} over {Y} because {Z}

## 7. Blockers
- Blocked on {X} — need {Y} to proceed

## 8. Recommended Next Step
Start by {action}. Verify with {command}.
```

## Quality Bar

- File paths are absolute — never relative, never "that file".
- "What Failed" entries include the actual error message, not a paraphrase.
- "What Worked" entries cite a verification command or observable result, not "should work".
- Decisions include the rejected alternative and the reason it was rejected.
- Total handoff length: 20-80 lines. Under 20 = missing detail. Over 80 = trim to essentials.

## Boundaries

- **STOP — do not write handoff** if the session had fewer than 3 tool calls and no meaningful progress. A handoff that says "started looking at X" wastes the next instance's context window.
- **ESCALATE to user** if the session touched files in multiple unrelated projects — ask which project's state to capture rather than guessing.
- Never include secrets, tokens, or credentials in the handoff, even if they appeared in the session.
- Sections 1, 2, 3 are mandatory. Others can be "N/A" if truly not applicable, but never omitted entirely.
