---
name: subagent-io
description: "File-IO protocol for parent ↔ subagent communication. Parent writes input.txt + context.json, subagent appends to output.txt with [ROUND END] sentinels. Used with Monitor tool for live observation."
---

# Subagent IO Protocol

## Identity

You are the subagent file-IO protocol. Parent and subagent communicate through a shared `temp/{task_id}/` directory using a fixed file contract: `input.txt` (task spec, parent → subagent), `output.txt` (subagent's turn-by-turn log, subagent → parent), `reply.txt` (parent's mid-task response, parent → subagent), `context.json` (metadata). The `[ROUND END]` sentinel marks turn boundaries in `output.txt` so the parent can use Monitor to tail it.

## How You Work

### Directory Layout

```
temp/{task_id}/
  input.txt         # task spec (parent writes once at dispatch)
  output.txt        # subagent appends each turn (one round per [ROUND END])
  reply.txt         # parent writes when injecting mid-task input
  context.json      # absolute paths + metadata
  _stop.txt         # parent writes to abort subagent (consume-once)
  _keyinfo.txt      # parent writes to inject into next prompt prefix (consume-once)
  _intervene.txt    # parent writes [PARENT INTERVENTION] block (consume-once)
```

The `_stop` / `_keyinfo` / `_intervene` files belong to the [subagent-intervention](../subagent-intervention/SKILL.md) skill — they are listed here for completeness of the directory layout.

### File contracts

| File | Writer | Reader | Lifetime | Encoding |
|------|--------|--------|----------|----------|
| `input.txt` | parent (once) | subagent (once at start) | task | UTF-8 |
| `output.txt` | subagent (append per turn) | parent (Monitor tail) | task | UTF-8 |
| `reply.txt` | parent (overwrite) | subagent (read + delete) | per-turn | UTF-8 |
| `context.json` | parent (once) | subagent (read once) | task | UTF-8 JSON |

### context.json schema

```json
{
  "task_id": "abc-123",
  "temp_dir": "D:/proj/temp/abc-123/",
  "parent_task": "high-level goal description",
  "iteration_budget": 20,
  "verbose": false
}
```

All paths in `context.json` MUST be **absolute**. Relative paths break when subagent's CWD differs from parent's.

### output.txt format

Each subagent turn appends:

```
<turn content — analysis, tool calls, results>
[ROUND END]
```

The literal `[ROUND END]\n` sentinel terminates each turn. Parent's Monitor tail uses this sentinel to detect "subagent finished a turn, OK to inspect / intervene".

When `--verbose` (i.e., `context.json.verbose == true`) is set, the subagent also appends raw tool stdin/stdout to `output.txt` between turn content and `[ROUND END]`.

### reply.txt protocol

When parent wants to inject input mid-task (without using `_intervene.txt`'s [PARENT INTERVENTION] formatting):
1. Parent writes new content to `temp/{task_id}/reply.txt` (overwrite, not append).
2. Subagent at next turn start checks `reply.txt`; if present, reads content and appends to its prompt.
3. Subagent deletes `reply.txt` after consuming.

### Monitor integration

Parent uses the `Monitor` tool to tail `output.txt`:
- Each `[ROUND END]` line is a notification trigger.
- On notification, parent reads the last turn's content and decides whether to intervene.
- Parent never blocks on subagent — Monitor is push-based.

## Output Format

When dispatching a subagent with this protocol, the parent emits a setup block:

```
[subagent-io] Dispatching task abc-123
  temp_dir:  D:/proj/temp/abc-123/
  input:     <preview of input.txt first 200 chars>
  context:   {"task_id": "abc-123", "iteration_budget": 20}
  monitor:   tailing output.txt for [ROUND END]
```

## Quality Bar

- All paths in `context.json` are absolute. Never relative.
- `[ROUND END]` is a literal string with a trailing `\n` — never variant capitalization or punctuation.
- Subagent never writes to `_stop` / `_keyinfo` / `_intervene` (those are parent → subagent only).
- `temp/{task_id}/` is cleaned by the parent after task completion. Subagent does not delete its own dir.

## Boundaries

- This protocol is for sub-agent dispatches that need live parent observability. For one-shot subagent calls (parent waits for full result, no intervention), use the standard Agent tool without this overhead.
- File-based IPC is durable across crashes. If parent dies mid-task, the subagent's `output.txt` remains for postmortem.
- Step 27 of the impl plan is documentation; runtime adapter wiring is a future code task.
