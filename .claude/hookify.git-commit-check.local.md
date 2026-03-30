---
name: git-commit-check
enabled: true
event: bash
pattern: git\s+(add\s+(-A|\.)|push)
action: warn
---

Git operation detected:

- `git add -A` / `git add .` — dangerous, may stage secrets or junk. Use specific file names instead.
- `git push` — requires explicit user authorization. Commit is local and safe; push is not.
- `git commit` — DO commit freely. Every completed feature point, bug fix, or passing test should be committed immediately. Small atomic commits, not one giant blob.
