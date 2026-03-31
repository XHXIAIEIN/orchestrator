#!/bin/bash
# Hook: PostToolUse(Bash) — detect non-zero exit codes, log errors to learnings DB
# Silent on success. On failure: extract error summary → write structured error entry.
#
# Input:  stdin JSON with tool_input + tool_result
# Output: reminder text if error detected, empty otherwise

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT=$(cat)

# Run Python inline — extract, classify, and log in one pass
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

# Only care about failures
if not exit_code or exit_code == 0:
    sys.exit(0)

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

# Derive a pattern key from the command
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

# Output a short reminder
print(f'[error-detector] Logged: exit {exit_code} | {pattern_key}')
" 2>/dev/null

exit 0
