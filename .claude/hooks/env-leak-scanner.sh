#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Env Leak Scanner — Detects commands that could expose sensitive environment variables
# Inspired by Archon's env-leak-scanner.ts (R47 steal)
#
# Architecture: Single jq parse → pattern matching against known leak vectors
# Runs on PreToolUse for Bash|PowerShell commands

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Only check Bash and PowerShell
case "$TOOL_NAME" in
    Bash|PowerShell) ;;
    *) exit 0 ;;
esac

# === Sensitive env var names (Archon's SENSITIVE_KEYS list + ours) ===
SENSITIVE_VARS='ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|CLAUDE_API_KEY|CLAUDE_CODE_OAUTH_TOKEN|OPENAI_API_KEY|CODEX_API_KEY|GEMINI_API_KEY|GH_TOKEN|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|AZURE_.*KEY|DATABASE_URL|POSTGRES_PASSWORD|MYSQL_PASSWORD|REDIS_PASSWORD|TELEGRAM_BOT_TOKEN|SLACK_BOT_TOKEN|DISCORD_TOKEN|QDRANT_API_KEY|HF_TOKEN'

# === Pattern 1: Commands that dump ALL env vars ===
if echo "$COMMAND" | grep -qiE '^\s*(env|printenv|export -p)\s*$'; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] Dumping all env vars exposes secrets. Use specific var: echo \$VAR_NAME\"}"
    exit 0
fi

# PowerShell: Get-ChildItem Env: or ls Env: or dir Env:
if echo "$COMMAND" | grep -qiE '(Get-ChildItem|ls|dir|gci)\s+(Env:|env:)\s*$'; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] Listing all env vars exposes secrets. Use \$env:VAR_NAME instead\"}"
    exit 0
fi

# === Pattern 2: Echo/print of specific sensitive vars ===
if echo "$COMMAND" | grep -qiE "(echo|printf|Write-Output|Write-Host|cat.*<<<).*[\$]($SENSITIVE_VARS)"; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] Printing sensitive env var to output. This could leak credentials.\"}"
    exit 0
fi

# PowerShell $env:SECRET
if echo "$COMMAND" | grep -qiE "(echo|Write-Output|Write-Host).*\\\$env:($SENSITIVE_VARS)"; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] Printing sensitive env var to output. This could leak credentials.\"}"
    exit 0
fi

# === Pattern 3: Cat/reading .env files (auto-load risk) ===
if echo "$COMMAND" | grep -qiE "cat\s+.*\.env(\s|$|\b)"; then
    echo "{\"decision\":\"ask\",\"reason\":\"[ENV-LEAK] Reading .env file may expose secrets in output\"}"
    exit 0
fi

# === Pattern 4: env vars embedded in curl/wget URLs (credential in URL) ===
if echo "$COMMAND" | grep -qiE "curl.*[\$]($SENSITIVE_VARS)|wget.*[\$]($SENSITIVE_VARS)"; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] Sending sensitive env var in HTTP request\"}"
    exit 0
fi

# === Pattern 5: set command on Windows (dumps all vars) ===
if [[ "$TOOL_NAME" == "Bash" ]] && echo "$COMMAND" | grep -qE '^\s*set\s*$'; then
    echo "{\"decision\":\"block\",\"reason\":\"[ENV-LEAK] 'set' dumps all vars including secrets. Use echo \$VAR_NAME for specific vars\"}"
    exit 0
fi

exit 0
