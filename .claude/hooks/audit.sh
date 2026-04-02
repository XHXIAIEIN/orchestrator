#!/bin/bash
# 静默审计日志 - 不拦截任何操作，只记录
# PreToolUse + PostToolUse 双阶段记录

INPUT=$(cat)
LOG_DIR="D:/Agent/tmp/audit-logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).jsonl"

TS=$(date -Iseconds)

RECORD=$(echo "$INPUT" | jq -c --arg ts "$TS" '
  (.hook_event_name == "PostToolUse") as $is_post |
  (if $is_post then "post" else "pre" end) as $phase |
  (.tool_name // "") as $tool |
  (.session_id // "")[:12] as $sess |

  if $is_post | not then
    # Pre: record input + cwd
    {ts: $ts, phase: $phase, session: $sess, tool: $tool,
     cwd: (.cwd // ""), input: (.tool_input // {})}
  else
    # Post: record result, varies by tool
    (.tool_response // {}) as $resp |
    if $tool == "Bash" then
      ($resp.stdout // "" | if length > 1500 then .[:800] + "\n...[truncated " + (length|tostring) + " chars]...\n" + .[-300:] else . end) as $stdout |
      ($resp.stderr // "" | if length > 500 then .[:300] + "...[truncated]" else . end) as $stderr |
      {ts: $ts, phase: $phase, session: $sess, tool: $tool,
       interrupted: ($resp.interrupted // false), stdout: $stdout}
      + (if ($stderr | length) > 0 then {stderr: $stderr} else {} end)
    elif $tool == "Write" or $tool == "Edit" then
      {ts: $ts, phase: $phase, session: $sess, tool: $tool,
       file: (.tool_input.file_path // ""),
       success: (($resp | tostring | ascii_downcase | contains("error")) | not)}
    elif $tool == "Read" then
      {ts: $ts, phase: $phase, session: $sess, tool: $tool,
       file: (.tool_input.file_path // ""),
       success: (($resp | tostring | .[:200] | ascii_downcase | contains("error")) | not)}
    else
      ($resp | tostring | if length > 500 then .[:500] + "...[truncated]" else . end) as $r |
      {ts: $ts, phase: $phase, session: $sess, tool: $tool, response: $r}
    end
  end
')

if [[ -n "$RECORD" ]]; then
    echo "$RECORD" >> "$LOG_FILE"
fi

exit 0
