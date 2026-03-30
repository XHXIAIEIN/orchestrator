---
dimension: memory
pattern_key: agent-memory-stable
gate: advisory
tier: fast
weight: 10
threshold_pass: 85
threshold_warn: 70
error_summary: Memory score dipped below stable baseline
learning_summary: Contradiction detection — FLAG the contradiction instead of silently picking one
---

Memory is normally stable. Advisory-only monitoring.
