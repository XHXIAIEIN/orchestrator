"""
Agent Evaluation module (R38 — stolen from Inspect AI, promptfoo, Braintrust).

Provides:
  - trajectory: Tool call trajectory capture, scoring, and assertions
  - scoring: LLM-as-Judge rubric-based scoring with partial credit
  - corpus: Production→Test feedback loop (failed tasks → eval corpus)
"""
