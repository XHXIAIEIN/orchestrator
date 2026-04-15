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


def exclude_idle_time(elapsed: float, idle_since: Optional[float], now: Optional[float] = None) -> float:
    """R60 MinerU P1-3: subtract idle gaps from elapsed time.

    MinerU pattern: adjusts tqdm's start_t to exclude model-loading idle.
    We apply the same idea to job timing — if a job was queued/waiting,
    the reported duration only reflects actual processing time.
    """
    if idle_since is None:
        return elapsed
    if now is None:
        now = time.time()
    idle_duration = max(0.0, now - idle_since)
    return max(0.0, elapsed - idle_duration)


def run_job(name: str, fn, db: EventsDB, on_complete: Optional[Callable] = None,
            idle_since: Optional[float] = None):
    """Unified job wrapper: logging + exception handling + timing + optional callback.

    R60 MinerU P0-4: on_complete callback fires immediately after job finishes,
    enabling streaming-style chaining without waiting for the next scheduler tick.

    R60 MinerU P1-3: if idle_since is set, reported elapsed time excludes
    the idle gap (time spent waiting in queue, not processing).
    """
    try:
        db.write_log(f"开始 {name}", "INFO", name)
    except Exception:
        pass
    t0 = time.time()
    try:
        result = fn(db)
        raw_elapsed = time.time() - t0
        elapsed = exclude_idle_time(raw_elapsed, idle_since, time.time())
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

    def __init__(self, window_s: float = 60.0, min_bin_weight: float = 10.0):
        self._window_s = window_s
        self._min_bin_weight = min_bin_weight  # R60 P1-2: floor for adaptive halving
        self._pending: list[tuple[str, Callable, float]] = []  # (name, fn, weight)
        self._lock = threading.Lock()

    def submit(self, name: str, fn: Callable, weight: Optional[float] = None) -> None:
        """Add a job to the pending queue."""
        w = weight if weight is not None else JOB_WEIGHTS.get(name, DEFAULT_JOB_WEIGHT)
        with self._lock:
            self._pending.append((name, fn, w))

    def _pack_ffd(self) -> list[list[tuple[str, Callable, float]]]:
        """First-Fit-Decreasing bin packing with area-adaptive sizing.

        R60 MinerU P1-2: sorts jobs by weight ascending, computes baseline
        mean weight from the first batch, then halves bin capacity when
        mean weight / baseline >= 4x (prevents heavy-job bins from
        overloading execution windows).
        """
        if not self._pending:
            return []

        # Sort ascending by weight (light jobs first → establish baseline)
        sorted_jobs = sorted(self._pending, key=lambda x: x[2])

        # Separate oversized jobs (solo bin)
        normal: list[tuple[str, Callable, float]] = []
        bins: list[list[tuple[str, Callable, float]]] = []

        for job in sorted_jobs:
            if job[2] > self._window_s:
                bins.append([job])
            else:
                normal.append(job)

        if not normal:
            return bins

        # Baseline: mean weight of light half (establishes "normal" load)
        half = max(1, len(normal) // 2)
        base_mean = sum(j[2] for j in normal[:half]) / half

        # Pack with adaptive window: shrink capacity for heavy regions
        cursor = 0
        while cursor < len(normal):
            remaining = normal[cursor:]
            probe_size = min(4, len(remaining))
            region_mean = sum(j[2] for j in remaining[:probe_size]) / probe_size

            # Adaptive: halve capacity per 4x weight ratio
            effective_window = self._window_s
            if base_mean > 0:
                ratio = region_mean / base_mean
                threshold = 4.0
                while ratio >= threshold and effective_window / 2 >= self._min_bin_weight:
                    effective_window /= 2
                    threshold *= 2

            # Fill one bin up to effective_window
            current_bin: list[tuple[str, Callable, float]] = []
            current_load = 0.0
            while cursor < len(normal):
                job = normal[cursor]
                if current_load + job[2] > effective_window and current_bin:
                    break
                current_bin.append(job)
                current_load += job[2]
                cursor += 1

            bins.append(current_bin)

        return bins

    def flush(self, db: EventsDB) -> dict:
        """Execute all pending jobs in bin-packed order.

        R60 MinerU P1-3: tracks idle time between bins — jobs report
        processing-only duration, excluding inter-bin wait gaps.

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
        last_job_end: Optional[float] = None
        for bin_idx, bin_jobs in enumerate(bins):
            job_names = [j[0] for j in bin_jobs]
            log.debug("JobBatcher: bin %d/%d → %s", bin_idx + 1, len(bins), job_names)
            for name, fn, _weight in bin_jobs:
                run_job(name, fn, db, idle_since=last_job_end)
                last_job_end = time.time()

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
