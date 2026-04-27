#!/bin/bash
# Stop hook: P0-1 Turn-Cadence Gate
# Reads per-session turn counter; fires [DANGER] injection at thresholds 7, 10, 35.
# Priority when thresholds coincide: 35 > 10 > 7.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$SCRIPT_DIR/state"

# Read session identifier
SID="${SESSION_ID:-}"
if [ -z "$SID" ]; then
    # No session ID in env — cannot determine turn; pass through
    exit 0
fi

STATE_FILE="$STATE_DIR/turn-${SID}.txt"
if [ ! -f "$STATE_FILE" ]; then
    # No counter file — first session, pass through
    exit 0
fi

TURN=$(cat "$STATE_FILE" 2>/dev/null | tr -d '[:space:]')
if ! [[ "$TURN" =~ ^[0-9]+$ ]] || [ "$TURN" -eq 0 ]; then
    exit 0
fi

# Evaluate thresholds — priority: 35 > 10 > 7
if [ $(( TURN % 35 )) -eq 0 ]; then
    printf '{"decision":"block","reason":"[DANGER: TURN %s] 必须调用 ask_user 报告当前状态后才能继续。"}\n' "$TURN"
    exit 1
elif [ $(( TURN % 10 )) -eq 0 ]; then
    printf '{"decision":"block","reason":"[DANGER: TURN %s] 重新读取 boot.md 和当前任务 SKILL.md，更新 working memory。"}\n' "$TURN"
    exit 1
elif [ $(( TURN % 7 )) -eq 0 ]; then
    printf '{"decision":"block","reason":"[DANGER: TURN %s] 禁止无效重试——切换策略或换工具。"}\n' "$TURN"
    exit 1
fi

exit 0
