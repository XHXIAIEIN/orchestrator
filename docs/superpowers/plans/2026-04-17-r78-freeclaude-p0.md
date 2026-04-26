# Plan: R78 FreeClaude P0 — Memory GC + Health Snapshot

## Goal

将 `src/jobs/maintenance.py::memory_hygiene` 从 `dry_run=True` 升级为物理 GC（移至 `.trash/memory-gc/<date>/`），并新增 `src/jobs/health_snapshot.py` 周期产出 `SOUL/public/heartbeat.json`（4 维 rollup），挂到 `src/scheduler.py` 5 分钟 cron；`pytest -k "memory_gc or health_snapshot" -q` 全绿。

## File Map

- `D:/Users/Administrator/Documents/GitHub/orchestrator/src/governance/memory/memory_gc.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/src/jobs/maintenance.py` — Modify（`memory_hygiene` 增加 `enforce` 分支）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/src/governance/context/memory_supersede.py` — Modify（`apply_half_life` 增加 `move_to_trash` 参数）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/src/jobs/health_snapshot.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/src/scheduler.py` — Modify（注册新 cron）
- `D:/Users/Administrator/Documents/GitHub/orchestrator/tests/jobs/test_memory_gc.py` — Create
- `D:/Users/Administrator/Documents/GitHub/orchestrator/tests/jobs/test_health_snapshot.py` — Create

## Steps

### Phase A — Memory GC (物理执行)

1. 在 `src/governance/memory/memory_gc.py` 创建 `gc_memories(base_dirs: list[Path], threshold: float = 0.1, trash_root: Path | None = None) -> dict`，基于 `stale_detector.score_memory` 返回 composite score；score < threshold 的文件 `shutil.move` 到 `trash_root / datetime.now().strftime("%Y-%m-%d") / <relative_path>`（父目录用 `mkdir(parents=True, exist_ok=True)`）；返回 `{"moved": [paths], "kept": count, "threshold": threshold}`。
   → verify: `python -c "from src.governance.memory.memory_gc import gc_memories; print(gc_memories.__doc__)"`

2. 在 `src/governance/context/memory_supersede.py::apply_half_life` 增加 `move_to_trash: Path | None = None` 参数；当非空时：对每个 expired 路径调用 `shutil.move(path, move_to_trash / path.name)`，保留旧 `dry_run` 行为（默认不动）。
   - depends on: step 1
   → verify: `python -c "from src.governance.context.memory_supersede import apply_half_life; import inspect; assert 'move_to_trash' in inspect.signature(apply_half_life).parameters"`

3. 在 `src/jobs/maintenance.py::memory_hygiene` 末尾加 `enforce = os.environ.get('ORCH_MEMORY_GC_ENFORCE') == '1'` 分支；`enforce=True` 时调用 `apply_half_life(mem_dir, dry_run=False, move_to_trash=Path('.trash/memory-gc') / datetime.now().date().isoformat())`，把结果写到 `db.write_log(f"Memory GC enforced: moved {n} to .trash/", "INFO", "memory_gc")`。
   - depends on: step 2
   → verify: `ORCH_MEMORY_GC_ENFORCE=1 python -c "from src.jobs.maintenance import memory_hygiene; from src.storage.events_db import EventsDB; memory_hygiene(EventsDB(':memory:'))"` 不报错即通过

4. 在 `tests/jobs/test_memory_gc.py` 写 3 个测试：(a) 新建 temp memory dir 含 1 过期 + 1 新鲜 file；(b) 调 `gc_memories(dry_run=False)` 后过期 file 不在原位 而在 `.trash/memory-gc/<date>/`，新鲜 file 仍在；(c) `threshold=0` 时不删任何 file。
   - depends on: step 1
   → verify: `pytest tests/jobs/test_memory_gc.py -v`

### Phase B — Health Snapshot (统一 rollup)

