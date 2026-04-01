#!/bin/bash
# Hook: UserPromptSubmit — detect user corrections, log as learnings
# Scans user prompt for correction signals (CN + EN), writes to learnings DB.
# Outputs context reminder when correction detected so agent can self-correct.
#
# Input:  stdin JSON with { "prompt": "...", ... }
# Output: JSON with additionalContext if correction detected, empty otherwise

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT=$(head -c 65536)

echo "$INPUT" | python3 -c "
import sys, json, os, re

try:
    data = json.load(sys.stdin)
except:
    sys.exit(0)

prompt = data.get('prompt', '') or ''

# Skip very short messages (likely just 'y', 'ok', etc.)
if len(prompt.strip()) < 5:
    sys.exit(0)

# ── Correction signal patterns (Chinese + English) ──
# Each pattern has a weight. Total weight >= 2 = correction detected.
correction_signals = [
    # Chinese — direct corrections
    (r'不对|不是这样|错了|搞错了|弄错了|说错了|写错了', 3),
    (r'别这样|不要这样|不是这个|不是那个', 3),
    (r'应该是|正确的是|其实是', 2),
    (r'我说的是|我要的是|我的意思是', 2),
    (r'重新来|重做|再来一次|重写', 2),
    (r'停[!！]|住手|打住', 3),
    # English — direct corrections
    (r'\bno[,!. ]+(?:that\'s|it\'s|this is)\b', 3),
    (r'\bactually[,. ]', 2),
    (r'\bwrong\b', 2),
    (r'\bnot what I\b', 3),
    (r'\bI (?:said|meant|asked for|wanted)\b', 2),
    (r'\bstop[!. ]', 2),
    (r'\bredo\b|\bstart over\b', 2),
    (r'\bthat\'s not\b', 2),
    (r'\bincorrect\b', 2),
]

total_weight = 0
matched_signals = []
prompt_lower = prompt.lower()

for pattern, weight in correction_signals:
    if re.search(pattern, prompt_lower):
        total_weight += weight
        matched_signals.append(pattern)

# Threshold: need strong signal (weight >= 2) to avoid false positives
if total_weight < 2:
    sys.exit(0)

# ── Log the correction to learnings DB ──
project_root = os.environ.get('ORCHESTRATOR_ROOT', '$PROJECT_ROOT')
sys.path.insert(0, project_root)

# Derive a short pattern key from prompt content
words = re.findall(r'[a-zA-Z\u4e00-\u9fff]+', prompt[:100])[:5]
slug = '-'.join(words)[:40] if words else 'unspecified'
pattern_key = f'correction-{slug}'

try:
    from src.storage.events_db import EventsDB
    from src.governance.audit.learnings import append_learning
    db = EventsDB()
    entry = append_learning(
        pattern_key=pattern_key,
        summary=f'User correction: {prompt[:120]}',
        detail=f'Correction signal weight: {total_weight}\nMatched: {matched_signals}\nFull prompt: {prompt[:500]}',
        area='correction',
        db=db,
    )

    # Check recurrence — if same area has 3+ corrections, suggest promoting to rule
    if entry:
        try:
            from src.governance.audit.learnings import get_promotable_entries
            promotable = [e for e in get_promotable_entries(db, threshold=3) if e.area == 'correction']
            if promotable:
                promo_hint = f'[correction-detector] {len(promotable)} correction(s) hit recurrence threshold (>=3). Consider promoting to permanent rule.'
                print(json.dumps({'additionalContext': f'[correction-detector] User correction detected — logged as {pattern_key}. Reflect on what you did wrong and adjust. {promo_hint}'}))
                sys.exit(0)
        except:
            pass

except Exception:
    # Fallback: write to flat JSONL log
    from datetime import datetime, timezone
    log_dir = os.path.join(project_root, '.remember', 'corrections')
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'prompt': prompt[:500],
        'signals': matched_signals,
        'weight': total_weight,
    }
    log_file = os.path.join(log_dir, datetime.now().strftime('%Y-%m') + '.jsonl')
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

# Output context reminder for the agent
print(json.dumps({'additionalContext': f'[correction-detector] User correction detected — logged as {pattern_key}. Reflect on what you did wrong before proceeding.'}))
" 2>/dev/null

exit 0
