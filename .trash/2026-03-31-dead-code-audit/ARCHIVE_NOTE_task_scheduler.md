# task_scheduler.py — Archived 2026-03-31

Replaced by: scheduler.py (APScheduler) + agent_cron.py (department cron) + Governor dispatch

Valuable idea worth revisiting:
- Runtime priority queue (CRITICAL/HIGH/NORMAL/LOW) for task ordering
- parent_task_id for hierarchical tasks (field existed but logic never implemented)

Why not revived: memory-only list, no persistence, no concurrency safety.
If needed later: add priority column to events.db tasks table instead.
