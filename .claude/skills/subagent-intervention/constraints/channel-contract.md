# Layer 0: File-Channel Contract — Subagent Intervention

This contract is non-negotiable. All parties (parent agent, subagent, hooks) MUST comply.

## IPC Root

`temp/{task}/` is the IPC root directory for the subagent identified by `{task}` (the `task_id`).

All channel files live directly under this directory. No subdirectories.

## Channel Files

### `_stop.txt`

- **Written by**: parent agent
- **Read by**: subagent (via `subagent-channel.sh` hook)
- **Semantics**: Presence signals that the subagent MUST stop after completing the current turn. Content is the stop reason (human-readable string).
- **Consume-once**: hook reads content, deletes the file immediately, outputs block decision. File MUST NOT persist after being read.

### `_keyinfo.txt`

- **Written by**: parent agent
- **Read by**: subagent (via `subagent-channel.sh` hook)
- **Semantics**: Content is injected verbatim into the subagent's working context as supplementary key information. Useful for mid-task corrections that don't require stopping.
- **Consume-once**: hook reads content, deletes the file immediately, appends to `state/keyinfo-${TASK_ID}.txt` for persistence within the session.

### `_intervene.txt`

- **Written by**: parent agent
- **Read by**: subagent (via `subagent-channel.sh` hook)
- **Semantics**: Content is injected as a `[PARENT INTERVENTION]` block in the subagent's next turn prompt. Used when the parent detects drift or needs to redirect the subagent mid-task.
- **Consume-once**: hook reads content, deletes the file immediately, outputs block decision with intervention content.

## Ownership Rules

- **Parent writes, subagent reads**: parent agent is the sole writer of all three channel files.
- **Subagent MUST NOT write** `_stop.txt`, `_keyinfo.txt`, or `_intervene.txt`. Writing these files from inside the subagent is a protocol violation.
- Subagent output goes to `temp/{task}/output.txt` (separate file, NOT a channel file).

## Consume-Once Semantics

Every channel file is consumed exactly once:
1. Hook detects file presence
2. Hook reads content into variable
3. Hook deletes the file (`rm -f`)
4. Hook acts on content (block / append / pass)

A file that is read but not deleted is a bug. A file that is deleted before being read is also a bug.

## Lifecycle

```
parent:  mkdir -p temp/{task}/
parent:  pass task_id to subagent via env/prompt
subagent: runs turns, hook checks temp/{task}/ at each PostToolUse
parent:  writes _intervene.txt when drift detected (Monitor tool)
subagent: hook fires, reads+deletes _intervene.txt, blocks with [PARENT INTERVENTION]
parent:  writes _stop.txt when task should terminate
subagent: hook fires, reads+deletes _stop.txt, blocks and exits
```
