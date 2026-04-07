"""Periodic jobs — profile analysis, performance report, skill evolution, policy suggestions, shared knowledge, weekly audit, skill vetting."""
import logging

from src.storage.events_db import EventsDB
from src.analysis.profile_analyst import ProfileAnalyst
from src.analysis.performance import PerformanceReport
from src.governance.learning.skill_evolver import run_evolution
from src.governance.policy.policy_advisor import generate_all_suggestions
from src.jobs.shared_knowledge import update_all as update_shared_knowledge

try:
    from src.governance.audit.skill_vetter import vet_all_departments, risk_summary, RiskLevel
except ImportError:
    vet_all_departments = None

log = logging.getLogger(__name__)


def profile_periodic(db: EventsDB):
    try:
        db.write_log("开始周期性画像分析", "INFO", "profile_analyst")
        analyst = ProfileAnalyst(db=db)
        result = analyst.run(analysis_type='periodic')
        if result is None:
            db.write_log("周期性画像分析跳过（LLM 响应无效）", "WARN", "profile_analyst")
        else:
            db.write_log("周期性画像分析完成", "INFO", "profile_analyst")
    except Exception as e:
        log.error(f"ProfileAnalyst periodic failed: {e}")
        db.write_log(f"画像分析失败: {e}", "ERROR", "profile_analyst")


def profile_daily(db: EventsDB):
    try:
        db.write_log("开始晨报画像分析（昨日）", "INFO", "profile_analyst")
        analyst = ProfileAnalyst(db=db)
        result = analyst.run(analysis_type='daily')
        if result is None:
            db.write_log("晨报画像分析跳过（LLM 响应无效）", "WARN", "profile_analyst")
        else:
            db.write_log("晨报画像分析完成", "INFO", "profile_analyst")
    except Exception as e:
        log.error(f"ProfileAnalyst daily failed: {e}")
        db.write_log(f"晨报画像分析失败: {e}", "ERROR", "profile_analyst")


def performance_report(db: EventsDB):
    try:
        db.write_log("吏部开始生成绩效报告", "INFO", "performance")
        perf = PerformanceReport(db=db)
        perf.run()
    except Exception as e:
        log.error(f"PerformanceReport failed: {e}")
        db.write_log(f"吏部绩效报告失败: {e}", "ERROR", "performance")


def skill_evolution(db: EventsDB):
    try:
        db.write_log("开始 Skill 演进分析", "INFO", "skill_evolver")
        results = run_evolution()
        summary = ", ".join(f"{k}: {v}" for k, v in (results or {}).items())
        db.write_log(f"Skill 演进分析完成: {summary}", "INFO", "skill_evolver")
    except Exception as e:
        log.error(f"SkillEvolver failed: {e}")
        db.write_log(f"Skill 演进分析失败: {e}", "ERROR", "skill_evolver")


def policy_suggestions(db: EventsDB):
    try:
        results = generate_all_suggestions()
        if results:
            depts = ", ".join(results.keys())
            db.write_log(f"Policy Advisor 生成建议: {depts}", "INFO", "policy_advisor")
        else:
            db.write_log("Policy Advisor: 无新建议", "DEBUG", "policy_advisor")
    except Exception as e:
        log.error(f"PolicyAdvisor failed: {e}")
        db.write_log(f"Policy Advisor 失败: {e}", "ERROR", "policy_advisor")


def shared_knowledge(db: EventsDB):
    """Update departments/shared/ knowledge files (recent-changes, known-issues, codebase-map)."""
    try:
        results = update_shared_knowledge(db)
        summary = ", ".join(f"{k}: {v} chars" for k, v in results.items())
        db.write_log(f"共享知识更新: {summary}", "INFO", "shared_knowledge")
    except Exception as e:
        log.error(f"SharedKnowledge update failed: {e}")
        db.write_log(f"共享知识更新失败: {e}", "ERROR", "shared_knowledge")


def skill_vetting(db: EventsDB):
    """Weekly audit of all department SKILL.md files for red flags (14-point check)."""
    if not vet_all_departments:
        log.debug("skill_vetting: skill_vetter not available, skipping")
        return
    try:
        results = vet_all_departments("departments")
        total_flags = 0
        critical_depts = []
        for dept, flags in results.items():
            summary = risk_summary(flags)
            total_flags += summary["total"]
            if summary.get("CRITICAL", 0) > 0 or summary.get("HIGH", 0) > 0:
                critical_depts.append(f"{dept}(C={summary.get('CRITICAL', 0)},H={summary.get('HIGH', 0)})")
        if critical_depts:
            db.write_log(
                f"Skill vetting: {total_flags} flags across {len(results)} depts, "
                f"critical/high: {', '.join(critical_depts)}",
                "WARNING", "skill_vetter",
            )
        else:
            db.write_log(
                f"Skill vetting: {total_flags} flags across {len(results)} depts, no critical/high",
                "INFO", "skill_vetter",
            )
        log.info(f"skill_vetting: scanned {len(results)} departments, {total_flags} total flags")
    except Exception as e:
        log.error(f"skill_vetting failed: {e}")
        db.write_log(f"Skill vetting failed: {e}", "ERROR", "skill_vetter")


def weekly_audit(db: EventsDB):
    """每周三触发兵部安全扫描 + 吏部绩效 + 礼部债务扫描（并行场景 deep_scan）。"""
    try:
        from src.governance.governor import Governor
        gov = Governor(db=db)
        results = gov.run_parallel_scenario("deep_scan")
        if results:
            db.write_log(f"每周审计：deep_scan 派发 {len(results)} 个任务", "INFO", "scheduler")
        else:
            db.write_log("每周审计：deep_scan 无可用 slot 或派发失败", "WARNING", "scheduler")
    except Exception as e:
        log.error(f"Weekly audit failed: {e}")
        db.write_log(f"每周审计失败: {e}", "ERROR", "scheduler")
