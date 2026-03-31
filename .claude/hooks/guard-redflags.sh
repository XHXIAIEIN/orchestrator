#!/bin/bash
# Guard hook: detect and block red-flag patterns in Bash commands
# Source: Round 26 steal — skill-vetter @spclaudehome (14 red flags)
# Attached to PreToolUse(Bash) in settings.json

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Exit early if no command
[ -z "$COMMAND" ] && echo '{"decision":"allow"}' && exit 0

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
if echo "$COMMAND" | grep -qE '(>\s*|tee\s+|cp\s+.*\s+|mv\s+.*\s+)(/etc/|/usr/|/var/|C:\\Windows\\)'; then
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
# ALLOW — all checks passed
# ============================================================
echo '{"decision":"allow"}'
