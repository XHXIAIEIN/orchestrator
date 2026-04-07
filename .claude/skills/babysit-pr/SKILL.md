---
name: babysit-pr
description: "Monitor a PR's CI checks and autonomously fix failures. Use when: (1) gh pr checks shows failed status, (2) user says 'CI is red', 'fix CI', 'babysit', or 'watch this PR'. NOT for: infrastructure failures (runner timeout, rate limit), workflow config changes, or flaky tests needing investigation. Max 5 fix rounds, each as separate commit."
---

# babysit-pr — Autonomous PR Monitoring

You are babysitting a pull request. Your job is to watch CI checks, and if any fail, diagnose and fix them.

## Inputs

The user provides a PR number or URL. Extract:
- Repository (default: current repo)
- PR number

## Loop

Repeat up to 5 rounds:

### 1. Check CI Status

```bash
gh pr checks <PR_NUMBER> --json name,state,conclusion
```

If all checks pass → report success and STOP.
If any check is "in_progress" → wait 60 seconds and re-check (max 3 waits).
If any check failed → proceed to step 2.

### 2. Read Failure Logs

```bash
gh run view <RUN_ID> --log-failed
```

Extract the error message, failing test name, and relevant context.

### 3. Diagnose

Read the failing file(s). Understand why the test/lint/build failed.
Apply the Surgical Changes principle: fix ONLY the failure, don't clean up adjacent code.

### 4. Fix and Push

Make the minimal fix. Commit with message:
```
fix(ci): <what was fixed>

babysit-pr round N/5
```

Push to the PR branch:
```bash
git push
```

### 5. Wait and Re-check

Wait 60 seconds for CI to restart, then go back to step 1.

## Safety Rules

- **Max 5 rounds.** If CI is still red after 5 fix attempts, report the remaining failures and STOP.
- **Never force-push.** Only regular push.
- **Never modify CI config** (.github/workflows/) to make tests pass. Fix the code, not the tests.
- **If the failure is infrastructure** (timeout, runner unavailable, rate limit), report it and STOP. Don't try to fix infra.
- **Each fix must be a separate commit** with a clear message. No squashing.

## Common Rationalizations

These thoughts mean you're about to violate the babysit protocol:

| Rationalization | Reality | Correct Behavior |
|---|---|---|
| "This test is flaky, I'll just re-run" | Flaky tests have root causes. Re-running without diagnosis is coin-flipping. | Read the failure log. If truly flaky (timing, network), report it as infra. Don't retry blindly. |
| "I'll fix the test to match the new behavior" | You're making the test pass, not making the code correct. Tests define expected behavior — code should conform. | Fix the code, not the test. Unless the test expectation is genuinely wrong. |
| "This is just a lint warning" | Lint rules exist because someone shipped a bug that rule would have caught. | Fix the lint issue. Don't disable the rule. |
| "Let me also clean up this file while I'm here" | Babysit scope is CI fixes ONLY. Mixing cleanup with fixes makes rollback impossible. | Fix the failure. Nothing else. |
| "The CI config is wrong, let me fix it" | Modifying CI config to make tests pass is cheating, not fixing. | Report CI config issues to the user. Don't touch workflows. |
| "Round 5 will definitely work" | If 4 rounds failed, your mental model is wrong. Round 5 with the same model will also fail. | Stop at round 5. Escalate with a diagnostic report. |

## Exit Conditions

- All checks green → "PR is green. All checks passing."
- 5 rounds exhausted → "Babysit limit reached. Remaining failures: [list]"
- Infrastructure failure → "CI infrastructure issue: [description]. Manual intervention needed."
- User interrupts → Stop immediately.

## Common Rationalizations

| Thought | Reality | Correct Behavior |
|---------|---------|-----------------|
| "The test is flaky, I'll skip it" | You don't know that without evidence. Flaky = same code passes sometimes. | Run the test 2x. If it fails both times, it's real. Only skip with `gh run rerun` evidence of prior flaky history. |
| "I'll just disable the lint rule" | Disabling rules is modifying CI config — explicitly forbidden above. | Fix the code to satisfy the linter. |
| "This CI failure looks like infra" | Infra failures are timeouts/runner issues, NOT code errors with clear stack traces. | If there's a stack trace pointing to code, it's a code bug. Diagnose it. |
| "Let me refactor this while I'm here" | Surgical changes: fix ONLY the failure. Adjacent cleanup is scope creep. | Fix the one failing line. Commit. Move on. |
| "5 rounds isn't enough, I need more" | 5 rounds is the hard limit. If you can't fix it in 5, the problem is your diagnosis, not the round count. | Report remaining failures honestly. Don't request more rounds. |
| "I'll batch these 3 fixes into one commit" | Each fix = separate commit. Batching defeats bisectability. | One fix, one commit, one push. |
