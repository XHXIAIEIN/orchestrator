"""Job execution infrastructure — unified wrapper."""
import logging
import time
from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


def run_job(name: str, fn, db: EventsDB):
    """Unified job wrapper: logging + exception handling + timing."""
    db.write_log(f"开始 {name}", "INFO", name)
    t0 = time.time()
    try:
        result = fn(db)
        elapsed = time.time() - t0
        db.write_log(f"{name} 完成 ({elapsed:.1f}s)", "INFO", name)
        return result
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"{name} failed after {elapsed:.1f}s: {e}")
        db.write_log(f"{name} 失败: {e}", "ERROR", name)
