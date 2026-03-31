#!/bin/bash
# Hook: UserPromptSubmit — conversation-level routing
# Classifies each user prompt and injects Governor dispatch context for task-type messages.
# Non-task messages (chat, dev work, status queries) pass through silently.
#
# Input:  stdin JSON with { "prompt": "...", "cwd": "...", ... }
# Output: JSON with { "additionalContext": "..." } or empty (pass-through)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Run the Python classifier — must complete within timeout
python "$PROJECT_ROOT/scripts/route_prompt.py" 2>/dev/null
