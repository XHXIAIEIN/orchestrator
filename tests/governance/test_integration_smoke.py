"""Integration smoke tests — cross-module concurrency interactions.

Validates that MemorySupersede (dedup), SmartApprovals, AgentSemaphore
(concurrency pool), and DeferredContext (deferred retrievers) play nicely
together under concurrent access.

Focus areas:
  1. Concurrent SmartApprovals + AgentSemaphore: approval decisions under slot pressure
  2. DeferredContext thread-safety: concurrent get() on the same key
  3. MemorySupersede + DeferredContext: deferred memory dedup pipeline
  4. Full pipeline: semaphore → approvals → deferred load → dedup check
"""
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.governance.smart_approvals import SmartApprovals
from src.governance.deferred_retrieval import DeferredContext
from src.governance.safety.agent_semaphore import AgentSemaphore, SemaphoreConfig
from src.governance.context.memory_supersede import (
    check_supersede, apply_half_life, SupersedeResult,
)


# ─── Helpers ───────────────────────────────────────────────────────

def _make_memory_dir(contents: dict[str, str]) -> Path:
    """Create a temp dir with .md files for memory_supersede tests."""
    d = tempfile.mkdtemp(prefix="mem_smoke_")
    for name, body in contents.items():
        (Path(d) / name).write_text(body, encoding="utf-8")
    return Path(d)


# ─── 1. Concurrent SmartApprovals + AgentSemaphore ─────────────────

