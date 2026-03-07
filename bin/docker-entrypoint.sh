#!/bin/bash
set -e

# Make claude available with full permissions inside the sandbox
export CLAUDE_SKIP_PERMISSIONS=1
alias claude="claude --dangerously-skip-permissions"

# Apply path mappings so collectors can find mounted volumes
export CHROME_HISTORY_ROOT="${CHROME_HISTORY_ROOT:-/chrome-data}"
export CLAUDE_HOME="${ORCHESTRATOR_CLAUDE_HOME:-/claude-home}"
export GIT_REPOS_ROOT="${GIT_REPOS_ROOT:-/git-repos}"

echo "[entrypoint] Starting orchestrator dashboard on port ${PORT:-23714}..."
node /orchestrator/dashboard/server.js &
DASHBOARD_PID=$!

echo "[entrypoint] Starting orchestrator scheduler..."
python3 -m src.scheduler &
SCHEDULER_PID=$!

# Forward signals to child processes
trap "kill $DASHBOARD_PID $SCHEDULER_PID 2>/dev/null; exit" SIGTERM SIGINT

# Wait for either to exit
wait -n $DASHBOARD_PID $SCHEDULER_PID
echo "[entrypoint] A process exited, shutting down..."
kill $DASHBOARD_PID $SCHEDULER_PID 2>/dev/null
