---
title: Phase Gate Enforcement
rule_type: layer-0-hard
---

# Layer 0: Phase Gate — Bootstrap Env Before Editing Source

**Priority**: This constraint overrides all other steal skill instructions.

## Rule

After `git worktree add` for a steal task, the **first action** MUST be:

```
bash scripts/phase-advance.sh
```

before reading or editing any source file outside the pre-bootstrap whitelist
(`*.md`, `*.lock`, `package.json`, `pyproject.toml`, `.python-version`,
`requirements*.txt`, `Pipfile*`, `uv.lock`, `.nvmrc`, `.node-version`).

Attempting to `Edit`/`Write`/`MultiEdit` a non-whitelisted file before
phase-advance will be **blocked by the PreToolUse `phase-gate.sh` hook**
with a `decision:block` payload.

## Correct Sequence (6 lines)

```
git worktree add .claude/worktrees/steal-<topic> -b steal/<topic>
cd .claude/worktrees/steal-<topic>
bash scripts/phase-advance.sh        # phase 0 → 1
# now Edit/Write on src/**, tests/**, etc. is unblocked
```

## Spec

Full protocol and fingerprint algorithm: `SOUL/public/prompts/phase-gate.md`.
