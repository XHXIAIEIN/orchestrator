#!/bin/bash
# Hook: PostToolUse(Bash) — detect failures + pressure escalation engine
# Source: error-detector.sh (original) + tanweai/pua failure-detector.sh (Round 35 steal)
#
# Two responsibilities:
# 1. Log errors to learnings DB (original behavior)
# 2. Track consecutive failure count → escalate methodology pressure (stolen from PUA)
#
# Escalation levels (deterministic, not LLM-judged):
#   < 2 consecutive failures: silent (just log)
#   = 2: L1 — "switch to fundamentally different approach"
#   = 3: L2 — mandatory hypothesis mode + methodology suggestion
#   = 4: L3 — full diagnostic checklist
#   >= 5: L4 — forced methodology switch, fallback chain
#
# State files:
#   /tmp/orchestrator-failure-count   — consecutive failure counter
#   /tmp/orchestrator-failure-session — session isolation key
#
# Input:  stdin JSON with tool_input + tool_result
# Output: log message + escalation text if threshold hit

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FAILURE_COUNT_FILE="/tmp/orchestrator-failure-count"
FAILURE_SESSION_FILE="/tmp/orchestrator-failure-session"

# Session isolation: reset counter on new session
CURRENT_SESSION="${CLAUDE_SESSION_ID:-$$}"
STORED_SESSION=$(cat "$FAILURE_SESSION_FILE" 2>/dev/null || echo "")
if [ "$CURRENT_SESSION" != "$STORED_SESSION" ]; then
    echo 0 > "$FAILURE_COUNT_FILE"
    echo "$CURRENT_SESSION" > "$FAILURE_SESSION_FILE"
fi

INPUT=$(head -c 65536)

# Run Python inline — extract, classify, log, and escalate in one pass
echo "$INPUT" | python3 -c "
import sys, json, os, re
from datetime import datetime, timezone

try:
    data = json.load(sys.stdin)
except:
    sys.exit(0)

tool_input = data.get('tool_input', {})
tool_result = data.get('tool_result', {})

command = tool_input.get('command', '')
exit_code = tool_result.get('exitCode', tool_result.get('exit_code', 0))
stdout = tool_result.get('stdout', '') or ''
stderr = tool_result.get('stderr', '') or ''

count_file = '$FAILURE_COUNT_FILE'

# ── Success path: reset counter, exit silently ──
if not exit_code or exit_code == 0:
    try:
        with open(count_file, 'w') as f:
            f.write('0')
    except:
        pass
    sys.exit(0)

# ── Failure path ──

# Skip trivial / expected failures (existence checks, search no-match, git info)
skip_patterns = [
    r'^(test|which|command -v|type|hash)\b',
    r'^(grep|rg|find)\b',
    r'^git\s+(diff|status|log)\b',
    r'^\[',
    r'^ls\b',
]
cmd_stripped = command.strip()
for pat in skip_patterns:
    if re.match(pat, cmd_stripped):
        sys.exit(0)

# Extract last meaningful error lines
error_output = stderr.strip() or stdout.strip()
error_lines = error_output.split('\n')[-5:]
error_summary = '\n'.join(error_lines)[:300]

if not error_summary.strip():
    sys.exit(0)

# ── Increment consecutive failure counter ──
try:
    count = int(open(count_file).read().strip())
except:
    count = 0
count += 1
try:
    with open(count_file, 'w') as f:
        f.write(str(count))
except:
    pass

# ── Log to learnings DB (original behavior) ──
cmd_words = cmd_stripped.split()[:3]
pattern_key = '-'.join(w for w in cmd_words if not w.startswith('-') and not w.startswith('/'))[:40]
pattern_key = re.sub(r'[^a-zA-Z0-9_-]', '', pattern_key) or 'unknown-cmd'
pattern_key = f'err-{pattern_key}'

project_root = os.environ.get('ORCHESTRATOR_ROOT', '$PROJECT_ROOT')
sys.path.insert(0, project_root)

