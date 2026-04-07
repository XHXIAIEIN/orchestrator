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

## Phase Gates

For multi-phase work (Spec → Plan → Implement → Verify), each phase boundary requires an explicit gate check before proceeding.

Insert a gate block between phases:

```
--- PHASE GATE: [phase name] → [next phase] ---
□ Deliverable exists: [specific artifact — spec doc, plan file, passing tests]
□ Acceptance criteria met: [list each criterion with evidence]
□ No open questions: [all ambiguities resolved, or explicitly deferred with rationale]
□ Owner review: [required/not required — if required, STOP and wait]
```

### Gate Rules

1. **No implicit phase transitions.** Moving from planning to implementation without a gate check is a protocol violation.
2. **"Owner review: required" means STOP.** Do not proceed until the owner explicitly approves. This is a hard gate, not a suggestion.
3. **Deferred questions must be logged.** If you proceed with an open question, write it as a `⚠️ ASSUMPTION:` in the plan with a rationale. The owner can challenge it later.
4. **Gate evidence must be concrete.** "Spec looks complete" is not evidence. "Spec covers 3 endpoints, 2 error cases, 1 auth flow — all with request/response examples" is evidence.

### Default Gate Configuration

| Transition | Owner Review Required? |
|-----------|----------------------|
| Spec → Plan | Yes (scope confirmation) |
| Plan → Implement | No (plan IS the approval) |
| Implement → Verify | No (automatic) |
| Verify → Ship/Commit | No (evidence-based) |

Override: If the user says "just do it" or grants blanket approval, all gates become automatic (still logged, but no STOP).

## Dependency Declaration

If step N depends on step M, declare explicitly:
```
3. Add route `/api/users` in `app.py` calling `validate_email` from step 1
   - depends on: step 1
   → verify: `curl -X POST localhost:8000/api/users -d '{"email":"bad"}' | grep 400`
```

Implicit dependencies (reader must infer order) are not allowed.
