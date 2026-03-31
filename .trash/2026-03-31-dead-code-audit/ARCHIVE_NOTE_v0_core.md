# v0 Core (db.py + store_collections.py + cli.py + agent.py) — Archived 2026-03-31

Replaced by: storage/events_db.py + gateway/intent.py + Governor pipeline

Valuable ideas worth revisiting:
- ClarificationAgent: 5-round clarification dialogue (IntentGateway only does 1 round)
  → Future: add multi-round clarification as IntentGateway enhancement
- store_collections: Generic Collection/Queue/KeyValue SQLite abstractions
  → Future: if generic KV/Queue needed, reference this implementation

Why not revived: v0 architecture (direct Anthropic API, own DB, own session model)
incompatible with current Governor + Agent SDK + EventsDB stack.