try:
    from src.storage.events_db import EventsDB
    from src.governance.audit.learnings import append_error
    db = EventsDB()
    append_error(
        pattern_key=pattern_key,
        summary=f'Command failed (exit {exit_code}): {command[:100]}',
        detail=f'Exit code: {exit_code}\nCommand: {command[:200]}\nError:\n{error_summary}',
        area='cli',
        db=db,
    )
except Exception:
    # Fallback: write to flat JSONL log
    log_dir = os.path.join(project_root, '.remember', 'errors')
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'tool': 'Bash',
        'command': command[:200],
        'exit_code': exit_code,
        'error_summary': error_summary,
    }
    log_file = os.path.join(log_dir, datetime.now().strftime('%Y-%m') + '.jsonl')
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

# ── Pressure Escalation (stolen from PUA failure-detector.sh) ──
# Deterministic: counter drives level, not LLM judgment.
output_lines = [f'[error-detector] exit {exit_code} | {pattern_key} | consecutive: {count}']

if count == 2:
    # L1: gentle nudge
    output_lines.append('')
    output_lines.append('[ESCALATION L1] 2 consecutive failures.')
    output_lines.append('You are repeating a failing approach. Switch to a FUNDAMENTALLY DIFFERENT method.')
    output_lines.append('Ask yourself: am I debugging the REAL problem, or a symptom?')

elif count == 3:
    # L2: mandatory hypothesis mode + methodology suggestion
    output_lines.append('')
    output_lines.append('[ESCALATION L2] 3 consecutive failures. Mandatory diagnostic pause.')
    output_lines.append('STOP coding. Execute these 5 steps before your next attempt:')
    output_lines.append('  1. State the EXACT error (copy-paste, not paraphrase)')
    output_lines.append('  2. List 2-3 possible root causes')
    output_lines.append('  3. For EACH cause, describe a verification step (no code changes)')
    output_lines.append('  4. Execute the verification steps')
    output_lines.append('  5. Only fix the CONFIRMED cause')
    output_lines.append('')
    output_lines.append('Methodology suggestion based on failure pattern:')
    output_lines.append('  - Same error repeating → you misidentified the root cause. Re-diagnose.')
    output_lines.append('  - Different errors each time → you are changing too much per attempt. Isolate ONE variable.')
    output_lines.append('  - Error is in a dependency → stop fixing YOUR code. Read the dependency docs.')

elif count == 4:
    # L3: full diagnostic checklist
    output_lines.append('')
    output_lines.append('[ESCALATION L3] 4 consecutive failures. Full diagnostic required.')
    output_lines.append('Before your next command, answer ALL of these:')
    output_lines.append('  1. What is the EXACT error message? (paste it)')
    output_lines.append('  2. What have you tried so far? (list each attempt)')
    output_lines.append('  3. Why did each attempt fail?')
    output_lines.append('  4. What assumption are you making that might be wrong?')
    output_lines.append('  5. Have you read the relevant source code / docs? Which files?')
    output_lines.append('  6. Is there a simpler way to achieve the same goal?')
    output_lines.append('  7. Should you ask the user for clarification instead of guessing?')

elif count >= 5:
    # L4: forced methodology switch
    output_lines.append('')
    output_lines.append(f'[ESCALATION L4] {count} consecutive failures. Forced methodology switch.')
    output_lines.append('Your current approach is not working. You MUST do one of these:')
    output_lines.append('  A. INVERT: Instead of making it work, ask why it CAN\\'T work. What constraint are you violating?')
    output_lines.append('  B. SIMPLIFY: Strip the problem to its absolute minimum. Can you make a 3-line version work?')
    output_lines.append('  C. SEARCH: Read docs, grep the codebase, or web search. You are likely missing information.')
    output_lines.append('  D. ESCALATE: Tell the user what you\\'ve tried and where you\\'re stuck. Asking for help is not failure.')
    output_lines.append('')
    output_lines.append('Continuing to retry the same approach class is PROHIBITED at L4.')

print('\n'.join(output_lines))
" 2>/dev/null

exit 0
