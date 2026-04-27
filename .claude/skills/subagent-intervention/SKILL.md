---
name: subagent-intervention
description: "Out-of-band parent-to-subagent intervention via file channel. Parent monitors subagent progress and can stop, redirect, or inject key info without waiting for the subagent to ask."
---

# Subagent Intervention

## Identity

You are the parent agent orchestrating a long-running subagent task. This skill gives you a live control channel into the subagent without interrupting its execution loop — you write files, the subagent's PostToolUse hook reads and acts on them.

## How You Work

### Step 1: Parent Sets Up Temp Directory

Before dispatching the subagent, create the IPC root:

```bash
TASK_ID="my-task-$(date +%s)"
mkdir -p temp/${TASK_ID}/
```

### Step 2: Pass `task_id` to Subagent

Include `TASK_ID` in the subagent's environment or prompt:

```
Agent(
  subagent_type="claude-sonnet",
  system_prompt="...",
  prompt=f"Your task_id is {TASK_ID}. Export TASK_ID={TASK_ID} before running hooks.",
  env={"TASK_ID": TASK_ID}
)
```

The subagent must export `TASK_ID` so the `subagent-channel.sh` PostToolUse hook can locate its channel files.

### Step 3: Parent Monitors via Monitor Tool

After dispatch, use the Monitor tool to stream `temp/${TASK_ID}/output.txt`:

```
Monitor(path=f"temp/{TASK_ID}/output.txt")
```

Each line the subagent writes to `output.txt` arrives as a notification. This is how you detect drift, mistakes, or completion.

### Step 4: Parent Writes `_intervene.txt` When Drift Detected

If you see something wrong in the output stream:

```bash
echo "Stop using Plan A. Switch to approach B: <specific instructions>" > temp/${TASK_ID}/_intervene.txt
```

On the subagent's next PostToolUse hook fire, `subagent-channel.sh` reads `_intervene.txt`, deletes it, and outputs:

```json
{"decision": "block", "reason": "[PARENT INTERVENTION] Stop using Plan A. Switch to approach B: ..."}
```

The subagent receives this as a continue-prompt injection and redirects.

### Step 5: Stopping the Subagent

To terminate the subagent after its current turn:

```bash
echo "Task cancelled: higher priority work arrived." > temp/${TASK_ID}/_stop.txt
```

The hook fires, reads+deletes `_stop.txt`, and blocks with `[parent-stop]` reason.

### Step 6: Injecting Key Info (Non-Blocking)

To add context without stopping the subagent:

```bash
echo "The API endpoint changed to https://api.example.com/v2/" > temp/${TASK_ID}/_keyinfo.txt
```

The hook reads+deletes `_keyinfo.txt` and appends to `.claude/hooks/state/keyinfo-${TASK_ID}.txt`. The accumulated key info can be read into the next prompt.

### Step 7: Subagent's Obligation

At the end of every turn, the subagent MUST call the `consume_intervention_files` hook (implemented as `subagent-channel.sh` PostToolUse hook). This ensures channel files are checked after every tool use, not just at turn end.

## Output Format

- **Intervention block**: `{"decision": "block", "reason": "[PARENT INTERVENTION] <content of _intervene.txt>"}`
- **Stop block**: `{"decision": "block", "reason": "[parent-stop] <content of _stop.txt>"}`
- **Key info**: silent — content appended to `state/keyinfo-${TASK_ID}.txt`, no block

## Quality Bar

- Channel files are consume-once: read → delete → act. Never re-read a deleted file.
- Parent must not write multiple channel files simultaneously without ordering guarantees. Write one at a time.
- `_intervene.txt` takes priority over `_keyinfo.txt` in the hook (checked last, most disruptive).
- `_stop.txt` is checked first — if stop is set, skip all other channel files.

## Boundaries

- See `constraints/channel-contract.md` for Layer 0 file-channel ownership rules.
- Subagent MUST NOT write `_stop.txt`, `_keyinfo.txt`, or `_intervene.txt`.
- The Monitor tool observes `output.txt` — this is a different file, not a channel file.
