<!-- TL;DR: Lookup table: if inner monologue matches left column, execute right column. -->
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

## Data Fabrication

| Rationalization | Rebuttal | Correct Behavior |
|---|---|---|
| "I'll use mock data for now" | "For now" never gets replaced. Mock data ships, real data never arrives. | Stop. Get real data or tell the owner explicitly what's blocked and why. |
| "Stubbed this out, will return real later" | You will not return. The stub becomes the implementation. | Stop. Implement the real thing or surface the blocker. |
| "Assuming the API returns X" | Assumptions baked into code are bugs waiting to be discovered in production. | Run the API call and handle its actual response, or block on inability to reach it. |
| "For now let's just hardcode this" | "Just hardcoding" is a commitment with an invisible expiry date that always passes. | Use the real source or declare the dependency explicitly as unresolved. |
| "Placeholder value, will fill in later" | Placeholders accumulate. There is no "later" in an agent's execution. | Fill it now with real data, or state to the owner that you cannot proceed without it. |
| "TODO: implement this properly later" | A TODO in committed code is a lie: you committed something unfinished and claimed it done. | Either implement it now or do not commit the file. |
| "Mocking \<service\> since I can't reach it" | Mocking an unreachable service produces a test that can never fail in a way that matters. | Tell the owner the service is unreachable and what that means for progress. Do not fake the interaction. |

## Output Format

N/A — reference document. Agents consult this table as a self-check before skipping steps; it does not produce standalone output.

## Boundaries

1. **No "special case" override** — if inner monologue matches the left column, execute the right column. The only valid exception path is to document the reasoning in writing and get explicit user approval before deviating.
2. **Meta-rationalization is still rationalization** — "I already checked this table and it doesn't apply" is itself a rationalization if you cannot cite which row you checked and why it does not match.

## Code-Level Examples

These pairs show what the rationalization looks like in actual code and diffs, not just mindset.
Format: ❌ what an LLM rationalizes into existence → ✅ what should have happened.

---

### Testing / Verification

**Rationalization**: "It's just a small change — the tests should still pass."

❌ Bad:
```python
# Changed one line in auth.py, declared done without running tests
def authenticate(user, password):
    return user.password_hash == hash(password)  # removed salt — "trivial fix"
```

✅ Correct:
```bash
# Run the exact test suite before declaring done
pytest tests/test_auth.py -v
# Read FULL output — not just "X passed"
# Investigate every warning before claiming green
```

---

### Reading Before Changing

**Rationalization**: "I've seen this pattern before — I know how it works."

❌ Bad:
```python
# Assumed function signature from the name, didn't read the body
result = validate_input(data)  # added call — turns out validate_input raises on None, not returns False
```

✅ Correct:
```bash
# Read the function before calling it
grep -n "def validate_input" src/validators.py
# Then read lines N to N+20 to see return type, exceptions, side effects
```

---

### Git Operations

**Rationalization**: "A quick reset will fix this — I'll just start clean."

❌ Bad:
```bash
git reset --hard HEAD~1  # lost 2 hours of uncommitted exploration work
```

✅ Correct:
```bash
git diff HEAD  # read what's actually different
git stash      # backup uncommitted work first
# Diagnose the specific issue from the diff
# Fix surgically — don't nuke the branch
```

---

### Scope Creep

**Rationalization**: "I'll just clean this up while I'm here — it's obviously broken."

❌ Bad:
```diff
-def process(items):
-    for i in items: do_thing(i)
+def process(items: list[Item]) -> None:  # added types
+    for i in items:
+        do_thing(i)  # added line break
+        log.debug(f"processed {i}")  # added logging — "obviously needed"
```

✅ Correct:
```diff
# Only the line the task required
-    for i in items: do_thing(i)
+    for item in items: do_thing(item)  # renamed per task requirement
# Every other line: untouched
```

---

### Completion Claims

**Rationalization**: "Based on the changes, this should work — I'm confident."

❌ Bad (in agent output):
```
I've updated the rate limiter. Based on the changes, requests should now be
limited to 100/minute. I'm confident this is correct.
```

✅ Correct (in agent output):
```
Ran: curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/api/test
Result after 101 requests: 429 Too Many Requests
All 47 tests pass (pytest output above, 0 failures, 0 warnings).
Task complete.
```

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

## Review Dismissal

> Applies when receiving any reviewer output. Load this file BEFORE reading the review — once you have read the findings, rationalizations have already formed.

| Forbidden Dismissal | Why It Fails | Correct Behavior |
|---|---|---|
| "This is low risk" | Risk is assessed after investigation, not before. You have not investigated. | Fix it. |
| "This is out of scope for this task" | Scope does not make a bug disappear. It makes it someone else's future emergency. | Fix it or file a tracked issue — do not dismiss. |
| "This is pre-existing / not my fault" | You touched the code. You own the blast radius. | Fix it. |
| "The reviewer doesn't understand the context" | You have 30 seconds of context. The reviewer has the full diff. | Fix it. |
| "This will break other things" | Unverified fear. Run the tests. | Run the tests. If they break, fix the root cause. |
| "This is a style nit" | Style rot compounds. One "nit" per PR = unreadable codebase in 6 months. | Fix it. |
| "I'll address this in a follow-up" | Follow-ups are where good intentions go to die. | Fix it now or write a concrete JIRA/issue with repro steps before closing this session. |

## Pre-Load Rule

**If you are about to read reviewer output** — stop. Load (read) this file first.
"If you have already read the findings, the rationalization has already formed. This section is useless to you now."
The correct sequence is: load `rationalization-immunity.md` → THEN read reviewer findings → THEN decide to fix or push back.
