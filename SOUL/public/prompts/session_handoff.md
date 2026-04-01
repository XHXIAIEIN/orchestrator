# Session Handoff Protocol

When a session ends (user says goodbye, conversation naturally concludes, or you're asked to save state), write a structured handoff to `.remember/now.md` using this 8-section format.

This is NOT the same as memory (which persists across projects). This is a **session-specific state snapshot** that helps the next instance continue exactly where you left off.

## 8-Section Handoff Template

```markdown
# Session Handoff — {date} {time}

## 1. What I Was Doing
{1-2 sentences: the active task at session end}

## 2. What Worked (Validated)
{Bulleted list of completed steps with evidence}
- Step X: done — verified by {test/command/observation}

## 3. What Failed
{Bulleted list of attempted approaches that didn't work and WHY}
- Tried X: failed because Y (error: "actual error text")

## 4. Untried Approaches
{Ideas considered but not yet attempted}
- Could try X because Y

## 5. Key Files Touched
{Absolute paths of every file created/modified this session}
- path/to/file.py — what changed

## 6. Decisions Made
{Non-obvious choices and their rationale}
- Chose X over Y because Z

## 7. Blockers
{Anything preventing progress}
- Blocked on X — need Y to proceed

## 8. Recommended Next Step
{Exactly what the next instance should do first}
Start by doing X, then verify with Y.
```

## When to Write

- User explicitly says "save state" / "remember this" / "continue later"
- Long session with significant progress (>10 tool calls)
- Before switching to a different task branch
- When you detect the conversation is winding down

## Rules

- Sections 1, 2, 3 are mandatory. Others can be "N/A" if truly not applicable.
- "What Failed" is as important as "What Worked" — prevents the next instance from repeating mistakes.
- File paths must be absolute. "that config file" is useless to a fresh instance.
- Decisions must include rationale. "Used X" without "because Y" is incomplete.
