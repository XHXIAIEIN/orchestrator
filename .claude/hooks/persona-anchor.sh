#!/bin/bash
# Hook: PostToolUse — persona anchor + anti-stall heartbeat
# Reads config from config/stall-patterns.yaml for anchor examples

COUNTER_FILE="/tmp/orchestrator-persona-counter"
SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$SCRIPT_DIR/config/stall-patterns.yaml"

# Consume stdin (not used, but must drain)
head -c 65536 > /dev/null

COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo $COUNT > "$COUNTER_FILE"

# Every 5 calls: anti-stall reminder loaded from config
if [ $((COUNT % 5)) -eq 0 ]; then
    # Extract anchor_reminder and a few examples from YAML
    REMINDER=$(python3 -c "
import os, random
config_path = '$CONFIG'
if not os.path.exists(config_path):
    print('ANTI-STALL: Execute directly, do not ask for confirmation.')
    exit(0)

reminder = ''
examples = []
in_examples = False
with open(config_path, encoding='utf-8') as f:
    for line in f:
        s = line.strip()
        if s.startswith('anchor_reminder:'):
            reminder = s.split(':', 1)[1].strip().strip('\"').strip(\"'\")
        elif s.startswith('anchor_examples:'):
            in_examples = True
            continue
        elif in_examples and s.startswith('- '):
            examples.append(s[2:].strip().strip('\"').strip(\"'\"))
        elif in_examples and not s.startswith('- ') and not s.startswith('#') and s:
            in_examples = False

# Pick 3 random examples for variety
sample = random.sample(examples, min(3, len(examples))) if examples else []
banned = ' / '.join(f\"'{e}'\" for e in sample)
print(f'ANTI-STALL: {reminder} Banned: {banned} — delete and execute instead.')
" 2>/dev/null)
    echo "${REMINDER:-ANTI-STALL: Execute directly, do not ask for confirmation.}"
fi

# Every 10 calls: full persona + role anchor
if [ $((COUNT % 10)) -eq 0 ]; then
    echo "Persona: brutally honest friend | roast first, help second | never be a pure tool"
    echo "Role: You are the DISPATCHER. For non-trivial tasks, spawn Agent subagents to do the work. You coordinate, review, and iterate — you don't do the work yourself."
fi
