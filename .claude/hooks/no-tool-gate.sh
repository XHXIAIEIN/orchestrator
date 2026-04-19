#!/bin/bash
# Stop hook: P0-2 No-Tool Interception Gate
# Reads last_assistant_message from stdin JSON.
# Blocks if: completion signal detected AND [VERIFY]/VERDICT: token absent.

# Read stdin
INPUT=$(cat)

# Extract last_assistant_message
MSG=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('last_assistant_message', ''))
except:
    print('')
" 2>/dev/null)

# Empty message — nothing to check
if [ -z "$MSG" ]; then
    exit 0
fi

# Case 3: Empty or truncated response (under 10 chars or max_tokens marker)
MSG_LEN=${#MSG}
if [ "$MSG_LEN" -lt 10 ] || echo "$MSG" | grep -qE '\[max_tokens\]|\[truncated\]'; then
    printf '{"decision":"block","reason":"[no-tool-gate] 响应不完整，请重新生成。"}\n'
    exit 1
fi

# Check for bypass tokens first (case-insensitive [VERIFY] and VERDICT:)
HAS_VERIFY=$(echo "$MSG" | grep -iE '\[VERIFY\]|VERDICT:' | head -1)
if [ -n "$HAS_VERIFY" ]; then
    # Bypass token present — allow
    exit 0
fi

# Case 1: Completion signal without verify token
HAS_COMPLETION=$(echo "$MSG" | grep -iE '(任务完成|task complete|完成了|搞定|all done|done\.)' | head -1)
if [ -n "$HAS_COMPLETION" ]; then
    printf '{"decision":"block","reason":"[no-tool-gate] 检测到完成声明但缺少 [VERIFY] 或 VERDICT token。请运行验证命令后再声明完成。"}\n'
    exit 1
fi

# Case 2: Code block without explanation (>200 chars code, <30 chars natural language)
python3 - <<'PYEOF'
import sys, re

msg = sys.stdin.read()

# Extract code block content
code_blocks = re.findall(r'```[\s\S]*?```', msg)
code_len = sum(len(b) for b in code_blocks)

# Natural language = message minus code blocks
natural = re.sub(r'```[\s\S]*?```', '', msg).strip()
natural_len = len(natural)

if code_len > 200 and natural_len < 30:
    print('BLOCK_CASE2')
PYEOF
<<< "$MSG"

CASE2=$(echo "$MSG" | python3 -c "
import sys, re
msg = sys.stdin.read()
code_blocks = re.findall(r'\`\`\`[\s\S]*?\`\`\`', msg)
code_len = sum(len(b) for b in code_blocks)
natural = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', msg).strip()
natural_len = len(natural)
if code_len > 200 and natural_len < 30:
    print('BLOCK')
" 2>/dev/null)

if [ "$CASE2" = "BLOCK" ]; then
    printf '{"decision":"block","reason":"[no-tool-gate] 纯代码块响应缺少说明。请补充 tool call 或说明下一步操作。"}\n'
    exit 1
fi

exit 0
