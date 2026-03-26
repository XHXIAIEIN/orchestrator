"""
EvolutionCycle — 自我改善闭环编排器。

完整循环：
  1. pattern_analyzer  → 结构化发现（无 LLM）
  2. skill_evolver     → LLM 分析生成 suggestions
  3. skill_applier     → suggestions → SKILL.md 补丁
  4. 验证              → 检查成功率是否下降，必要时回滚

触发条件：
  - 部门 run-log 每增 10 条触发一次
  - 或手动调用 run_evolution_cycle()
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

# 每 N 条新 run-log 触发一次演化
TRIGGER_EVERY_N_RUNS = 10

# 演化状态文件：记录上次触发时各部门的 run count
_STATE_FILE = _REPO_ROOT / "data" / "evolution_state.json"


def _load_state() -> dict:
    """加载演化状态（上次各部门的 run count）。"""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    """持久化演化状态。"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _count_runs(department: str) -> int:
    """统计部门 run-log 的条数。"""
    run_log = _REPO_ROOT / "departments" / department / "run-log.jsonl"
    if not run_log.exists():
        return 0
    try:
        return sum(1 for line in run_log.read_text(encoding="utf-8").strip().split("\n") if line.strip())
    except Exception:
        return 0


def _recent_success_rate(department: str, n: int = 10) -> float:
    """最近 N 条 run 的成功率。"""
    run_log = _REPO_ROOT / "departments" / department / "run-log.jsonl"
    if not run_log.exists():
        return 1.0
    try:
        lines = [l for l in run_log.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        recent = lines[-n:]
        if not recent:
            return 1.0
        runs = [json.loads(l) for l in recent]
        done = sum(1 for r in runs if r.get("status") == "done")
        return done / len(runs)
    except Exception:
        return 1.0


def should_trigger(department: str) -> bool:
    """检查该部门是否应该触发演化。"""
    state = _load_state()
    current_count = _count_runs(department)
    last_count = state.get(department, {}).get("last_run_count", 0)
    return (current_count - last_count) >= TRIGGER_EVERY_N_RUNS


def run_evolution_cycle(department: str, force: bool = False) -> dict:
    """为单个部门执行完整演化循环。

    Returns:
        dict: {
            department, triggered, pattern_findings, suggestions_generated,
            patch_applied, patch_text, success_rate_before, success_rate_after,
            rolled_back, reason
        }
    """
    result = {
        "department": department,
        "triggered": False,
        "pattern_findings": 0,
        "suggestions_generated": False,
        "patch_applied": False,
        "patch_text": "",
        "success_rate_before": 0.0,
        "success_rate_after": 0.0,
        "rolled_back": False,
        "reason": "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if not force and not should_trigger(department):
        result["reason"] = "not enough new runs since last evolution"
        return result

    result["triggered"] = True
    log.info(f"EvolutionCycle: starting for {department}")

    # 记录演化前成功率
    result["success_rate_before"] = _recent_success_rate(department)

    # ── Step 1: Pattern Analysis（无 LLM）──
    try:
        from src.governance.learning.pattern_analyzer import analyze_department_patterns
        patterns = analyze_department_patterns(department)
        result["pattern_findings"] = len(patterns.findings)
        log.info(f"EvolutionCycle: {department} — {len(patterns.findings)} patterns found")
    except Exception as e:
        log.warning(f"EvolutionCycle: pattern analysis failed for {department}: {e}")
        patterns = None

    # ── Step 2: Skill Evolution（LLM 分析）──
    try:
        from src.governance.learning.skill_evolver import analyze_department
        analysis = analyze_department(department)
        if analysis and "暂无建议" not in analysis:
            result["suggestions_generated"] = True
            log.info(f"EvolutionCycle: {department} — suggestions generated")
        else:
            result["reason"] = "no actionable suggestions from evolver"
            _update_state(department)
            return result
    except Exception as e:
        result["reason"] = f"skill evolver failed: {e}"
        log.warning(f"EvolutionCycle: {result['reason']}")
        _update_state(department)
        return result

    # ── Step 3: Apply Suggestions ──
    try:
        from src.governance.learning.skill_applier import apply_suggestions
        apply_result = apply_suggestions(department)
        result["patch_applied"] = apply_result["applied"]
        result["patch_text"] = apply_result["patch"]
        if not apply_result["applied"]:
            result["reason"] = f"applier: {apply_result['reason']}"
            _update_state(department)
            return result
    except Exception as e:
        result["reason"] = f"skill applier failed: {e}"
        log.warning(f"EvolutionCycle: {result['reason']}")
        _update_state(department)
        return result

    # ── Step 4: 更新状态 ──
    _update_state(department)
    result["reason"] = "evolution cycle completed"
    log.info(f"EvolutionCycle: {department} — cycle completed, patch applied")

    return result


def validate_evolution(department: str) -> dict:
    """演化后验证：检查成功率是否下降。在后续 runs 后调用。

    Returns:
        dict: {degraded, rate_before, rate_after, rolled_back}
    """
    state = _load_state()
    dept_state = state.get(department, {})
    rate_before = dept_state.get("success_rate_at_evolution", 1.0)
    rate_after = _recent_success_rate(department, n=5)

    result = {
        "degraded": False,
        "rate_before": rate_before,
        "rate_after": rate_after,
        "rolled_back": False,
    }

    # 成功率下降超过 20% → 回滚
    if rate_after < rate_before - 0.2 and rate_after < 0.6:
        result["degraded"] = True
        log.warning(
            f"EvolutionCycle: {department} success rate degraded "
            f"{rate_before:.0%} → {rate_after:.0%}, rolling back"
        )
        try:
            from src.governance.learning.skill_applier import rollback_last_patch
            if rollback_last_patch(department):
                result["rolled_back"] = True
                log.info(f"EvolutionCycle: rolled back last patch for {department}")
        except Exception as e:
            log.error(f"EvolutionCycle: rollback failed for {department}: {e}")

    return result


def run_all_departments(force: bool = False) -> list[dict]:
    """对所有部门执行演化循环。"""
    results = []
    dept_root = _REPO_ROOT / "departments"
    for d in sorted(dept_root.iterdir()):
        if d.is_dir() and not d.name.startswith((".", "_", "shared")):
            r = run_evolution_cycle(d.name, force=force)
            results.append(r)
    return results


def _update_state(department: str):
    """更新该部门的演化状态。"""
    state = _load_state()
    state[department] = {
        "last_run_count": _count_runs(department),
        "last_evolution_ts": datetime.now(timezone.utc).isoformat(),
        "success_rate_at_evolution": _recent_success_rate(department),
    }
    _save_state(state)
