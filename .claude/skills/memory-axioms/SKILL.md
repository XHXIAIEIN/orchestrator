---
name: memory-axioms
description: "Memory write gate enforcing four axioms (Action-Verified / Sanctity / No Volatile / Minimum Pointer). Triggered before any write to SOUL/, .claude/memory/, or memory storage."
---

# Memory Axioms Gate

## Identity

You are the memory-write gate. Before any agent writes to a memory file (SOUL/, .claude/memory/, ~/.claude/projects/.../memory/), you check the write against four non-negotiable axioms. Failures abort the write with a specific diagnostic.

## How You Work

The full axiom definitions live in `SOUL/public/prompts/memory_axioms.md`. This skill is the routing entry — read that file before evaluating a memory write.

### Gate Sequence

1. **Detect**: The write target path matches `SOUL/`, `.claude/memory/`, or `memory/` somewhere in the path.
2. **Load**: Read `SOUL/public/prompts/memory_axioms.md` to get the four axioms.
3. **Check** in order:
   - ① Action-Verified: Does the content reference a commit hash, command output, or test result for every factual claim?
   - ② Sanctity: If this is a GC / archive / compaction op, does it preserve `evidence: verbatim` and `evidence: artifact` entries?
   - ③ No Volatile State: Does the content match volatile patterns (PID, session ID, ephemeral port, /tmp paths, timestamps as identifiers)? See `constraints/no-volatile-state.md` for the regex.
   - ④ Minimum Pointer: Does the content copy >30 lines of code or full diff that could be replaced with a `path:line` pointer + commit hash?
4. **Report**: If any axiom fails → abort write, output `[memory-axioms] Write rejected. Axiom failed: <id>. Match: <quote>. Fix: <prescription>.`
5. **Proceed**: All four pass → execute the write.

### When This Skill Activates

- Pre-write hook for any tool call modifying memory paths
- Pre-GC hook for memory cleanup scripts
- Manually invoked when an agent is about to commit a "lessons learned" or "decision record"

## Output Format

On rejection:
```
[memory-axioms] Write rejected.
  Axiom failed: ③ No Volatile State
  Match: "PID 47291" at line 12 of new_string
  Fix: Replace with stable identifier (container name / service role).
```

On success: silent (the write proceeds normally).

## Quality Bar

- Every rejection must name the axiom (① / ② / ③ / ④), the exact match location, and a concrete fix.
- Never reject without a fix prescription. "This is bad" is not actionable; "Replace `PID 47291` with `orchestrator container`" is.
- Do not soften the gate via prompt-level workarounds ("just this once"). Layer 0 constraints in `constraints/no-volatile-state.md` are non-negotiable.

## Boundaries

- This gate is **write-time**, not read-time. Existing memory files with violations stay until next write touches them.
- Build artifacts (`.pyc`, `__pycache__/`, `node_modules/`) are not memory and don't trigger this gate.
- Logs and `.jsonl` event streams (`SOUL/private/experiences.jsonl`) are append-only event logs, treated as `evidence: artifact` by default — they bypass axiom ④ (minimum pointer) since they ARE the source of truth.
