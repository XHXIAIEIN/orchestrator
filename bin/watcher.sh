#!/bin/bash
# watcher.sh — 守护 scheduler 进程，挂掉自动重启

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$SCRIPT_DIR/scheduler.pid"
LOG_FILE="$SCRIPT_DIR/scheduler.log"

start_scheduler() {
    echo "[$(date)] Starting scheduler..." >> "$LOG_FILE"
    cd "$SCRIPT_DIR"
    python3 -m src.scheduler >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "[$(date)] Scheduler started with PID $(cat $PID_FILE)" >> "$LOG_FILE"
}

echo "[$(date)] Watcher started." >> "$LOG_FILE"

while true; do
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "[$(date)] Scheduler (PID $PID) is dead, restarting..." >> "$LOG_FILE"
            start_scheduler
        fi
    else
        start_scheduler
    fi
    sleep 30
done
