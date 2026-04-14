"""Job execution infrastructure — unified wrapper + bin-packing batcher.

R60 MinerU steal: JobBatcher uses First-Fit-Decreasing to merge small jobs
into execution windows, reducing scheduling overhead for bursty job arrivals.
"""
import logging
import time
import threading
from collections import defaultdict
from typing import Callable, Optional

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)

# ── Job weight registry: estimated cost in seconds per job ──
# Used by JobBatcher for FFD bin-packing. Unknown jobs default to 10s.
JOB_WEIGHTS: dict[str, float] = {
    "collectors": 30.0,
    "analysis": 60.0,
    "sync_vectors": 20.0,
    "proactive_scan": 5.0,
    "debt_scan": 15.0,
    "debt_resolve": 15.0,
    "profile_periodic": 20.0,
    "profile_daily": 40.0,
    "performance_report": 30.0,
    "evolution_cycle": 45.0,
    "experience_cull": 10.0,
    "hotness_sweep": 10.0,
    "memory_hygiene": 20.0,
    "zombie_task_reaper": 2.0,
    "agent_cron_check": 3.0,
}
DEFAULT_JOB_WEIGHT = 10.0


def run_job(name: str, fn, db: EventsDB, on_complete: Optional[Callable] = None):
    """Unified job wrapper: logging + exception handling + timing + optional callback.

    R60 MinerU P0-4: on_complete callback fires immediately after job finishes,
    enabling streaming-style chaining without waiting for the next scheduler tick.
    """
    try:
        db.write_log(f"开始 {name}", "INFO", name)
    except Exception:
        pass
    t0 = time.time()
    try:
        result = fn(db)
        elapsed = time.time() - t0
        try:
            db.write_log(f"{name} 完成 ({elapsed:.1f}s)", "INFO", name)
        except Exception:
            pass
        if on_complete:
            try:
                on_complete(name, result, elapsed)
            except Exception as cb_err:
                log.warning(f"{name}: on_complete callback failed: {cb_err}")
        return result
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"{name} failed after {elapsed:.1f}s: {e}")
        try:
            db.write_log(f"{name} 失败: {e}", "ERROR", name)
        except Exception:
            pass  # DB itself is broken, just log to stderr


class JobBatcher:
    """FFD bin-packing for scheduled jobs. (R60 MinerU steal)

    Groups pending jobs into execution windows of `window_s` seconds,
    using First-Fit-Decreasing by estimated job weight. Oversized jobs
    (weight > window_s) get their own dedicated window.

    Usage:
        batcher = JobBatcher(window_s=60)
        batcher.submit("collectors", run_collectors, db)
        batcher.submit("sync_vectors", sync_vectors, db)
        # Later, execute all pending bins:
        batcher.flush(db)
    """

    def __init__(self, window_s: float = 60.0):
        self._window_s = window_s
        self._pending: list[tuple[str, Callable, float]] = []  # (name, fn, weight)
        self._lock = threading.Lock()

    def submit(self, name: str, fn: Callable, weight: Optional[float] = None) -> None:
        """Add a job to the pending queue."""
        w = weight if weight is not None else JOB_WEIGHTS.get(name, DEFAULT_JOB_WEIGHT)
        with self._lock:
            self._pending.append((name, fn, w))

    def _pack_ffd(self) -> list[list[tuple[str, Callable, float]]]:
        """First-Fit-Decreasing bin packing.

        Sort jobs by weight descending, fit each into the first bin that
        has room. Oversized jobs (weight > window_s) get a solo bin.
        """
        if not self._pending:
            return []

        sorted_jobs = sorted(self._pending, key=lambda x: x[2], reverse=True)
        bins: list[list[tuple[str, Callable, float]]] = []
        bin_loads: list[float] = []

        for job in sorted_jobs:
            name, fn, weight = job
            if weight > self._window_s:
                # Oversized job → dedicated bin
                bins.append([job])
                bin_loads.append(weight)
                continue

            # First-fit: find first bin with room
            placed = False
            for i, load in enumerate(bin_loads):
                if load + weight <= self._window_s:
                    bins[i].append(job)
                    bin_loads[i] += weight
                    placed = True
                    break

            if not placed:
                bins.append([job])
                bin_loads.append(weight)

        return bins

    def flush(self, db: EventsDB) -> dict:
        """Execute all pending jobs in bin-packed order.

        Returns stats: {bins: N, jobs: N, total_elapsed: float}
        """
        with self._lock:
            bins = self._pack_ffd()
            self._pending.clear()

        if not bins:
            return {"bins": 0, "jobs": 0, "total_elapsed": 0.0}

        total_jobs = sum(len(b) for b in bins)
        log.info(
            "JobBatcher: executing %d jobs in %d bins (window=%.0fs)",
            total_jobs, len(bins), self._window_s,
        )

        t0 = time.time()
        for bin_idx, bin_jobs in enumerate(bins):
            job_names = [j[0] for j in bin_jobs]
            log.debug("JobBatcher: bin %d/%d → %s", bin_idx + 1, len(bins), job_names)
            for name, fn, _weight in bin_jobs:
                run_job(name, fn, db)

        elapsed = time.time() - t0
        stats = {"bins": len(bins), "jobs": total_jobs, "total_elapsed": round(elapsed, 2)}
        log.info("JobBatcher: completed — %s", stats)
        return stats

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def pending_summary(self) -> dict:
        """Preview of how jobs would be packed without executing."""
        with self._lock:
            bins = self._pack_ffd()
        return {
            "bins": len(bins),
            "jobs": sum(len(b) for b in bins),
            "layout": [[j[0] for j in b] for b in bins],
        }
