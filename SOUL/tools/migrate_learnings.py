"""
一次性迁移：.learnings/ markdown → DB learnings 表。

解析 ERRORS.md 和 LEARNINGS.md，upsert 到 DB。
文件版本覆盖 DB 版本（Clawvard 产出更丰富）。
迁移完成后 .learnings/ → .trash/learnings-migrated/

用法：
    python SOUL/tools/migrate_learnings.py              # 执行迁移
    python SOUL/tools/migrate_learnings.py --dry-run    # 预览不写入
"""
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LEARNINGS_DIR = PROJECT_ROOT / '.learnings'
DB_PATH = PROJECT_ROOT / 'data' / 'events.db'
TRASH_DIR = PROJECT_ROOT / '.trash' / 'learnings-migrated'


def parse_markdown_file(path: Path) -> list[dict]:
    """Parse a .learnings/ markdown file into structured entries."""
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8')
    entries = []
    current = None

    for line in text.split('\n'):
        m = re.match(r'^## ((?:ERR|LRN|FTR)-\d{8}-\d{3}) — (.+)$', line)
        if m:
            if current:
                entries.append(current)
            current = {
                'id': m.group(1),
                'summary': m.group(2),
                'pattern_key': '',
                'area': 'general',
                'occurrences': 1,
                'status': 'active',
                'first_seen': '',
                'last_seen': '',
                'detail_lines': [],
            }
            continue
        if current is None:
            continue

        # Metadata lines
        pk = re.match(r'^- Pattern-Key: (.+)$', line)
        if pk:
            current['pattern_key'] = pk.group(1).strip()
            continue
        am = re.match(r'^- Area: (.+)$', line)
        if am:
            current['area'] = am.group(1).strip()
            continue
        occ = re.match(r'^- Occurrences: (\d+)$', line)
        if occ:
            current['occurrences'] = int(occ.group(1))
            continue
        st = re.match(r'^- Status: (.+)$', line)
        if st:
            current['status'] = st.group(1).strip()
            continue
        fs = re.match(r'^- First-seen: (.+)$', line)
        if fs:
            current['first_seen'] = fs.group(1).strip()
            continue
        ls = re.match(r'^- Last-seen: (.+)$', line)
        if ls:
            current['last_seen'] = ls.group(1).strip()
            continue

        # Detail and evidence lines
        dm = re.match(r'^- Detail: (.+)$', line)
        if dm:
            current['detail_lines'].append(dm.group(1))
            continue
        # Continuation lines (Mitigation evidence, Regression evidence, etc.)
        if line.startswith('- ') and current['detail_lines']:
            current['detail_lines'].append(line[2:])
            continue
        if line.strip() and not line.startswith('#') and current['detail_lines']:
            current['detail_lines'].append(line.strip())

    if current:
        entries.append(current)
    return entries


def infer_entry_type(entry_id: str) -> str:
    """ERR-* → error, LRN-* → learning, FTR-* → feature."""
    if entry_id.startswith('ERR'):
        return 'error'
    elif entry_id.startswith('LRN'):
        return 'learning'
    elif entry_id.startswith('FTR'):
        return 'feature'
    return 'learning'


def infer_related_keys(pattern_key: str) -> list[str]:
    """Cross-reference by naming convention."""
    related = []
    if pattern_key.endswith('-fix'):
        related.append(pattern_key[:-4])
    elif pattern_key.endswith('-systematic'):
        base = pattern_key.replace('-systematic', '')
        related.append(base)
        related.append(base + '-random')
    return related


def normalize_status(raw_status: str) -> str:
    """Normalize markdown status to DB status values.

    DB valid: pending, promoted, retired
    Markdown has: active, validated, subsumed, improving, mitigated but fragile
    """
    s = raw_status.lower().split()[0].rstrip('(')
    if s in ('promoted',):
        return 'promoted'
    if s in ('retired', 'subsumed'):
        return 'retired'
    # active, validated, improving, mitigated → pending (still active in DB)
    return 'pending'


def migrate(dry_run: bool = False):
    from src.storage.events_db import EventsDB

    errors_file = LEARNINGS_DIR / 'ERRORS.md'
    learnings_file = LEARNINGS_DIR / 'LEARNINGS.md'

    errors = parse_markdown_file(errors_file)
    learnings = parse_markdown_file(learnings_file)

    all_entries = errors + learnings
    print(f"Parsed {len(errors)} errors + {len(learnings)} learnings = {len(all_entries)} total")

    if dry_run:
        for e in all_entries:
            et = infer_entry_type(e['id'])
            detail = '\n'.join(e['detail_lines'])
            print(f"  [{et}] {e['pattern_key']} (occ={e['occurrences']}, status={e['status']})")
            if detail:
                print(f"    detail: {detail[:100]}...")
        print("\n--dry-run: no changes made")
        return

    db = EventsDB(str(DB_PATH))
    now = datetime.now(timezone.utc).isoformat()
    migrated = 0
    updated = 0

    with db._connect() as conn:
        for e in all_entries:
            entry_type = infer_entry_type(e['id'])
            detail = '\n'.join(e['detail_lines'])
            related = json.dumps(infer_related_keys(e['pattern_key']))
            db_status = normalize_status(e['status'])

            existing = conn.execute(
                "SELECT id, recurrence, detail FROM learnings WHERE pattern_key = ?",
                (e['pattern_key'],),
            ).fetchone()

            if existing:
                # File version overwrites DB version (richer data from Clawvard)
                conn.execute(
                    "UPDATE learnings SET "
                    "rule = ?, detail = ?, entry_type = ?, related_keys = ?, "
                    "recurrence = ?, status = ?, first_seen = ?, last_seen = ?, "
                    "area = ? "
                    "WHERE id = ?",
                    (e['summary'], detail, entry_type, related,
                     e['occurrences'], db_status,
                     e['first_seen'] or now, e['last_seen'] or now,
                     e['area'], existing['id']),
                )
                updated += 1
                print(f"  UPDATE [{entry_type}] {e['pattern_key']} (occ={e['occurrences']})")
            else:
                conn.execute(
                    "INSERT INTO learnings (pattern_key, area, rule, detail, context, "
                    "source_type, entry_type, related_keys, status, recurrence, "
                    "created_at, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (e['pattern_key'], e['area'], e['summary'], detail,
                     entry_type, entry_type, related,
                     db_status, e['occurrences'],
                     now, e['first_seen'] or now, e['last_seen'] or now),
                )
                migrated += 1
                print(f"  INSERT [{entry_type}] {e['pattern_key']} (occ={e['occurrences']})")

    print(f"\nDone: {migrated} inserted, {updated} updated")

    # Move .learnings/ to .trash/
    if LEARNINGS_DIR.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        for f in LEARNINGS_DIR.iterdir():
            dest = TRASH_DIR / f.name
            shutil.move(str(f), str(dest))
            print(f"  mv {f} → {dest}")
        LEARNINGS_DIR.rmdir()
        print(f"\n.learnings/ moved to {TRASH_DIR}")

    # Final count
    with db._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
    print(f"DB learnings total: {count}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Migrate .learnings/ to DB')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
