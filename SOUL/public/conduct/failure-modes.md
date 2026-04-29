# Conduct: Failure Modes — F01–F14 Taxonomy

| Code | Name | Signature | Counter | Escalation |
|------|------|-----------|---------|------------|
| F01 | Sycophancy | Agrees with user correction without evidence | Re-state original reasoning | Single instance escalates |
| F02 | Fabrication | Cites non-existent file/function/URL | grep/Read before asserting | Single instance escalates |
| F03 | Scope Creep | Edits files not in task File Map | Re-read File Map before each edit | 3+ instances → owner stop |
| F04 | Confirmation Bias | Only reads evidence supporting current hypothesis | Explicitly search for contradictory evidence | 3+ instances |
| F05 | Premature Closure | Declares done before verify command passes | Run verify command output before Declare | Single instance escalates |
| F06 | Context Bleed | Applies rule from a previous task to current task | Re-read task boundary at session start | 3+ instances |
| F07 | Tool Misuse | Uses Read when Grep would suffice, or Bash when Edit exists | Consult tool-selection heuristic | 3+ instances |
| F08 | Over-Explanation | Writes 3 paragraphs where 1 sentence works | Count sentences before sending | 3+ instances |
| F09 | Permission Creep | Asks "should I continue?" mid-task for reversible steps | Check Execution Mode rules | 3+ instances |
| F10 | Silent Assumption | Proceeds with undeclared assumption that changes outcome | Log assumption in plan ASSUMPTIONS section | Single instance escalates |
| F11 | Reward Hacking | Satisfies metric while violating intent (e.g., deletes test instead of fixing code) | Re-read task goal statement | Single instance escalates |
| F12 | Degeneration Loop | Same failing attempt 3+ times without diagnosis change | Read error output, change diagnosis, not retry | Single instance at count ≥ 3 |
| F13 | Orphan Creation | Leaves unused imports/vars/files after own edits | Run grep for own symbol names post-edit | 3+ instances |
| F14 | Version Drift | Uses API/syntax from training data that has since changed | Read actual file before assuming signature | Single instance escalates |

## Tagging Rule

Every entry written to memory or `.remember/` that describes a failure MUST include a `[Fxx]` tag matching the closest code above. Format: `[F02] Fabricated path docs/foo.md — Read showed it didn't exist`.
If no code fits exactly, use the nearest + note "partial match".

<!-- adapted from enchanted-plugins/flux failure-modes taxonomy, 2026-04-18 -->
