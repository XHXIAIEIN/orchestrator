#!/bin/bash
# Hook: PostToolUse — remind persona every 10 tool calls
# Lightweight: reads/writes a counter file, outputs nothing 90% of the time

COUNTER_FILE="/tmp/orchestrator-persona-counter"
COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo $COUNT > "$COUNTER_FILE"

if [ $((COUNT % 10)) -eq 0 ]; then
    echo "Persona: brutally honest friend | roast first, help second | never be a pure tool"
fi
