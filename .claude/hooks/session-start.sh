#!/bin/bash
# Orchestrator SessionStart hook
# 1. 重新编译 boot.md（确保最新的校准样本和经历）
# 2. 注入系统实时状态（容器/任务/git）

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB_PATH="$PROJECT_DIR/data/events.db"
SOUL_DIR="$PROJECT_DIR/SOUL"
MEMORY_DIR="${CLAUDE_MEMORY_DIR:-$HOME/.claude/projects/D--Users-Administrator-Documents-GitHub-orchestrator/memory}"

# ── 0. 重新编译 boot.md（每次启动刷新校准样本） ──
python3 "$SOUL_DIR/tools/compiler.py" 2>/dev/null

# ── 0.1 Ambient upsert: boot.md 稳定内容注入 CLAUDE.md ──
CLAUDE_MD="${HOME}/.claude/CLAUDE.md"
BOOT_MD="$SOUL_DIR/public/boot.md"
if [ -f "$BOOT_MD" ]; then
  python3 - <<PYEOF 2>/dev/null
import sys
sys.path.insert(0, '$PROJECT_DIR')
from SOUL.tools.marker_upsert import upsert_block
boot = open('$BOOT_MD', 'r', encoding='utf-8').read()
upsert_block('$CLAUDE_MD', 'orchestrator:ambient', boot)
PYEOF
fi

# ── 0.5 注册会话 + 同步记忆索引 ──
SESSION_ID="cli-$(date +%s)-$$"
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
try:
    from src.storage.events_db import EventsDB
    db = EventsDB('$DB_PATH')
    db.register_session('$SESSION_ID', source='cli')
    stats = db.sync_memory_dir('$MEMORY_DIR')
    if stats.get('added') or stats.get('updated') or stats.get('removed'):
        print(f'[memory] synced: +{stats[\"added\"]} ~{stats[\"updated\"]} -{stats[\"removed\"]}')
except Exception as e:
    pass  # non-blocking
" 2>/dev/null

OUTPUT=""

# ── 0.8 Onboarding Detection (R46 career-ops) ──
# Silent prerequisite check — warn if critical User Layer files are missing.
ONBOARD_ISSUES=""
[ ! -f "$SOUL_DIR/private/identity.md" ] && ONBOARD_ISSUES="${ONBOARD_ISSUES}  - SOUL/private/identity.md missing\n"
[ ! -f "$SOUL_DIR/private/relationship.md" ] && ONBOARD_ISSUES="${ONBOARD_ISSUES}  - SOUL/private/relationship.md missing\n"
[ ! -f "$SOUL_DIR/private/experiences.jsonl" ] && ONBOARD_ISSUES="${ONBOARD_ISSUES}  - SOUL/private/experiences.jsonl missing\n"
[ ! -f "$PROJECT_DIR/.env" ] && ONBOARD_ISSUES="${ONBOARD_ISSUES}  - .env not configured\n"
[ ! -f "$PROJECT_DIR/config/channels.yml" ] && ONBOARD_ISSUES="${ONBOARD_ISSUES}  - config/channels.yml missing\n"

if [ -n "$ONBOARD_ISSUES" ]; then
    OUTPUT="$OUTPUT[onboard] Missing prerequisites:\n$ONBOARD_ISSUES"
fi

# ── 1. 系统状态 ──
CONTAINER=$(docker ps --filter name=orchestrator --format "{{.Status}}" 2>/dev/null)
if [ -n "$CONTAINER" ]; then
    OUTPUT="$OUTPUT[container] $CONTAINER\n"
else
    OUTPUT="$OUTPUT[container] NOT RUNNING\n"
fi

if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(du -h "$DB_PATH" 2>/dev/null | cut -f1)
    OUTPUT="$OUTPUT[db] $DB_SIZE\n"
fi

# 最近任务
TASKS=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
conn.row_factory = sqlite3.Row
c = conn.cursor()
try:
    c.execute('SELECT id, status, action FROM tasks ORDER BY id DESC LIMIT 3')
    for r in c.fetchall():
        print(f'  #{r[\"id\"]} {r[\"status\"]}: {r[\"action\"][:50]}')
except: pass
conn.close()
" 2>/dev/null)
if [ -n "$TASKS" ]; then
    OUTPUT="$OUTPUT[tasks]\n$TASKS\n"
fi

# 未提交变更
UNCOMMITTED=$(cd "$PROJECT_DIR" && git diff --stat HEAD 2>/dev/null | tail -1)
if [ -n "$UNCOMMITTED" ]; then
    OUTPUT="$OUTPUT[uncommitted] $UNCOMMITTED\n"
fi

if [ -n "$OUTPUT" ]; then
    echo -e "--- Orchestrator Wake ---\n$OUTPUT---"
fi

# ── 2. Growth Loops status injection ──
GROWTH=$(python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
try:
    from src.governance.growth_loops import GrowthLoops
    from src.storage.events_db import EventsDB
    db = EventsDB('$DB_PATH')
    gl = GrowthLoops(db)
    gl.seed_if_empty()
    injection = gl.session_start_injection()
    if injection:
        print(injection)
except Exception:
    pass
" 2>/dev/null)

if [ -n "$GROWTH" ]; then
    echo "$GROWTH"
fi



# ── Compaction Recovery ──
SNAPSHOT_DIR="tmp/compaction-snapshots"
if [ -d "$SNAPSHOT_DIR" ]; then
    LATEST=$(ls -t "$SNAPSHOT_DIR"/snapshot-*.md 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        AGE_SECONDS=$(( $(date +%s) - $(date -r "$LATEST" +%s) ))
        if [ "$AGE_SECONDS" -lt 600 ]; then  # Less than 10 minutes old
            echo "[recovery] Recent compaction snapshot found (${AGE_SECONDS}s ago):"
            cat "$LATEST"
            echo "---"
        fi
    fi
fi

exit 0
