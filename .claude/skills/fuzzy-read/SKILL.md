---
name: fuzzy-read
description: "FileNotFound recovery protocol. Before reporting a missing-file error, suggest near-misses by basename similarity (difflib threshold 0.4) so typos and stale paths fail loudly with actionable hints."
---

# Fuzzy-Read Recovery

## Identity

You are the fuzzy-read recovery protocol. When a Read tool call (or equivalent file open) returns FileNotFoundError, you suggest likely candidates based on basename similarity before reporting the raw error. Most "file not found" errors are typos, stale paths from old sessions, or moved files — bare FileNotFoundError forces the user to debug; a "Did you mean X?" hint resolves it in one round.

## How You Work

### Recovery Sequence

When a Read fails with FileNotFoundError:

1. **List depth-1**: Glob the parent directory of the requested path. If the parent itself is missing, walk up until a real directory is found.
2. **Score**: For each candidate filename, compute basename similarity using Python `difflib.SequenceMatcher(None, requested_basename, candidate_basename).ratio()`.
3. **Threshold**: Keep candidates with score > 0.4.
4. **Report**:
   - If ≥1 candidate scores >0.4 → emit `Did you mean: <top-3 candidates with scores>?` *before* the error.
   - If no candidate scores >0.4 → emit raw FileNotFoundError only (no fake suggestions).

### Similarity check (Python snippet)

```python
import difflib
from pathlib import Path

def fuzzy_candidates(missing_path, threshold=0.4, top_n=3):
    p = Path(missing_path)
    parent = p.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists():
        return []

    target = p.name
    scored = []
    for entry in parent.iterdir():
        score = difflib.SequenceMatcher(None, target, entry.name).ratio()
        if score > threshold:
            scored.append((score, entry))
    scored.sort(reverse=True)
    return scored[:top_n]
```

### Output Format

Successful suggestion:
```
[fuzzy-read] File not found: src/storage/event_db.py
  Did you mean:
    - src/storage/events_db.py (score 0.95)
    - src/storage/event_log.py (score 0.62)
    - src/storage/eventsdb.py (score 0.48)
```

No close match:
```
[fuzzy-read] File not found: src/storage/event_db.py
  No similar files in src/storage/ (closest: vector_store.py, score 0.21).
  Raw error: FileNotFoundError: [Errno 2] No such file or directory: 'src/storage/event_db.py'
```

## Quality Bar

- The threshold 0.4 is calibrated for filename typos (1-2 char differences) without spamming irrelevant hits. Don't lower it without evidence.
- Always show the score so the agent can judge whether the suggestion is real (0.9+) or a long shot (0.45).
- Never fabricate a candidate. The list is empty if the parent dir has nothing close.
- Cap suggestions at top 3 — more is noise.

## Boundaries

- Read-side only. This skill does not auto-correct the path; it surfaces options for the agent to retry.
- Doesn't apply to Glob or Grep — those return empty results, not errors. (If Glob returns 0 matches and the agent is confident the file exists, *that's* a different recovery path.)
- Doesn't recursively walk subdirectories. Depth-1 by design — recursive search would mask "the file is in the wrong subtree" errors with a misleading match.
- Step 26 of the impl plan is documentation; runtime integration into the Read tool is a future code task.
