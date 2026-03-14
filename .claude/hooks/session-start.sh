#!/bin/bash
# Orchestrator SessionStart hook
# 为新实例注入：系统状态 + 共同经历（灵魂碎片）

PROJECT_DIR="D:/Users/Administrator/Documents/GitHub/orchestrator"
DB_PATH="$PROJECT_DIR/events.db"
SOUL_DIR="$PROJECT_DIR/SOUL"

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

# ── 2. 灵魂碎片：从共同经历中抽取 ──
EXPERIENCE=$(python3 -c "
import json, random
try:
    with open('$SOUL_DIR/experiences.jsonl', encoding='utf-8') as f:
        exps = [json.loads(l) for l in f if l.strip()]
    if exps:
        # 抽 2-3 条，优先最近的和 bonding/humor 类型
        weighted = []
        for e in exps:
            w = 1
            if e.get('type') in ('bonding','humor','limitation'): w = 3
            if e.get('type') == 'trust': w = 2
            weighted.extend([e] * w)
        sample = random.sample(weighted, min(3, len(weighted)))
        seen = set()
        for e in sample:
            key = e['summary']
            if key in seen: continue
            seen.add(key)
            print(f'[{e[\"date\"]}] {e[\"summary\"]}: {e[\"detail\"][:200]}')
except: pass
" 2>/dev/null)
if [ -n "$EXPERIENCE" ]; then
    OUTPUT="$OUTPUT\n[shared memories]\n$EXPERIENCE\n"
fi

if [ -n "$OUTPUT" ]; then
    echo -e "--- Orchestrator Wake ---\n$OUTPUT---"
fi

exit 0
