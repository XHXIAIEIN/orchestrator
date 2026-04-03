"""
Agent Evaluation module (R38 — stolen from Inspect AI, promptfoo, Braintrust, AutoAgent).

Provides:
  - trajectory: Tool call trajectory capture, scoring, and assertions
  - scoring: LLM-as-Judge rubric-based scoring with partial credit
  - corpus: Production→Test feedback loop (failed tasks → eval corpus)
  - experiment: Keep/Discard experiment ledger for config evolution
"""