5. 在 `src/jobs/health_snapshot.py` 创建 `run_health_snapshot() -> dict`：并行调 `checkers` 列表：`check_db_integrity()`（打开 events.db 跑 `PRAGMA integrity_check`），`check_task_pids()`（查 `tasks` 表 status='running' 的 pid，用 `os.kill(pid, 0)` 探活，死的 UPDATE status='failed' + 写日志），`check_disk_usage()`（`du -s SOUL/ .claude/ tmp/` 汇总 MB），`check_channel_adapters()`（调现有 per-module `health_check()` 收集）。
   → verify: `python -c "from src.jobs.health_snapshot import run_health_snapshot; print(run_health_snapshot())"` 打印含 4 键的 dict

6. 在同文件加 `rollup_overall(checks: dict) -> str`：若 disk_usage_mb > 1000 OR 任一 adapter fail → "degraded"；若 db_integrity fail OR 所有 adapters fail → "critical"；否则 "healthy"。规则抄 `R78-freeclaude-deep-steal.md` 中引用的 heartbeat.ts:249-254。
   - depends on: step 5
   → verify: `pytest tests/jobs/test_health_snapshot.py::test_rollup_rules -v`

7. 在同文件加 `persist_snapshot(snapshot: dict, path: Path = Path("SOUL/public/heartbeat.json"))`：`path.parent.mkdir(parents=True, exist_ok=True)` + `path.write_text(json.dumps(snapshot, indent=2))`——单文件覆盖写，非追加。
   - depends on: step 6
   → verify: `python -c "from src.jobs.health_snapshot import run_health_snapshot, persist_snapshot; persist_snapshot(run_health_snapshot())" && test -f SOUL/public/heartbeat.json`

8. 在 `tests/jobs/test_health_snapshot.py` 写 4 个测试：(a) 所有 adapters ok + disk<1GB → "healthy"；(b) 一个 adapter fail → "degraded"；(c) db integrity fail → "critical"；(d) task pid sweep：插一条 `pid=99999` running 的 task，跑完后 status='failed'。
   - depends on: step 5, 6
   → verify: `pytest tests/jobs/test_health_snapshot.py -v`

9. 在 `src/scheduler.py` 注册 `health_snapshot` 到 5 分钟周期（对标现有 `maintenance` jobs 的注册方式——grep `scheduler.py` 找 `add_job` 调用，按同样格式加一条 `scheduler.add_job(run_health_snapshot, 'interval', minutes=5, id='health_snapshot')`）。
   - depends on: step 7
   → verify: `python -c "from src.scheduler import build_scheduler; s = build_scheduler(); assert 'health_snapshot' in [j.id for j in s.get_jobs()]"`

### Phase C — Integration & docs

10. 在 `CLAUDE.md` 的 "### Docker & Environment" 之前加一条 `### Observability`：说明 `SOUL/public/heartbeat.json` 是 unified health snapshot，外部消费者读此文件而非查 DB；`ORCH_MEMORY_GC_ENFORCE=1` 启用物理 GC（默认仍 dry_run）。
   - depends on: step 9
   → verify: `grep -q "heartbeat.json" CLAUDE.md && grep -q "ORCH_MEMORY_GC_ENFORCE" CLAUDE.md`

11. 跑全量 regression：`pytest tests/jobs/ tests/governance/memory/ -q`。
    - depends on: step 10
    → verify: `pytest tests/jobs/ tests/governance/memory/ -q` 退出码 0

--- PHASE GATE: Plan → Implement ---
[x] File Map 列齐 7 个文件
[x] 11 步全部有 verify 命令
[x] 依赖关系显式标注（step 2 依赖 1, step 3 依赖 2, step 6 依赖 5, etc.）
[x] 无 banned placeholder（"implement the logic"、"update as needed" 等均未出现）
[ ] Owner review: 不强制（可逆，<30min 多步骤的累计），但建议 step 4+8 完成后再 commit Phase B

## 预计 Effort

- Phase A: ~3h（含测试）
- Phase B: ~2h（含测试）
- Phase C: ~0.5h

Total ~5.5h（单人单 session 可完成）。

## 来源

`docs/steal/R78-freeclaude-deep-steal.md` 的 P0.1 (Memory Physical GC) + P0.2 (Heartbeat Health Snapshot)。具体 adaptation 细节见报告的 Comparison Matrix。
