"""Maintenance jobs — debt scan/resolve, voice pool refresh, memory hygiene."""
import logging
from pathlib import Path

from src.storage.events_db import EventsDB
from src.governance.learning.debt_scanner import DebtScanner
from src.governance.learning.debt_resolver import resolve_debts, check_resolved_debts
from src.voice.voice_picker import refresh_voice_pool
from src.governance.context.memory_supersede import apply_half_life

log = logging.getLogger(__name__)


def debt_scan(db: EventsDB):
    try:
        db.write_log("开始增量注意力债务扫描", "INFO", "debt_scanner")
        scanner = DebtScanner(db=db)
        debts = scanner.run(full_scan=False)
        db.write_log(f"注意力债务扫描完成：发现 {len(debts)} 个遗留问题", "INFO", "debt_scanner")
    except Exception as e:
        log.error(f"DebtScanner failed: {e}")
        db.write_log(f"注意力债务扫描失败: {e}", "ERROR", "debt_scanner")


def debt_resolve(db: EventsDB):
    try:
        # Check if previously tasked debts are now resolved
        resolved = check_resolved_debts(db)
        if resolved:
            db.write_log(f"Debt closed-loop: {resolved} debts confirmed resolved", "INFO", "debt_resolver")

        # Convert new debts into Governor tasks
        results = resolve_debts(db)
        if results["tasked"]:
            db.write_log(
                f"Debt dispatch: evaluated {results['evaluated']}, tasked {results['tasked']}, skipped {results['skipped']}",
                "INFO", "debt_resolver"
            )
    except Exception as e:
        log.error(f"DebtResolver failed: {e}")
        db.write_log(f"DebtResolver failed: {e}", "ERROR", "debt_resolver")


def memory_hygiene(db: EventsDB):
    """Scan memory files for expiry (half-life 90 days). Report only, no auto-delete."""
    try:
        # Scan all known memory directories
        memory_dirs = [
            Path.home() / ".claude" / "projects",
        ]
        total_expired = 0
        for base in memory_dirs:
            if not base.exists():
                continue
            for mem_dir in base.glob("*/memory"):
                expired = apply_half_life(mem_dir, dry_run=True)
                if expired:
                    total_expired += len(expired)
                    log.info(f"memory_hygiene: {mem_dir.parent.name} has {len(expired)} expired memories")
        if total_expired:
            db.write_log(f"Memory hygiene: {total_expired} memories past 90-day half-life", "INFO", "memory_supersede")
    except Exception as e:
        log.error(f"Memory hygiene failed: {e}")


def voice_refresh(db: EventsDB):
    try:
        db.write_log("开始刷新声音池", "INFO", "voice_picker")
        ids = refresh_voice_pool(pool_size=12)
        db.write_log(f"声音池刷新完成：{len(ids)} 个新声音", "INFO", "voice_picker")
    except Exception as e:
        log.error(f"Voice refresh failed: {e}")
        db.write_log(f"声音池刷新失败: {e}", "ERROR", "voice_picker")
