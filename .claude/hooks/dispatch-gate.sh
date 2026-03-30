#!/bin/bash
# Hook: PreToolUse(Agent) — force governance pipeline for dispatched work
# When Orchestrator spawns an Agent subagent, remind it to use dispatch.py instead
#
# This hook fires on every Agent tool call and injects a reminder.
# It does NOT block — it adds context that the governance pipeline should be used.

echo "DISPATCH GATE: You are Orchestrator. For non-trivial tasks, use 'python scripts/dispatch.py \"<task>\" --wait' to dispatch through the real Governor pipeline (Scrutinizer → Dispatcher → Executor). Do NOT manually brief agents with hand-written prompts."
