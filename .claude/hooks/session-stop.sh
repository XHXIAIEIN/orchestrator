#!/bin/bash
# Session Stop hook — git safety + experience logger
# Phase 0: force-save uncommitted work (shell-level, not LLM-dependent)
# Phase 1-3: experience extraction + memory audit (background)

SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB_PATH="$SCRIPT_DIR/data/events.db"
JSONL_PATH="$SCRIPT_DIR/SOUL/private/experiences.jsonl"
TODAY=$(date +%Y-%m-%d)

# ── Phase 0: Git safety net — stash uncommitted changes ──
cd "$SCRIPT_DIR" 2>/dev/null
if git rev-parse --is-inside-work-tree &>/dev/null; then
    DIRTY=$(git status --porcelain 2>/dev/null | grep -v '^\?\?' | head -1)
    UNTRACKED_SRC=$(git status --porcelain 2>/dev/null | grep '^\?\? src/' | head -1)

    if [ -n "$DIRTY" ] || [ -n "$UNTRACKED_SRC" ]; then
        # Stage tracked changes + new src/ files (skip .trash/, tmp/, *.log)
        git add -u 2>/dev/null
        git ls-files --others --exclude-standard -- 'src/' 'scripts/' | xargs -r git add 2>/dev/null

        STAGED=$(git diff --cached --stat 2>/dev/null | tail -1)
        if [ -n "$STAGED" ]; then
            BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
            git commit -m "wip(session-stop): auto-save uncommitted work on ${BRANCH} [$(date '+%H:%M')]" \
                --no-verify 2>/dev/null
        fi
    fi
fi

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
project_dir = '$SCRIPT_DIR'

if not summary:
    sys.exit(0)

# Unified write: DB + JSONL in one call
sys.path.insert(0, project_dir)
try:
    from src.storage.events_db import EventsDB
    db = EventsDB(db_path)
    exp_id = db.add_experience_unified(
        today, etype, summary, detail,
        jsonl_path=jsonl_path
    )
    # Close most recent active session
    active = db.get_active_session()
    if active:
        db.close_session(
            active['session_id'],
            summary=summary,
            topics=[etype],
            experience_ids=[exp_id] if exp_id else []
        )
except:
    # Fallback: direct DB + JSONL (old behavior)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            'INSERT OR IGNORE INTO experiences (date, type, summary, detail, created_at) VALUES (?, ?, ?, ?, datetime(\"now\"))',
            (today, etype, summary, detail)
        )
        conn.commit()
        conn.close()
    except: pass
    try:
        entry = json.dumps({'date': today, 'type': etype, 'summary': summary, 'detail': detail}, ensure_ascii=False)
        with open(jsonl_path, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except: pass
" 2>/dev/null

    # ── Phase 2: 6-type structured memory extraction → structured_memory.db ──
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
try:
    from src.governance.context.memory_extractor import extract_memories
    from src.governance.context.memory_bridge import save_extracted_to_structured_memory
    last_msg = '''${LAST_MSG//\'/\'\\\'\'}'''
    memories = extract_memories(last_msg, use_local=True)
    if memories:
        save_extracted_to_structured_memory(memories)
except Exception:
    pass  # non-critical, fail silently
" 2>/dev/null

    # ── Phase 3: Subconscious memory audit (stolen from letta-ai/claude-subconscious) ──
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
try:
    from SOUL.tools.subconscious import audit, should_curate, curate, AUDIT_LOG_PATH
    import json

    # Always run fast audit
    findings = audit()

    issues = (
        len(findings.get('duplicates', []))
        + len(findings.get('orphan_files', []))
        + len(findings.get('orphan_links', []))
        + len(findings.get('empty_files', []))
    )

    # Log audit results
    with open(str(AUDIT_LOG_PATH), 'a', encoding='utf-8') as f:
        f.write(json.dumps(findings, ensure_ascii=False) + '\n')

    # Curate every 5 sessions or if 3+ issues found
    if should_curate(every_n=5) or issues >= 3:
        curate()

except Exception:
    pass  # non-critical
" 2>/dev/null
) &

# Return immediately — background process handles the rest
exit 0
