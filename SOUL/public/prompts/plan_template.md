# Plan: {title}

## Goal
{one sentence, verifiable — what does "done" look like?}

## File Map
All files this plan will touch. Reviewer uses this for scope check.
- `path/to/file1.py` — Create | Modify | Delete
- `path/to/file2.ts` — Create | Modify | Delete

## Steps

Each step: 2-5 minutes, action verb, explicit verify command.

1. [Action verb] [specific target] → verify: [exact command]
2. [Action verb] [specific target] → verify: [exact command]
   - depends on: step 1
3. [Action verb] [specific target] → verify: [exact command]

## No Placeholder Iron Rule

The following are BANNED in plan steps. Every one must be replaced with specifics:

| Banned phrase | Replace with |
|---|---|
| "implement the logic" | Exact logic: "Add null check for `user.email`, return 400 if missing" |
| "add appropriate error handling" | Exact errors: "Catch `ConnectionError`, retry 3x with 1s backoff, then raise `ServiceUnavailable`" |
| "update as needed" | Exhaustive list: "Update `config.yaml` key `db.host` from localhost to `${DB_HOST}`" |
| "etc." / "and so on" | Full enumeration of every item |
| "similar to X" | Write out the actual code/steps, even if repetitive |
| "refactor" (alone) | Specific transform: "Extract lines 42-78 into `validate_input()`, call from `handle_request()`" |
| "clean up" (alone) | Specific items: "Remove unused import `os` on line 3, delete empty `__init__.py` in `utils/`" |
| "optimize" (alone) | Specific change: "Replace O(n^2) nested loop in `search()` with dict lookup, expected O(n)" |

## Step Format Reference

Good:
```
1. Create `src/validators/email.py` with `validate_email(addr: str) -> bool`
   that checks RFC 5322 format using `re.fullmatch(EMAIL_PATTERN, addr)`
   → verify: `python -c "from src.validators.email import validate_email; assert validate_email('a@b.com'); assert not validate_email('bad')"`
```

Bad:
```
1. Add email validation logic
   → verify: test it
```

## Dependency Declaration

If step N depends on step M, declare explicitly:
```
3. Add route `/api/users` in `app.py` calling `validate_email` from step 1
   - depends on: step 1
   → verify: `curl -X POST localhost:8000/api/users -d '{"email":"bad"}' | grep 400`
```

Implicit dependencies (reader must infer order) are not allowed.

## Phase Gates

Each phase ends with a gate. Do NOT cross into the next phase until all gate conditions pass.

### Gate 1: SPECIFY → PLAN
Before writing any plan steps:
- [ ] Goal is one sentence, verifiable (not "improve X" — what does done look like?)
- [ ] File Map is complete (every file that will be touched is listed)
- [ ] Ambiguities resolved (if spec says "add auth" but not which type → ASK, don't guess)
- [ ] Scope confirmed (nothing in File Map that the user didn't ask for)

### Gate 2: PLAN → IMPLEMENT
Before writing any code:
- [ ] Every step has an action verb + specific target + verify command
- [ ] No banned placeholder phrases (check against Iron Rule table above)
- [ ] Dependencies are explicit (no implicit ordering)
- [ ] Steps are 2-5 min each (split anything bigger)
- [ ] Owner has seen the plan (unless task is clearly reversible and < 30 min total)

### Gate 3: IMPLEMENT → DONE
Before declaring completion:
- [ ] Every step's verify command has been run and passed
- [ ] No unrelated changes in `git diff` (surgical changes rule)
- [ ] Orphaned imports/vars from YOUR changes are cleaned up
- [ ] If tests exist, they pass
