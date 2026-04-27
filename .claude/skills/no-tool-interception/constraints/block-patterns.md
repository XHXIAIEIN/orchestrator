# Layer 0: Block Patterns — No-Tool Interception

These patterns are non-negotiable. When the Stop hook detects any of these in the response WITHOUT `[VERIFY]` or `VERDICT:` token, it **MUST block**.

## Completion Signal Regex

```
(任务完成|task complete|完成了|搞定|all done|done\.)
```

Case-insensitive match. Applied against the full `last_assistant_message`.

## Block Condition

If response contains any completion signal **AND** lacks `[VERIFY]` or `VERDICT: (PASS|FAIL|PARTIAL)`, the Stop hook MUST block.

Both conditions must be true:
1. `last_assistant_message` matches the completion signal regex (case-insensitive)
2. `last_assistant_message` does NOT contain `[VERIFY]` AND does NOT contain `VERDICT:`

## Bypass Tokens (must appear literally)

Either of these tokens in the response bypasses the block:
- `[VERIFY]` — explicit verification step declared
- `VERDICT:` — adversarial verify-subagent result present (followed by PASS, FAIL, or PARTIAL)

## Non-Bypassable

The following do NOT bypass the block even if they appear in the message:
- "I verified it mentally"
- "should be fine"
- "already tested"
- Any paraphrase of [VERIFY] that is not the literal token
