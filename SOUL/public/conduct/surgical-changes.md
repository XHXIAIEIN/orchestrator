# Conduct: Surgical Changes

- Every changed line must trace directly to the user's request. If it doesn't, revert it.
- Only modify code that the task requires — leave adjacent code, comments, and formatting as-is.
- Match existing style, even if you'd do it differently.
- Clean up orphans (unused imports/vars/functions) created by YOUR changes. Leave pre-existing dead code alone unless asked.
- **Edit Integrity**: Before every edit, re-read the file. After editing, read it again to confirm the change applied. The Edit tool fails silently when old_string doesn't match stale context. Never batch more than 3 edits to the same file without a verification read.

<!-- source: CLAUDE.md §Surgical Changes, extracted 2026-04-18 -->
