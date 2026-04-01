---
name: babysit-pr
description: "Monitor a PR's CI checks and autonomously fix failures. Use when CI is red on a PR and you want automated fix attempts."
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

## Exit Conditions

- All checks green → "PR is green. All checks passing."
- 5 rounds exhausted → "Babysit limit reached. Remaining failures: [list]"
- Infrastructure failure → "CI infrastructure issue: [description]. Manual intervention needed."
- User interrupts → Stop immediately.
