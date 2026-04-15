#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.." || exit 1
# Hook: Stop — Verify Before Reporting (VBR) gate
# Detects when the agent claims task completion but provides no test/verification evidence.
# Stolen from R23 proactive-agent pattern.
#
# Input:  stdin JSON with { "last_assistant_message": "...", ... }
# Output: Warning to stderr if completion claim without verification evidence

INPUT=$(cat)

# Extract last assistant message
LAST_MSG=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('last_assistant_message', '') or '')
except:
    pass
" 2>/dev/null)

# Skip if message is too short
if [ ${#LAST_MSG} -lt 10 ]; then
    exit 0
fi

echo "$LAST_MSG" | python3 -c "
import sys, re

msg = sys.stdin.read()
if not msg.strip():
    sys.exit(0)

msg_lower = msg.lower()

# ── Completion claim patterns (Chinese + English) ──
completion_patterns = [
    r'完成了',
    r'搞定',
    r'已经.*好了',
    r'都.*改好了',
    r'修复完成',
    r'实现完成',
    r'\bdone\b',
    r'\bcompleted\b',
    r'\bfixed\b',
    r'\bfinished\b',
    r'\ball set\b',
    r'that should work',
]

# ── Verification evidence patterns (Chinese + English) ──
verification_patterns = [
    r'测试通过',
    r'验证.*通过',
    r'确认.*正常',
    r'运行.*成功',
    r'test passed',
    r'\bverified\b',
    r'\bconfirmed\b',
    r'output shows',
    r'\bsuccessfully\b',
    r'✓',
    r'✅',
]

has_completion = any(re.search(p, msg_lower) for p in completion_patterns)
has_verification = any(re.search(p, msg) for p in verification_patterns)

if has_completion and not has_verification:
    print('[VBR] Completion claim without verification evidence. Run tests or verify before declaring done.', file=sys.stderr)
" 2>/dev/null

exit 0