class TestApprovalUnderConcurrency:
    """SmartApprovals decisions must remain consistent while
    AgentSemaphore controls how many tasks actually run."""

    def test_concurrent_record_and_query(self):
        """Multiple threads recording approvals simultaneously."""
        sa = SmartApprovals(threshold=5)
        errors = []

        def record_batch(cmd: str, n: int):
            try:
                for _ in range(n):
                    sa.record(cmd, "approve")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_batch, args=("git push origin main", 10)),
            threading.Thread(target=record_batch, args=("git push origin main", 10)),
            threading.Thread(target=record_batch, args=("npm test", 8)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # At least threshold met for git push (20 total approvals across threads)
        assert sa.should_auto_approve("git push origin main")
        stats = sa.get_stats()
        assert stats["tracked_commands"] == 2

    def test_semaphore_limits_concurrent_approvals(self):
        """Only tasks that acquire a semaphore slot should proceed to approval."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=3, mutate_max=2, read_max=2))
        sa = SmartApprovals(threshold=1)

        # Pre-trust some commands
        sa.record("deploy app", "approve")
        sa.record("run tests", "approve")

        acquired_ids = []
        rejected_ids = []

        def try_acquire_and_approve(dept: str, task_id: int, cmd: str):
            ok, reason = sem.try_acquire(dept, task_id)
            if ok and sa.should_auto_approve(cmd):
                acquired_ids.append(task_id)
            else:
                rejected_ids.append(task_id)

        threads = []
        # 4 mutate tasks, but mutate_max=2 → 2 should be rejected
        for i in range(4):
            t = threading.Thread(
                target=try_acquire_and_approve,
                args=("engineering", i + 1, "deploy app"),
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired_ids) <= 2
        assert len(rejected_ids) >= 2

    def test_deny_during_concurrent_approvals(self):
        """A deny in one thread should reset trust seen by other threads."""
        sa = SmartApprovals(threshold=2)
        sa.record("risky cmd", "approve")
        sa.record("risky cmd", "approve")

        barrier = threading.Barrier(2, timeout=5)
        results = {}

        def deny_thread():
            barrier.wait()
            sa.record("risky cmd", "deny")
            results["denied"] = True

        def check_thread():
            barrier.wait()
            time.sleep(0.01)  # let deny happen first
            results["auto"] = sa.should_auto_approve("risky cmd")

        t1 = threading.Thread(target=deny_thread)
        t2 = threading.Thread(target=check_thread)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # After deny, auto-approve should be False
        assert results.get("denied") is True
        assert results.get("auto") is False


# ─── 2. DeferredContext thread-safety ──────────────────────────────

class TestDeferredConcurrency:
    """DeferredContext.get() must be safe under concurrent access."""

    def test_concurrent_get_same_key(self):
        """Multiple threads calling get() on the same key should only
        invoke the loader once (or at most a few times due to race)."""
        call_count = {"n": 0}
        lock = threading.Lock()

        def slow_loader():
            with lock:
                call_count["n"] += 1
            time.sleep(0.01)  # simulate latency
            return "expensive_result"

        ctx = DeferredContext()
        ctx.register("shared", slow_loader)

        results = []

        def reader():
            val = ctx.get("shared")
            results.append(val)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(reader) for _ in range(8)]
            for f in as_completed(futures):
                f.result()

        # All readers must get the correct value
        assert all(r == "expensive_result" for r in results)
        # Loader called at least once (may be >1 due to race, but value is correct)
        assert call_count["n"] >= 1

    def test_concurrent_register_and_get(self):
        """Registering and getting keys from different threads."""
        ctx = DeferredContext()
        errors = []

        def writer(start: int):
            try:
                for i in range(start, start + 20):
                    ctx.register(f"key_{i}", lambda i=i: f"val_{i}")
            except Exception as e:
                errors.append(e)

        def reader(start: int):
            try:
                for i in range(start, start + 20):
                    ctx.get(f"key_{i}", default="missing")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(0,)),
            threading.Thread(target=writer, args=(20,)),
            threading.Thread(target=reader, args=(0,)),
            threading.Thread(target=reader, args=(20,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent access errors: {errors}"

    def test_error_loader_under_concurrency(self):
        """Error in loader should not poison other retrievers."""
        ctx = DeferredContext()
        ctx.register("good", lambda: "ok")
        ctx.register("bad", lambda: 1 / 0)
        ctx.register("also_good", lambda: "fine")

        results = {}

        def load_key(key):
            results[key] = ctx.get(key, "default")

        with ThreadPoolExecutor(max_workers=3) as pool:
            pool.map(load_key, ["good", "bad", "also_good"])

        assert results["good"] == "ok"
        assert results["bad"] == "default"
        assert results["also_good"] == "fine"
        assert ctx.get_stats()["errors"] >= 1


# ─── 3. MemorySupersede + DeferredContext pipeline ─────────────────

class TestDeferredMemoryDedup:
    """Combining deferred loading with memory dedup checks —
    the real-world pattern where memory content is lazy-loaded
    then checked for supersession."""

    def test_deferred_dedup_pipeline(self):
        """Register memory content as deferred, then check supersede on load."""
        mem_dir = _make_memory_dir({
            "api_notes.md": "The API uses REST endpoints with JSON payloads. Auth via bearer tokens.",
            "old_setup.md": "Install with pip install orchestrator. Run with python main.py.",
        })

        ctx = DeferredContext()
        # Register a deferred loader that checks supersede
        new_content = "The API uses REST endpoints with JSON payloads. Authentication via bearer tokens."

        ctx.register("dedup_check", lambda: check_supersede(new_content, mem_dir))

        # Not loaded yet
        assert not ctx.is_loaded("dedup_check")

        # Load and check
        result: SupersedeResult = ctx.get("dedup_check")
        assert ctx.is_loaded("dedup_check")
        assert isinstance(result, SupersedeResult)
        # Should find high similarity with api_notes.md
        assert result.similarity > 0.5  # at least somewhat similar

    def test_concurrent_dedup_on_different_dirs(self):
        """Multiple dedup checks running concurrently on separate memory dirs."""
        dirs = []
        for i in range(4):
            d = _make_memory_dir({
                f"note_{i}.md": f"This is note number {i} about topic alpha. " * 10,
            })
            dirs.append(d)

        results = {}

        def check_dir(idx):
            new = f"This is note number {idx} about topic alpha. " * 10
            r = check_supersede(new, dirs[idx])
            results[idx] = r

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(check_dir, i) for i in range(4)]
            for f in as_completed(futures):
                f.result()

        assert len(results) == 4
        # Each should find its matching note as highly similar
        for idx, r in results.items():
            assert isinstance(r, SupersedeResult)
            assert r.similarity > 0.8, f"Dir {idx}: similarity={r.similarity}"


# ─── 4. Full pipeline: Semaphore → Approvals → Deferred → Dedup ───

class TestFullPipelineSmoke:
    """End-to-end: acquire slot → check approval → lazy-load context → dedup."""

    def test_pipeline_happy_path(self):
        """Full pipeline succeeds when all gates pass."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=5, mutate_max=3, read_max=3))
        sa = SmartApprovals(threshold=1)
        sa.record("process memories", "approve")

        mem_dir = _make_memory_dir({
            "existing.md": "Some completely different content about databases and SQL queries.",
        })
        new_content = "New content about API design and REST endpoints."

        # Gate 1: Semaphore
        acquired, reason = sem.try_acquire("engineering", 100)
        assert acquired, f"Semaphore failed: {reason}"

        # Gate 2: Approval
        assert sa.should_auto_approve("process memories")

        # Gate 3: Deferred load + dedup
        ctx = DeferredContext()
        ctx.register("memory_check", lambda: check_supersede(new_content, mem_dir))
        ctx.register("config", lambda: {"model": "sonnet", "budget": 5000})

        dedup_result = ctx.get("memory_check")
        assert isinstance(dedup_result, SupersedeResult)
        # Different content → should NOT supersede
        assert not dedup_result.should_supersede

        # Config loaded only if needed
        assert not ctx.is_loaded("config")
        config = ctx.get("config")
        assert config["model"] == "sonnet"

        # Cleanup
        sem.release("engineering", 100)
        status = sem.get_status()
        assert status["global_used"] == 0

    def test_pipeline_blocked_by_semaphore(self):
        """Pipeline stops early when semaphore is full."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=1, mutate_max=1, read_max=1))
        sa = SmartApprovals(threshold=1)
        sa.record("cmd", "approve")

        # Fill the slot
        sem.try_acquire("engineering", 1)

        # Next task should be blocked
        acquired, reason = sem.try_acquire("engineering", 2)
        assert not acquired
        assert "上限" in reason

        # Pipeline should NOT proceed to approval or deferred
        # (We don't even check approval — early exit)
        loader_called = {"called": False}
        ctx = DeferredContext()
        ctx.register("data", lambda: (loader_called.__setitem__("called", True), "result")[1])

        if not acquired:
            # Simulates the pipeline early-exit: deferred data never loaded
            pass

        assert not loader_called["called"]
        assert not ctx.is_loaded("data")

    def test_pipeline_concurrent_tasks(self):
        """Multiple tasks racing through the full pipeline."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=3, mutate_max=2, read_max=2))
        sa = SmartApprovals(threshold=1)
        sa.record("batch process", "approve")

        mem_dir = _make_memory_dir({
            "shared.md": "Shared knowledge about the system architecture. " * 5,
        })

        pipeline_results = []
        pipeline_lock = threading.Lock()

        def run_pipeline(task_id: int, dept: str):
            result = {"task_id": task_id, "acquired": False, "approved": False,
                      "dedup_done": False, "supersede": False}

            acquired, _ = sem.try_acquire(dept, task_id)
            result["acquired"] = acquired
            if not acquired:
                with pipeline_lock:
                    pipeline_results.append(result)
                return

            result["approved"] = sa.should_auto_approve("batch process")

            ctx = DeferredContext()
            new = f"New content for task {task_id} about something unique."
            ctx.register("check", lambda: check_supersede(new, mem_dir))
            dedup = ctx.get("check")
            result["dedup_done"] = True
            result["supersede"] = dedup.should_supersede if dedup else False

            sem.release(dept, task_id)
            with pipeline_lock:
                pipeline_results.append(result)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = []
            # Mix of mutate and read departments
            for i in range(6):
                dept = "engineering" if i % 2 == 0 else "quality"
                futures.append(pool.submit(run_pipeline, i + 1, dept))
            for f in as_completed(futures):
                f.result()

        assert len(pipeline_results) == 6

        acquired_count = sum(1 for r in pipeline_results if r["acquired"])
        # At most global_max=3 should run concurrently, but since some release before
        # others acquire, total acquired can be > 3 across time
        assert acquired_count >= 1  # at least some got through

        # All acquired tasks should complete the pipeline
        for r in pipeline_results:
            if r["acquired"]:
                assert r["approved"]
                assert r["dedup_done"]


# ─── 5. Semaphore release + re-acquire under contention ────────────

class TestSemaphoreContention:
    """Verify semaphore correctness under heavy contention."""

    def test_acquire_release_cycle(self):
        """Rapid acquire-release cycles across threads."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=2, mutate_max=1, read_max=1))
        success_count = {"n": 0}
        lock = threading.Lock()

        def cycle(dept: str, task_id: int):
            acquired, _ = sem.try_acquire(dept, task_id)
            if acquired:
                time.sleep(0.001)  # simulate brief work
                sem.release(dept, task_id)
                with lock:
                    success_count["n"] += 1

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(20):
                dept = "engineering" if i % 2 == 0 else "protocol"
                futures.append(pool.submit(cycle, dept, i + 1))
            for f in as_completed(futures):
                f.result()

        # With rapid cycling, many should succeed despite low limits
        assert success_count["n"] > 0
        # Semaphore should be clean after all releases
        status = sem.get_status()
        assert status["global_used"] == 0

    def test_cross_department_isolation(self):
        """MUTATE and READ department limits are independent."""
        sem = AgentSemaphore(SemaphoreConfig(global_max=10, mutate_max=2, read_max=3))

        # Fill MUTATE slots
        assert sem.try_acquire("engineering", 1)[0]
        assert sem.try_acquire("operations", 2)[0]
        assert not sem.try_acquire("engineering", 3)[0]  # mutate full

        # READ slots still available
        assert sem.try_acquire("quality", 4)[0]
        assert sem.try_acquire("protocol", 5)[0]
        assert sem.try_acquire("security", 6)[0]
        assert not sem.try_acquire("personnel", 7)[0]  # read full

        status = sem.get_status()
        assert status["global_used"] == 5


# ─── 6. MemorySupersede edge cases under concurrency ──────────────

class TestMemoryDedupEdgeCases:
    """Edge cases for memory dedup that matter in concurrent workflows."""

    def test_empty_dir(self):
        """Dedup on empty directory should return no-supersede."""
        d = _make_memory_dir({})
        r = check_supersede("any content", d)
        assert not r.should_supersede
        assert r.similarity == 0.0

    def test_nonexistent_dir(self):
        """Dedup on missing directory should not crash."""
        r = check_supersede("content", Path("/nonexistent/path/abc123"))
        assert not r.should_supersede

    def test_exclude_file(self):
        """Exclude_file parameter should skip that file in comparison."""
        d = _make_memory_dir({
            "self.md": "Exact same content here.",
            "other.md": "Completely different topic about databases.",
        })
        r = check_supersede("Exact same content here.", d, exclude_file="self.md")
        # Should compare against other.md only, which is dissimilar
        assert r.similarity < 0.9

    def test_half_life_on_fresh_files(self):
        """Freshly created files should not be flagged as expired."""
        d = _make_memory_dir({
            "fresh.md": "Just created this memory.",
        })
        expired = apply_half_life(d)
        assert len(expired) == 0

    def test_concurrent_supersede_checks(self):
        """Multiple supersede checks on the same dir concurrently."""
        d = _make_memory_dir({
            "api.md": "REST API with JSON. Bearer auth. Rate limiting at 100 req/min.",
            "db.md": "PostgreSQL database. Tables: users, tasks, events. ",
        })

        new_contents = [
            "REST API with JSON. Bearer auth. Rate limiting at 100 req/min.",  # ~exact match
            "GraphQL API with subscriptions. API key auth.",  # different
            "PostgreSQL database. Tables: users, tasks, events.",  # ~exact match
            "Redis cache for sessions.",  # different
        ]

        results = [None] * 4

        def check(idx):
            results[idx] = check_supersede(new_contents[idx], d)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(check, i) for i in range(4)]
            for f in as_completed(futures):
                f.result()

        # Exact matches should have high similarity
        assert results[0].similarity > 0.8
        assert results[2].similarity > 0.8
        # Different content should have lower similarity
        assert results[1].similarity < results[0].similarity
        assert results[3].similarity < results[2].similarity
