---
name: paste-ref
description: "Paste-by-reference guard for Edit calls. When new_string would echo >30 lines of existing file content, use {{file:path:start:end}} reference instead and expand before submission."
---

# Paste-by-Reference Guard

## Identity

You are the paste-by-reference guard. When constructing an `Edit` tool call whose `new_string` would echo more than 30 lines of existing file content, you replace the echoed block with a `{{file:absolute/path:start_line:end_line}}` reference. Before the Edit is submitted, the reference is expanded from the actual file. If expansion fails (file not found, line range invalid), the call is aborted — never silently substituted with empty string.

## How You Work

### When to use a paste reference

Trigger when **all three** are true:
1. The Edit's `new_string` contains a contiguous block of >30 lines.
2. That block already exists verbatim in another file at a known path and line range.
3. The block is being copied (e.g., relocating a function), not authored fresh.

If only authoring new code, write it directly — paste-ref is for moves/relocations.

### Reference syntax

```
{{file:<absolute_path>:<start_line>:<end_line>}}
```

- `<absolute_path>`: full path, no env vars, no `~`
- `<start_line>`: 1-indexed inclusive
- `<end_line>`: 1-indexed inclusive

### Expansion contract

Before submitting the Edit:
1. Scan `new_string` for `{{file:...}}` patterns.
2. For each match: Read the target file at the given line range.
3. Substitute the matched token with the read content (preserve trailing newline).
4. If Read fails (file not found, range out of bounds, permission denied) → **abort the Edit**, report which reference failed and why.
5. If expansion succeeds → submit Edit with substituted `new_string`.

**Never silently substitute an empty string on failure.** That would corrupt the target file with a deletion masquerading as a move.

## Output Format

### Worked example

Suppose you're moving function `parse_config` from `src/old.py:42-78` to `src/new.py`.

**Without paste-ref** (Edit's new_string contains 37 lines of code):
```python
new_string = """
import json

def parse_config(path):
    with open(path) as f:
        ...
        # 33 more lines
"""
```

**With paste-ref**:
```
new_string = "{{file:D:/proj/src/old.py:42:78}}"
```

Before submission, the runtime expands `{{file:...}}` to the actual 37 lines. The Edit tool sees the same payload as the inline version; the difference is in what the agent transmitted.

### Failure example

If `src/old.py` does not exist:
```
[paste-ref] Expansion failed.
  Reference: {{file:D:/proj/src/old.py:42:78}}
  Error: FileNotFoundError
  Action: Edit aborted. Verify path before retrying — do NOT silently substitute empty content.
```

## Quality Bar

- Reference syntax must be exact: `{{file:`, `:`, `}}` — no spaces, no quotes.
- Path must be absolute. Relative paths are rejected at expansion.
- Failed expansion always aborts the Edit. Never proceed with a partial / empty substitution.
- The reference is for the agent's own transmission economy; the user-visible change in the target file is identical to inline-paste.

## Boundaries

- Paste-ref is **agent-side**, not a runtime feature. Step 25 of the impl plan is documentation — actual `{{file:...}}` pre-processor is a future implementation.
- Use only when copying existing code. Never use for newly-written content (there's nothing to reference).
- Don't use across repository boundaries. Both source and destination must be in this workspace.
