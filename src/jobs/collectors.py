"""Collector job — runs all enabled data collectors in parallel."""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.storage.events_db import EventsDB
from src.collectors.registry import build_enabled_collectors
from src.collectors.reputation import ReputationTracker
from src.core.health import HealthCheck
from src.analysis.burst_detector import record_bursts

log = logging.getLogger(__name__)

MAX_COLLECTOR_WORKERS = int(os.environ.get("COLLECTOR_PARALLEL_WORKERS", "4"))
COLLECTOR_RUN_TIMEOUT = int(os.environ.get("COLLECTOR_RUN_TIMEOUT", "60"))


def _is_collector_enabled(name):
    """DEPRECATED: 由 registry.build_enabled_collectors() 替代。保留以防外部调用。"""
    default_on = {"claude", "browser", "git", "vscode", "network", "codebase"}
    env_key = f"COLLECTOR_{name.upper()}"
    val = os.environ.get(env_key)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return name in default_on


def run_collectors(db: EventsDB):
    db.write_log("开始采集数据", "INFO", "collector")
    enabled = build_enabled_collectors(db)
    results = {}
    reputation = ReputationTracker(db)

    def _run_one(name, collector):
        skip, reason = reputation.should_skip(name)
        if skip:
            log.info(f"collector [{name}] skipped: {reason}")
            return name, 0, reason
        t0 = time.time()
        try:
            count = collector.collect_with_metrics()
            return name, count, None
        except Exception as e:
            elapsed = time.time() - t0
            log.error(f"collector [{name}] failed after {elapsed:.1f}s: {e}")
            return name, -1, str(e)

    with ThreadPoolExecutor(max_workers=MAX_COLLECTOR_WORKERS) as pool:
        futures = {
            pool.submit(_run_one, name, collector): name
            for name, collector in enabled
        }
        for future in as_completed(futures, timeout=COLLECTOR_RUN_TIMEOUT):
            fname = futures[future]
            try:
                name, count, error = future.result()
                results[name] = count
                reputation.update(name, count, error)
            except Exception as e:
                results[fname] = -1
                reputation.update(fname, -1, str(e))

    # 日志汇总
    ok = [k for k, v in results.items() if v >= 0]
    fail = [k for k, v in results.items() if v < 0]
    msg = f"采集完成：{', '.join(ok)} 各 {[results[k] for k in ok]} 条"
    if fail:
        msg += f"；失败：{', '.join(fail)}"
    db.write_log(msg, "INFO", "collector")
    log.info(f"Collection done: {results}")

    # 每次采集后检测 burst session
    try:
        burst_count = record_bursts(db, lookback_hours=2)
        if burst_count:
            db.write_log(f"Burst detector: recorded {burst_count} burst session(s)", "WARN", "burst_detector")
    except Exception as e:
        log.error(f"Burst detector failed: {e}")

    # 每次采集后跑自检
    try:
        health = HealthCheck(db=db)
        report = health.run()
        if not report["healthy"]:
            log.warning(f"Health issues: {[i['summary'] for i in report['issues']]}")
    except Exception as e:
        log.error(f"Health check failed: {e}")

    return results
