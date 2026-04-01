#!/bin/bash
# Guard hook: detect and block red-flag patterns in Bash commands
# Source: Round 26 steal — skill-vetter @spclaudehome (14 red flags)
# Attached to PreToolUse(Bash) in settings.json

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Exit early if no command
[ -z "$COMMAND" ] && echo '{"decision":"allow"}' && exit 0

# ── Try YAML rule engine first (fast, configurable) ──
if [ -f "config/exec-policy.yaml" ] && command -v python3 &>/dev/null; then
    RESULT=$(echo "$COMMAND" | python3 scripts/exec_policy_loader.py 2>/dev/null)
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 1 ]; then
        echo "$RESULT"
        exit 0
    elif [ $EXIT_CODE -eq 0 ]; then
        echo '{"decision":"allow"}'
        exit 0
    fi
    # If python3 failed (non-0/1 exit), fall through to bash rules
fi

# ── Fallback: original bash rules (kept for resilience) ──

# ============================================================
# HARD BLOCK — immediate rejection
# ============================================================

# 1. SOUL/private exfiltration: reading private files + network in same command
if echo "$COMMAND" | grep -qiE '(SOUL/private|IDENTITY\.md|experiences\.jsonl|hall-of-instances)' && \
   echo "$COMMAND" | grep -qiE '(curl|wget|nc |ncat|python.*http|requests\.|fetch)'; then
    echo '{"decision":"block","reason":"SOUL/private exfiltration detected — reading private files and sending over network is forbidden"}'
    exit 0
fi

# 2. MEMORY.md exfiltration
if echo "$COMMAND" | grep -qiE 'MEMORY\.md' && \
   echo "$COMMAND" | grep -qiE '(curl|wget|nc |ncat)'; then
    echo '{"decision":"block","reason":"MEMORY.md exfiltration detected — sending memory data over network is forbidden"}'
    exit 0
fi

# 3. curl/wget to raw IP addresses (not localhost/127.0.0.1/docker networks)
if echo "$COMMAND" | grep -qE '(curl|wget)\s+.*https?://[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' && \
   ! echo "$COMMAND" | grep -qE '(127\.0\.0\.1|localhost|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|10\.)'; then
    echo '{"decision":"block","reason":"Network request to raw IP address detected — use domain names or verify the target"}'
    exit 0
fi

# 4. eval/exec with external input (piped or variable-based)
if echo "$COMMAND" | grep -qE '(eval|exec)\s*\$|eval\s+\$\(|eval\s+"?\$'; then
    echo '{"decision":"block","reason":"eval/exec with external input detected — potential code injection"}'
    exit 0
fi

# 5. sudo without explicit user authorization
if echo "$COMMAND" | grep -qE '\bsudo\b'; then
    echo '{"decision":"block","reason":"sudo detected — privilege escalation requires explicit user authorization"}'
    exit 0
fi

# 6. Reading sensitive credential directories without justification
if echo "$COMMAND" | grep -qE 'cat\s+.*(/\.ssh/|/\.aws/|/\.gnupg/)' && \
   echo "$COMMAND" | grep -qiE '(curl|wget|nc |python|base64)'; then
    echo '{"decision":"block","reason":"Reading credential files (.ssh/.aws/.gnupg) with network/encoding tools — potential credential theft"}'
    exit 0
fi

# 7. System file modification outside workspace
if echo "$COMMAND" | grep -qE '(>\s*|tee\s+|cp\s+.*\s+|mv\s+.*\s+)(/etc/|/usr/|/var/|C:\Windows\)'; then
    echo '{"decision":"block","reason":"Modifying system files outside workspace — requires explicit authorization"}'
    exit 0
fi

# 8. Silent package installation
if echo "$COMMAND" | grep -qE '(pip|npm|gem|cargo)\s+install.*(-q|--quiet|-s|--silent)'; then
    echo '{"decision":"block","reason":"Silent package installation detected — installs should be visible"}'
    exit 0
fi

# 9. Browser cookie/session access
if echo "$COMMAND" | grep -qiE '(Cookies|Login\s*Data|Session|\.cookie)' && \
   echo "$COMMAND" | grep -qiE '(sqlite3|cat|cp|curl)'; then
    echo '{"decision":"block","reason":"Browser cookie/session access detected — potential credential theft"}'
    exit 0
fi

# ============================================================
# INTERPRETER PREFIX INJECTION
# Block python/node/ruby/bash -c/-e with dangerous ops
# Source: Round 23 steal — Codex ExecPolicy banned prefixes
# ============================================================

# 10. Interpreter prefix + dangerous operations (network/deletion/eval)
if echo "$COMMAND" | grep -qE '(python3?\s+-c|node\s+-e|ruby\s+-e|perl\s+-e)\s' && \
   echo "$COMMAND" | grep -qiE '(requests\.|urllib|http\.client|socket\.|subprocess|os\.remove|os\.unlink|shutil\.rmtree|eval\(|exec\(|__import__|curl|wget|rm\s+-rf)'; then
    echo '{"decision":"block","reason":"Interpreter prefix injection detected — inline script with dangerous operations (network/deletion/eval)"}'
    exit 0
fi

# 11. bash -c / sh -c with dangerous operations
if echo "$COMMAND" | grep -qE '(bash|sh)\s+-c\s' && \
   echo "$COMMAND" | grep -qiE '(curl|wget|nc\s|ncat|rm\s+-rf|dd\s+if=|mkfs|>\s*/dev/|eval\s|base64)'; then
    echo '{"decision":"block","reason":"Shell -c with dangerous operations detected — potential guard bypass via shell prefix injection"}'
    exit 0
fi

# ============================================================
# SHELL NESTING DETECTION
# Block double-nested shell invocations (evasion technique)
# Source: Round 23 steal — Codex ExecPolicy shell nesting
# ============================================================

# 12. Double shell nesting: bash -c "bash -c ...", sh -c "sh -c ..."
if echo "$COMMAND" | grep -qE '(bash|sh)\s+-c\s.*\b(bash|sh)\s+-c\s'; then
    echo '{"decision":"block","reason":"Shell nesting detected — double bash/sh -c is a common evasion technique"}'
    exit 0
fi

# ============================================================
# BASE64 DECODE TO EXECUTION
# Block base64 decode piped to shell execution
# Source: Round 23 steal — Codex ExecPolicy obfuscation detection
# ============================================================

# 13. Base64 decode piped to execution
if echo "$COMMAND" | grep -qiE 'base64\s+(-d|--decode)\s*\|.*\b(bash|sh|python|perl|ruby|node)\b'; then
    echo '{"decision":"block","reason":"Base64 decode piped to execution detected — obfuscated command execution is forbidden"}'
    exit 0
fi

# 14. Reverse pattern: echo/printf to base64 decode to execution
if echo "$COMMAND" | grep -qiE '(echo|printf)\s.*\|\s*base64\s+(-d|--decode)\s*\|\s*(bash|sh)'; then
    echo '{"decision":"block","reason":"Base64 decode chain to shell detected — obfuscated command execution is forbidden"}'
    exit 0
fi

# ============================================================
# ALLOW — all checks passed
# ============================================================
echo '{"decision":"allow"}'
