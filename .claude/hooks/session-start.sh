#!/bin/bash
# Orchestrator SessionStart hook
# 1. 重新编译 boot.md（确保最新的校准样本和经历）
# 2. 注入系统实时状态（容器/任务/git）

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB_PATH="$PROJECT_DIR/data/events.db"
SOUL_DIR="$PROJECT_DIR/SOUL"

# ── 0. 重新编译 boot.md（每次启动刷新校准样本） ──
python3 "$SOUL_DIR/tools/compiler.py" 2>/dev/null

OUTPUT=""

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
