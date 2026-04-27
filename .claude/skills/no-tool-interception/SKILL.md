---
name: no-tool-interception
description: "Stop-hook interception for non-tool responses that claim completion without verification evidence."
---

# No-Tool Interception

## Identity

You are a stop-gate enforcer. Your job is to intercept agent responses that claim task completion without providing verification evidence. Three specific response shapes trigger a block.

## How You Work

The `no-tool-gate.sh` Stop hook reads `last_assistant_message` from stdin JSON and checks for three intercept patterns:

### Case 1: Completion Claim Without Verify Token

**Triggers when**: Response contains a completion signal matching `(任务完成|task complete|完成了|搞定|all done|done\.)` (case-insensitive) AND lacks `[VERIFY]` or `VERDICT:` token.

**Block message**: `[no-tool-gate] 检测到完成声明但缺少 [VERIFY] 或 VERDICT token。请运行验证命令后再声明完成。`

**Bypass**: Include `[VERIFY]` followed by actual verification output, or `VERDICT: PASS/FAIL/PARTIAL` from a verify-subagent.

### Case 2: Code Block Without Explanation

**Triggers when**: Response is >200 characters of code block content (``` fenced) with <30 characters of natural language text outside the fence.

**Block message**: `[no-tool-gate] 纯代码块响应缺少说明。请补充 tool call 或说明下一步操作。`

**Rationale**: A response that is 99% code with no context means the agent is dumping output without directing the work.

### Case 3: Empty or Truncated Response

**Triggers when**: `last_assistant_message` is empty, or contains `[max_tokens]`/`[truncated]` markers, or is under 10 characters.

**Block message**: `[no-tool-gate] 响应不完整，请重新生成。`

**Rationale**: Truncated responses from context overflow should not be silently accepted as task completion.

## Output Format

When a block fires, the hook outputs:

```json
{"decision": "block", "reason": "[no-tool-gate] <specific message>"}
```

Exit code 1. The agent receives the reason as a continue-prompt injection.

## Quality Bar

- The hook is bypass-safe: `[VERIFY]` must appear literally, not as a paraphrase.
- Case 1 is the primary pattern; Cases 2 and 3 are secondary guards.
- The hook exits 0 (pass) when none of the three cases match.

## Boundaries

- Does NOT block technical responses that happen to contain "done" mid-sentence if they also contain `[VERIFY]` or `VERDICT:`.
- Does NOT block responses to pure research/explanation tasks (no completion signal pattern present).
- See `constraints/block-patterns.md` for Layer 0 pattern definitions.
