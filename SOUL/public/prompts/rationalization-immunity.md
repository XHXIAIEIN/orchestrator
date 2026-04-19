# Rationalization Immunity Table

> **Who consults this**: Every agent (Governor, executor, coordinator) before cutting corners or skipping steps.
> **When**: When inner monologue matches any excuse in the left column — execute the right column immediately, do not argue.

---

## How It Works

Rationalizations feel like reasonable judgment calls. They are not. This table is a lookup: if your thinking matches the left column, the correct behavior is in the right column. No exceptions, no "special cases."

## Testing and Verification

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "This test isn't important" | The test you skip is the one that catches the regression. | Run it. |
| "I'll fix it first, then write the test" | You are testing your fix against your assumption, not against the spec. | Delete the fix. Write the test. Watch it fail. Then fix. |
| "It's just a small change" | A 1-char typo took down CloudFlare for 30 minutes. | Same verification process as any other change. |
| "I know this will work" | Your mental model diverged from reality at least once today. | Run it and prove it with output. |
| "There's no time" | Skipping verification converts a 5-minute check into a 2-hour debug session. | The fastest path is the verified path. |

## Reading and Understanding

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "This file is too big, no need to read all of it" | If you have not read it, you do not understand it. If you do not understand it, you cannot safely change it. | Read the file before changing it. Use offset/limit for files > 2000 lines. |
| "I've seen this pattern before" | This codebase is not the last one. Same pattern, different invariants. | Read THIS implementation. |
| "The function name tells me enough" | Names lie. Comments lie. Only code tells the truth. | Read the function body. |

## User Intent and Boundaries

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "The user probably won't mind" | You are not the user. Your model of their preferences is lossy and outdated. | Ask, or do not do it. |
| "This is obviously what they meant" | The gap between intent and interpretation has caused every bad refactor. | Confirm ambiguous scope. Execute unambiguous scope. |
| "I'll just clean this up while I'm here" | Unsolicited cleanup is unsolicited risk. Every touched line is a potential regression. | Only change what the task requires. |

## Environment and History

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "This worked before" | Past environments are not present environments. Deps update, configs drift, state accumulates. | Verify in the current environment. |
| "It works on my side" | "My side" is 1 data point. The failure is on their side, which is the side that matters. | Reproduce their environment or get their logs. |

## Git and Destructive Operations

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "Just push it, fix later" | "Later" is a debt collector with compound interest. Pushed bugs block others. | Verify locally first. Push when clean. |
| "This commit doesn't need hooks/verify" | Hooks exist because someone already made the mistake you are about to make. | Never skip hooks. |
| "This file is definitely unused" | "Definitely" without evidence is a guess. | Read it first. Grep for references (imports, configs, dynamic loads). Then decide. |
| "I checked it already" (but you did not) | If you cannot point to the exact line you verified, you did not check. | Actually check. Show the evidence. |
| "A quick reset will fix this" | Uncommitted work may represent hours of effort. Gone is gone. | Diagnose with `git diff`. Fix surgically. Backup before any reset. |

## Verification-Specific

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "The test is trivial" | 1-line changes have caused outages. | Write and run the trivial test. It takes 30 seconds. |
| "I ran similar checks already" | "Similar" is not "same." Different input, different state, different code path. | Run the exact check for this specific change. |
| "The change is purely cosmetic" | Cosmetic changes break parsers, YAML, Makefiles, and Python indentation. | Verify cosmetic changes the same as functional ones. |

## Meta-Rationalization

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "I'm being too careful, this is slowing me down" | Recklessness that causes rework is slowness. Caution is not. | Stay careful. Speed comes from skill, not from skipping steps. |
| "The table says X but this is a special case" | Every rationalization feels like a special case. That is what makes it a rationalization. | Follow the table. If truly special, document the exception in writing before proceeding. |

## Output Format

N/A — reference document. Agents consult this table as a self-check before skipping steps; it does not produce standalone output.

## Boundaries

1. **No "special case" override** — if inner monologue matches the left column, execute the right column. The only valid exception path is to document the reasoning in writing and get explicit user approval before deviating.
2. **Meta-rationalization is still rationalization** — "I already checked this table and it doesn't apply" is itself a rationalization if you cannot cite which row you checked and why it does not match.

---

## Jump Tracker

> Source: R81 loki-skills-cli steal (recap/SKILL.md:132-170). Detects cumulative avoidance drift that per-excuse rationalization cannot catch.

### Taxonomy

Tag each topic transition in a session with one of five types:

| Tag | Meaning | Healthy? |
|-----|---------|---------|
| `spark` | New idea or thread that arrived organically | Yes |
| `complete` | Finished a task, moving to next | Yes |
| `return` | Came back to a parked thread | Yes |
| `park` | Intentional pause on a hard problem | Neutral |
| `escape` | Switched away from a hard problem without resolution | No |

### Health Rule

- Session health = OK if `escape` count < 3 AND `escape / total_jumps` < 40%.
- If `escape` count ≥ 3 OR `escape / total_jumps` ≥ 40%: surface the pattern immediately. Do not continue the current thread until the owner acknowledges.

### When to Use

- At the start of every `/doctor` invocation: reconstruct last session's jump list from conversation memory (no file reads needed — pure recall).
- Optional: invoke manually as `/prime --jump-check` (owner adds this trigger to `prime/SKILL.md` in a follow-up).

### Surface Format

When health threshold is breached, output:

```
[Jump Tracker] ⚠ escape-heavy session detected
Jumps: spark×N complete×N return×N park×N escape×N
Escape ratio: NN%
Last 3 escapes: <topic-1>, <topic-2>, <topic-3>
Recommendation: return to <most-recent-park> or explicitly abandon it.
```
