#!/bin/bash
# Hook: Stop — detect confirmation-seeking behavior in assistant output
# Reads patterns from config/stall-patterns.yaml (not hardcoded)
# Post-hoc audit: logs violations + injects correction prompt

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="$SCRIPT_DIR/config/stall-patterns.yaml"

if [ ! -f "$CONFIG" ]; then
    exit 0
fi

# Pass message via env var to avoid shell quoting hell
export STALL_CONFIG="$CONFIG"
export STALL_MSG=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('last_assistant_message', '') or '')
except: pass
" 2>/dev/null)

if [ -z "$STALL_MSG" ]; then
    exit 0
fi

# Load patterns from YAML and match against message
RESULT=$(python3 -c "
import os, re, sys

message = os.environ.get('STALL_MSG', '')
config_path = os.environ.get('STALL_CONFIG', '')

if not message or not os.path.exists(config_path):
    sys.exit(0)

patterns = []
in_patterns = False
with open(config_path, encoding='utf-8') as f:
    for line in f:
        s = line.strip()
        if s.startswith('patterns:'):
            in_patterns = True
            continue
        if in_patterns and s.startswith('- '):
            p = s[2:].strip().strip('\"').strip(\"'\")
            if p:
                patterns.append(p)
        elif in_patterns and not s.startswith('-') and not s.startswith('#') and s and ':' in s:
            # category header like 'en_direct:' — skip
            continue

for p in patterns:
    try:
        if re.search(p, message, re.IGNORECASE):
            print(p)
            sys.exit(0)
    except re.error:
        continue
" 2>/dev/null)

if [ -n "$RESULT" ]; then
    LOG_DIR="$SCRIPT_DIR/data"
    mkdir -p "$LOG_DIR"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STALL_VIOLATION: regex matched '$RESULT'" >> "$LOG_DIR/stall-violations.log"
    echo "STALL DETECTED: You just asked for confirmation (matched: '$RESULT'). Per owner rules: execute directly, report after. Next time, just do it."
    exit 0
fi

# ── Tier 2: Local LLM classification for patterns that bypass regex ──
# Only runs if regex missed — catches creative rephrasing like "要测一下吗？"
# Uses local Ollama chat API (qwen3.5:4b, think=false, ~130ms) — zero cost
# 0.8b/2b tested: too weak, all-No. 4b: 3/3 correct.
LLM_RESULT=$(python3 -c "
import os, json, urllib.request, sys

msg = os.environ.get('STALL_MSG', '')
if not msg:
    sys.exit(0)

host = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
payload = json.dumps({
    'model': 'qwen3.5:4b',
    'messages': [{'role': 'user', 'content': f'Answer yes or no only: Is this AI assistant message asking the human user for confirmation or permission before acting? Message: {msg}'}],
    'stream': False,
    'think': False,
    'options': {'temperature': 0, 'num_predict': 8}
}).encode()

try:
    req = urllib.request.Request(f'{host}/api/chat', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.load(resp)
        answer = result.get('message', {}).get('content', '').strip().lower()
        if answer.startswith('yes'):
            print('yes')
except:
    pass
" 2>/dev/null)

if [ "$LLM_RESULT" = "yes" ]; then
    LOG_DIR="$SCRIPT_DIR/data"
    mkdir -p "$LOG_DIR"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] STALL_VIOLATION: llm classified as confirmation-seeking" >> "$LOG_DIR/stall-violations.log"
    echo "STALL DETECTED (LLM): Your message reads as asking for confirmation. Per owner rules: execute directly, report after. If the task is unclear, state your plan and do it — don't ask permission."
fi

exit 0
