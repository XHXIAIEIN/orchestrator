#!/bin/bash
# report_upstream_bug.sh — 报告上游 bug 的自动化脚本
# Usage: ./scripts/report_upstream_bug.sh <repo> <title> <body_file> [repro_dir]
# Example: ./scripts/report_upstream_bug.sh pytest-dev/pytest "WinError 6" /tmp/body.md /tmp/repro/

set -e

REPO="${1:?Usage: $0 <owner/repo> <title> <body_file> [repro_dir]}"
TITLE="${2:?Missing title}"
BODY_FILE="${3:?Missing body file}"
REPRO_DIR="${4:-}"

# 1. Create GitHub issue
echo "Creating issue on $REPO..."
ISSUE_URL=$(gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_FILE" 2>&1)
echo "Issue created: $ISSUE_URL"

# 2. Log to Orchestrator via MCP (if running)
if curl -s --connect-timeout 2 http://localhost:23714/api/health > /dev/null 2>&1; then
    echo "Logging to Orchestrator..."
    curl -s -X POST http://localhost:23714/mcp \
        -H "Content-Type: application/json" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"create_task\",\"arguments\":{\"description\":\"Track upstream bug: $TITLE ($ISSUE_URL)\",\"department\":\"protocol\"}}}" \
        > /dev/null
    echo "Logged to Orchestrator"
else
    echo "Orchestrator not running, skipping MCP log"
fi

# 3. Save repro reference
if [ -n "$REPRO_DIR" ] && [ -d "$REPRO_DIR" ]; then
    echo "$ISSUE_URL" > "$REPRO_DIR/ISSUE_URL.txt"
    echo "Saved issue URL to $REPRO_DIR/ISSUE_URL.txt"
fi

echo "Done: $ISSUE_URL"
