---
dimension: tooling
pattern_key: agent-tooling-variance
gate: soft
tier: normal
weight: 15
threshold_pass: 90
threshold_warn: 75
error_summary: Agent tooling score unstable (80-95) — tool selection reasoning sometimes shallow
learning_summary: When recommending tools, explicitly state WHY alternatives are worse — not just why the pick is good
---

Tooling dimension swings between 80-95 across exams.
The agent sometimes gives correct tool recommendations without sufficiently
explaining tradeoffs of alternatives.
