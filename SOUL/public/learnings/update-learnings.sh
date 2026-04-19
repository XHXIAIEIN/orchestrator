#!/usr/bin/env bash
set -euo pipefail

# cd to script directory so python3 open() calls work with relative paths
cd "$(dirname "${BASH_SOURCE[0]}")"

DATA_FILE="learnings.json"
TMP_FILE=".learnings.json.tmp"

if [[ $# -lt 1 ]]; then
  echo "Usage:" >&2
  echo "  $0 --session topic=<str> outcome=<pass|fail>" >&2
  echo "  $0 --fix fcode=<F01-F14> description=<str> what_worked=<str>" >&2
  echo "  $0 --decay" >&2
  exit 1
fi

MODE="$1"
shift

# Parse key=value args into an associative array
declare -A KV
for arg in "$@"; do
  key="${arg%%=*}"
  val="${arg#*=}"
  KV["$key"]="$val"
done

case "$MODE" in

  --session)
    TOPIC="${KV[topic]:?'topic is required'}"
    OUTCOME="${KV[outcome]:?'outcome is required'}"
    if [[ "$OUTCOME" != "pass" && "$OUTCOME" != "fail" ]]; then
      echo "outcome must be 'pass' or 'fail'" >&2
      exit 1
    fi
    TODAY="$(date +%Y-%m-%d)"

    python3 - <<PYEOF
import json, os
data_file = 'learnings.json'
tmp_file  = '.learnings.json.tmp'
with open(data_file) as f:
    d = json.load(f)
entry = {'date': '$TODAY', 'topic': '$TOPIC', 'outcome': '$OUTCOME'}
d['sessions'].append(entry)
d['_last_updated'] = '$TODAY'
with open(tmp_file, 'w') as f:
    json.dump(d, f, indent=2)
os.replace(tmp_file, data_file)
n = len(d['sessions'])
print(f'updated learnings.json: sessions now has {n} entries')
PYEOF
    ;;

  --fix)
    FCODE="${KV[fcode]:?'fcode is required'}"
    DESC="${KV[description]:?'description is required'}"
    WHAT_WORKED="${KV[what_worked]:?'what_worked is required'}"
    TODAY="$(date +%Y-%m-%d)"

    python3 - <<PYEOF
import json, os
data_file = 'learnings.json'
tmp_file  = '.learnings.json.tmp'
with open(data_file) as f:
    d = json.load(f)
entry = {
    'date': '$TODAY',
    'fcode': '$FCODE',
    'description': '$DESC',
    'what_worked': '$WHAT_WORKED'
}
d['fix_history'].append(entry)
# trim to last 30
d['fix_history'] = d['fix_history'][-30:]
d['_last_updated'] = '$TODAY'
with open(tmp_file, 'w') as f:
    json.dump(d, f, indent=2)
os.replace(tmp_file, data_file)
n = len(d['fix_history'])
print(f'updated learnings.json: fix_history now has {n} entries')
PYEOF
    ;;

  --decay)
    TODAY="$(date +%Y-%m-%d)"

    python3 - <<PYEOF
import json, os
data_file = 'learnings.json'
tmp_file  = '.learnings.json.tmp'
with open(data_file) as f:
    d = json.load(f)
for sid, stats in d.get('confidence_scores', {}).items():
    if isinstance(stats.get('score_0_to_1'), (int, float)):
        stats['score_0_to_1'] = round(stats['score_0_to_1'] * 0.9, 6)
        stats['last_updated'] = '$TODAY'
d['_last_updated'] = '$TODAY'
with open(tmp_file, 'w') as f:
    json.dump(d, f, indent=2)
os.replace(tmp_file, data_file)
n = len(d.get('confidence_scores', {}))
print(f'updated learnings.json: confidence_scores now has {n} entries (decay applied)')
PYEOF
    ;;

  *)
    echo "Unknown mode: $MODE" >&2
    exit 1
    ;;
esac
