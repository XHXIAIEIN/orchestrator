---
dimension: reasoning
pattern_key: agent-reasoning-stable
gate: advisory
tier: fast
weight: 10
threshold_pass: 90
threshold_warn: 80
error_summary: Reasoning score dipped below stable baseline
learning_summary: When rules are explicitly stated, apply them literally — do not let common sense override spec
---

Reasoning is normally stable at 90+. Advisory-only monitoring.
