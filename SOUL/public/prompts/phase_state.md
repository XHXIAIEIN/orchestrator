# Phase State Schema

## Purpose

`_phase/status.md` is the single source of truth for a task's lifecycle phase.
Every skill that can change phase MUST read this file on entry and write to it on exit.
A skill that enters when `phase:` does not match its expected phase MUST stop and print:
`PHASE MISMATCH — expected <X>, current phase is <Y>. Read _phase/status.md.`

## File Location

`_phase/status.md` lives at the task root (beside `_phase/`).
It is NOT tracked in git (add to `.gitignore` or use a gitignored subdirectory).

## Schema

~~~yaml
task: <one-line task identifier>
phase: discussing | planning | implementing | reviewing | done | blocked
blocked_reason: <string, only present when phase=blocked>
plan_start_hash: <git SHA when planning phase began, used for staleness check>
started: <ISO-8601 timestamp of current phase start>
~~~

## Timeline Block

After the YAML block, append a `## Timeline` section.
Each phase transition appends one line — never edit existing lines.

~~~
## Timeline
2026-04-18T10:00Z  discussing   → planning    (plan file: docs/plans/foo.md)
2026-04-18T10:45Z  planning     → implementing
~~~

## Append Protocol

To write a transition without corrupting the YAML:
1. Read the full file.
2. Update ONLY the `phase:` (and `started:`) keys in the YAML block.
3. Append one line to `## Timeline` — never insert, never edit past entries.

## Skill Entry Guard (copy this block into each skill's SKILL.md preamble)

```
### Phase Guard
1. Read `_phase/status.md` (if file absent → create it with `phase: discussing`).
2. If `phase:` ≠ `<EXPECTED_PHASE_FOR_THIS_SKILL>` → STOP. Print PHASE MISMATCH error. Do not proceed.
3. Proceed.
```
