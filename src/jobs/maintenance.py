"""Maintenance jobs — debt scan/resolve and voice pool refresh."""
import logging

from src.storage.events_db import EventsDB
from src.governance.learning.debt_scanner import DebtScanner
from src.governance.learning.debt_resolver import resolve_debts, check_resolved_debts
from src.voice.voice_picker import refresh_voice_pool

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


def voice_refresh(db: EventsDB):
    try:
        db.write_log("开始刷新声音池", "INFO", "voice_picker")
        ids = refresh_voice_pool(pool_size=12)
        db.write_log(f"声音池刷新完成：{len(ids)} 个新声音", "INFO", "voice_picker")
    except Exception as e:
        log.error(f"Voice refresh failed: {e}")
        db.write_log(f"声音池刷新失败: {e}", "ERROR", "voice_picker")
