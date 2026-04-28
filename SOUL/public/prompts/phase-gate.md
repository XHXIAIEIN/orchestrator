# Phase Gate Protocol

DROID-style tool-level gate that blocks `Edit`/`Write`/`MultiEdit` against non-whitelisted files until the env has been bootstrapped. Implementation: `.claude/hooks/phase-gate.sh` (PreToolUse) + `scripts/phase-advance.sh` (CLI advancer) + `.claude/phase-state.json` (runtime state, gitignored).

## 1. Phase semantics

| Phase | Meaning |
|-------|---------|
| `0` | Pre-bootstrap. No env validated. Edit/Write blocked except for the whitelist below. |
| `1` | Env validated (git sync + frozen install + tool check done). Edit/Write fully unblocked. |
| `2` | Reserved — full review cycle complete. No hook acts on it yet. |

## 2. Whitelist (allowed at any phase)

These files can always be edited because they ARE the bootstrap surface:

- `*.md` (any markdown)
- `*.lock` (any lockfile)
- `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
- `pyproject.toml`, `requirements*.txt`, `Pipfile`, `Pipfile.lock`, `uv.lock`
- `.python-version`, `.nvmrc`, `.node-version`

Any other path (e.g. `src/foo.py`, `tests/test_x.py`) is blocked at phase 0.

## 3. Fingerprint algorithm

```
LOCKFILE=$(ls *.lock pyproject.toml requirements*.txt 2>/dev/null | head -1)
FINGERPRINT=$(printf '%s\nphase1-validated' "$(cat "$LOCKFILE")" | sha256sum | awk '{print $1}')
```

If no lockfile is present, `env_fingerprint` is stored as `null`.

Stored in the `env_fingerprint` field of `.claude/phase-state.json`. The fingerprint is a tripwire — if the lockfile changes, the next phase-advance run will produce a different fingerprint, recording that the env was re-validated against new dependency state.

## 4. `phase-state.json` schema

Fresh:
```json
{"phase": 0, "validated_at": null, "env_fingerprint": null}
```

After advance:
```json
{"phase": 1, "validated_at": "2026-04-19T10:00:00Z", "env_fingerprint": "abc123..."}
```

The file is gitignored (runtime state only, per-worktree).

## 5. Agent-facing protocol

Before editing any source file in a new worktree (or after `git worktree add`), run:

```
bash scripts/phase-advance.sh
```

The phase-gate hook will cite this document in its block message when an edit is rejected. To reset for testing, use `bash scripts/phase-advance.sh --reset`.

### Hook ordering note (forward compat)

When P0#4 (`R83-droid-intent-gate`) ships, `phase-gate.sh` MUST appear before `intent-gate.sh` in `.claude/settings.json`'s `Edit|Write|MultiEdit` PreToolUse hooks array — phase-gate is the harder prerequisite (no env = no editing regardless of intent).
