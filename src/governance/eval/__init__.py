"""
Agent Evaluation module (R38 — stolen from Inspect AI, promptfoo, Braintrust, AutoAgent).

Provides:
  - trajectory: Tool call trajectory capture, scoring, and assertions
  - scoring: LLM-as-Judge rubric-based scoring with partial credit
  - corpus: Production→Test feedback loop (failed tasks → eval corpus)
  - experiment: Keep/Discard experiment ledger for config evolution
  - epochs: Multi-run evaluation with statistical aggregation (ScoreReducer)
  - early_stopping: Per-category adaptive stopping for mastered categories
  - regression: Bootstrap CI regression detection for score changes
  - registry: Decorator-based component registration for eval tasks/scorers
"""
