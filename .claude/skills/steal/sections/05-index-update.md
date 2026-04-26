## Phase 4: Index Update

After writing the report:

1. **Update steal consolidated index** in memory — add a row to the round table:
   `| R<N> | <date> | <source> | <stars> | <key patterns summary> | <status> |`

2. **If P0 patterns exist**, draft an implementation plan following `SOUL/public/prompts/plan_template.md` format → save to `docs/superpowers/plans/`

3. **Dedup check**: Before adding any pattern, grep `docs/steal/` for similar names. Overlap > 60% → update existing entry (per dedup_matrix.md)

4. **Cross-reference**: Check if patterns connect to open items from previous rounds. A new discovery might close an old gap or validate a shelved P2.

## Common Rationalizations

These thoughts mean you're about to produce a shallow steal report:

| Rationalization | Reality | Correct Behavior |
|---|---|---|
| "This project is too simple to learn from" | Simple projects often have the cleanest patterns. Complexity ≠ value. | Analyze anyway. A 200-line orchestrator may have a tighter loop than a 20K-line framework. |
| "We already have something similar" | "Similar" without diff is a guess. Their edge case handling may cover gaps you don't know exist. | Show the comparison matrix. Diff implementations line by line. |
| "The README explains enough" | READMEs are marketing. The real design decisions are in the code, commit history, and error handling. | Read implementation code. `grep` for error handling, retries, edge cases. |
| "This domain is too different from ours" | Structure transfers across domains. A game engine's ECS is an agent orchestrator. A compiler's IR pipeline is a prompt chain. | Ask "Is the *structure* transferable?" before dismissing. |
| "I'll just list the features" | Feature lists are not steal reports. Anyone can read a README. The value is in *mechanisms* and *why they work*. | Extract the HOW, not the WHAT. Include 5-20 line code snippets. |
| "P2 is fine for this" | Downgrading to avoid implementation work is the #1 rationalization in steal reports. | Re-check P0 criteria: does it fill a gap? Is it < 2h? If yes, it's P0. |
| "We're already better" | Overconfidence kills learning. Even if overall architecture is stronger, individual patterns can be superior. | Find the ONE thing they do better. Every project has at least one. |
| "I don't have time for the six-dimensional scan" | Skipping dimensions = missing patterns. Security and failure recovery are the most commonly skipped — and the most valuable. | Do all six. Empty dimensions are fine. Skipped dimensions are not. |
| "I can analyze this from the GitHub page" | GitHub web view hides cross-file context, directory structure, and test fixtures. You'll only see the surface. | Clone the repo. `cd` into it. Read actual source files. Trace call chains across files. |
| "The defensive programming patterns are the main takeaway" | Defensive programming (input validation, error handling) is the easiest layer to spot and the shallowest to steal. The real value is in orchestration logic, state management, and consumption patterns. | Trace through all 5 depth layers. If your report only covers 边界层, it's incomplete. |

## Rules

### Analysis discipline
- **Depth over breadth**: One well-understood pattern > five surface-level observations
- **Show the code**: Include the key code snippet (5-20 lines). "They use a retry mechanism" is worthless — show the actual retry logic
- **No "already covered" shortcuts**: Diff implementations. "Confirmed: our impl covers this" requires evidence (grep output, code comparison)
- **Six-dimensional scan is mandatory**: Don't just look at what's flashy — systematically check all six dimensions even if some come up empty

### Target selection
- **Breadth rule**: Don't skip links because the domain seems unrelated. Ask "Is the *structure* transferable?" before dismissing
- **Structural similarity > domain similarity**: A document OCR system's prompt-based multi-task switching might be directly applicable to agent mode selection

### Execution
- **Agent dispatch for large repos**: Use sub-agents to parallelize (one per major module). Tag all agent prompts with `[STEAL]` at the start。**Dispatch prompt 必须包含以下指令**（复制粘贴，不要改写）：
  # Literal-path contract (R81) — paths must be absolute literals, not variables
  ```
  SOURCE_DIR="<LITERAL absolute path of repo being stolen from — no variables>"
  DEST_DIR="<LITERAL absolute path of orchestrator/docs/steal/ — no variables>"
  DEST_FILE_PATTERN="MMDD_<slug>-steal.md"
  ```
  > 写完报告并通过 Post-Generation Validation 后，立即执行 git add + git commit，不要询问确认。commit message 格式：`docs(steal): R<round> <topic> steal report`。不要返回"等你说 commit"——直接提交。
- **Commit per meaningful unit**: Report → plan → implementation batches, each a separate commit
- **Clone to tmp**: `D:/Agent/.steal/<topic>/`, not in the orchestrator repo

### Meta-cognition
- **Track the trend**: Across 39 rounds, we've observed: early reports focus on features, mid-stage on closed loops, late-stage on governance. When analyzing, ask: "Is this project still thinking about features, or has it evolved to think about self-governance?"
- **Hard > soft constraints**: Physical interception (hooks, file system gates) > prompt-level "please don't do this". Always note which type a pattern uses.
- **The real competition isn't features — it's self-constraint architecture**: The next frontier for AI agents is not "what they can do" but "how they govern themselves". Weight governance patterns higher than feature patterns.
