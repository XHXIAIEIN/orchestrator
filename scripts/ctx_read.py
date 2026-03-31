"""ctx_read — CLI tool for sub-agents to read from context_store.

Usage:
    python scripts/ctx_read.py --session <id> --key <key>       # Read specific key
    python scripts/ctx_read.py --session <id> --layer <0-3>     # Read all in layer
    python scripts/ctx_read.py --session <id> --list            # List available keys
    python scripts/ctx_read.py --session <id> --key <k> --budget <N>  # Budget-limited read
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.events_db import EventsDB

_DEFAULT_DB = str(Path(__file__).parent.parent / "data" / "events.db")


def main():
    parser = argparse.ArgumentParser(description="Read context from context_store")
    parser.add_argument("--session", required=True, help="Session ID")
    parser.add_argument("--key", help="Specific context key to read")
    parser.add_argument("--layer", type=int, help="Read all entries in layer (0-3)")
    parser.add_argument("--list", action="store_true", help="List available keys")
    parser.add_argument("--budget", type=int, default=0,
                        help="Max tokens to return (0 = unlimited)")
    parser.add_argument("--db", default=_DEFAULT_DB, help="DB path")
    args = parser.parse_args()

    db = EventsDB(args.db)

    if args.list:
        _list_keys(db, args.session)
    elif args.key:
        _read_key(db, args.session, args.key, args.budget)
    elif args.layer is not None:
        _read_layer(db, args.session, args.layer, args.budget)
    else:
        print("Error: specify --key, --layer, or --list")
        sys.exit(1)


def _list_keys(db: EventsDB, session_id: str):
    rows = db.list_context_keys(session_id)
    if not rows:
        print("No context available for this session.")
        return
    for row in rows:
        print(f"  L{row['layer']} | {row['key']:40s} | ~{row['token_est']} tokens")


def _read_key(db: EventsDB, session_id: str, key: str, budget: int):
    row = db.get_context(session_id, key)
    if not row:
        print(f"Key '{key}' not found in session '{session_id}'.")
        return
    content = row["content"]
    if budget > 0 and row["token_est"] > budget:
        char_limit = budget * 4
        print(f"[BUDGET] Truncating to ~{budget} tokens ({char_limit} chars)")
        print(content[:char_limit])
        print(f"\n[BUDGET] {row['token_est'] - budget} tokens remaining in this entry")
    else:
        print(content)


def _read_layer(db: EventsDB, session_id: str, layer: int, budget: int):
    rows = db.get_context_by_layer(session_id, layer)
    if not rows:
        print(f"No context in Layer {layer} for session '{session_id}'.")
        return
    tokens_used = 0
    for row in rows:
        if budget > 0 and tokens_used + row["token_est"] > budget:
            remaining = len(rows) - rows.index(row)
            print(f"\n[BUDGET] Budget exhausted ({tokens_used}/{budget} tokens). {remaining} entries skipped.")
            break
        print(f"--- {row['key']} ({row['token_est']} tokens) ---")
        print(row["content"])
        print()
        tokens_used += row["token_est"]


if __name__ == "__main__":
    main()
