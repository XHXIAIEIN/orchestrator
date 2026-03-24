#!/bin/bash
# Session Stop hook — lightweight, non-blocking experience logger
# Reads last assistant message from stdin, spawns background process to evaluate and store

SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB_PATH="$SCRIPT_DIR/data/events.db"
JSONL_PATH="$SCRIPT_DIR/SOUL/private/experiences.jsonl"
TODAY=$(date +%Y-%m-%d)

# Read stdin (hook arguments JSON)
INPUT=$(cat)

# Extract last assistant message (truncated to 500 chars for efficiency)
LAST_MSG=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    msg = d.get('last_assistant_message', '') or ''
    print(msg[:500])
except: pass
" 2>/dev/null)

# Skip if message is too short (trivial conversation)
if [ ${#LAST_MSG} -lt 50 ]; then
    exit 0
fi

# Background: use a lightweight LLM call via Ollama (local, fast) or skip if unavailable
(
    OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

    # Try local Ollama for fast classification
    RESULT=$(curl -s --max-time 10 "$OLLAMA_HOST/api/generate" \
        -d "{\"model\":\"qwen3:1.7b\",\"prompt\":\"Classify if this AI conversation excerpt contains a memorable shared experience worth recording. Types: bonding, humor, conflict, trust, discovery, limitation, milestone, lesson. If yes, respond with JSON: {\\\"type\\\":\\\"TYPE\\\",\\\"summary\\\":\\\"short title\\\",\\\"detail\\\":\\\"1 sentence\\\"}. If no (pure technical ops, trivial), respond: {\\\"skip\\\":true}. Excerpt: ${LAST_MSG//\"/\\\"}\" ,\"stream\":false,\"options\":{\"temperature\":0.3}}" 2>/dev/null \
        | python3 -c "import sys,json;r=json.load(sys.stdin);print(r.get('response',''))" 2>/dev/null)

    # If Ollama unavailable, skip silently
    if [ -z "$RESULT" ]; then
        exit 0
    fi

    # Parse result
    python3 -c "
import sys, json, sqlite3, os

raw = '''$RESULT'''
# Extract JSON from response
import re
m = re.search(r'\{[^}]+\}', raw)
if not m:
    sys.exit(0)

try:
    data = json.loads(m.group())
except:
    sys.exit(0)

if data.get('skip'):
    sys.exit(0)

etype = data.get('type', 'discovery')
summary = data.get('summary', '')[:100]
detail = data.get('detail', '')[:200]
today = '$TODAY'
db_path = '$DB_PATH'
jsonl_path = '$JSONL_PATH'

if not summary:
    sys.exit(0)

# Write to DB
try:
    conn = sqlite3.connect(db_path)
    conn.execute(
        'INSERT OR IGNORE INTO experiences (date, type, summary, detail, created_at) VALUES (?, ?, ?, ?, datetime(\"now\"))',
        (today, etype, summary, detail)
    )
    conn.commit()
    conn.close()
except: pass

# Append to jsonl backup
try:
    entry = json.dumps({'date': today, 'type': etype, 'summary': summary, 'detail': detail}, ensure_ascii=False)
    with open(jsonl_path, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')
except: pass
" 2>/dev/null
) &

# Return immediately — background process handles the rest
exit 0
