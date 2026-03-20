import logging
import os
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.storage.events_db import EventsDB
from src.collectors.claude_collector import ClaudeCollector
from src.collectors.browser_collector import BrowserCollector
from src.collectors.git_collector import GitCollector
from src.collectors.steam_collector import SteamCollector
from src.collectors.youtube_music_collector import YouTubeMusicCollector
from src.collectors.qqmusic_collector import QQMusicCollector
from src.collectors.codebase_collector import CodebaseCollector
from src.collectors.vscode_collector import VSCodeCollector
from src.collectors.network_collector import NetworkCollector
from src.analysis.analyst import DailyAnalyst
from src.analysis.insights import InsightEngine
from src.governance.governor import Governor
from src.analysis.profile_analyst import ProfileAnalyst
from src.core.health import HealthCheck
from src.governance.debt_scanner import DebtScanner
from src.governance.debt_resolver import resolve_debts, check_resolved_debts
from src.analysis.performance import PerformanceReport
from src.voice.voice_picker import refresh_voice_pool
from src.governance.skill_evolver import run_evolution
from src.governance.policy_advisor import generate_all_suggestions
from src.analysis.burst_detector import record_bursts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def _is_collector_enabled(name):
    """Check COLLECTOR_<NAME> env var. Default: true for core, false for optional."""
    default_on = {"claude", "browser", "git", "vscode", "network", "codebase"}
    env_key = f"COLLECTOR_{name.upper()}"
    val = os.environ.get(env_key)
    if val is not None:
        return val.lower() in ("true", "1", "yes")
    return name in default_on


def _build_collectors(db):
    """Build enabled collector instances from env config."""
    git_paths_env = os.environ.get("GIT_PATHS")
    git_paths = [p.strip() for p in git_paths_env.split(",")] if git_paths_env else None

    all_collectors = {
        "claude":        lambda: ClaudeCollector(db=db),
        "browser":       lambda: BrowserCollector(db=db),
        "git":           lambda: GitCollector(db=db, search_paths=git_paths),
        "steam":         lambda: SteamCollector(db=db),
        "youtube_music": lambda: YouTubeMusicCollector(db=db),
        "qqmusic":       lambda: QQMusicCollector(db=db),
        "codebase":      lambda: CodebaseCollector(db=db),
        "vscode":        lambda: VSCodeCollector(db=db),
        "network":       lambda: NetworkCollector(db=db),
    }

    enabled = []
    for name, factory in all_collectors.items():
        if _is_collector_enabled(name):
            enabled.append((name, factory))
    return enabled


def run_collectors():
    db = EventsDB(DB_PATH)
    db.write_log("开始采集数据", "INFO", "collector")
    results = {}

    for name, factory in _build_collectors(db):
        try:
            collector = factory()
        except Exception as e:
            log.error(f"Collector [{name}] init failed: {e}")
            results[name] = -1
            continue
        try:
            count = collector.collect()
            results[name] = count
        except Exception as e:
            log.error(f"Collector [{name}] failed: {e}")
            results[name] = -1
    log.info(f"Collection done: {results}")
    ok = [k for k, v in results.items() if v >= 0]
    fail = [k for k, v in results.items() if v < 0]
    msg = f"采集完成：{', '.join(ok)} 各 {[results[k] for k in ok]} 条" + (f"；失败：{', '.join(fail)}" if fail else "")
    db.write_log(msg, "INFO", "collector")

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


def run_analysis():
    db = EventsDB(DB_PATH)
    try:
        db.write_log("开始每日分析", "INFO", "analyst")
        analyst = DailyAnalyst(db=db)
        result = analyst.run()
        log.info(f"Analysis done: {result.get('summary', '')[:80]}")
        db.write_log(f"每日分析完成：{result.get('summary','')[:60]}", "INFO", "analyst")
    except Exception as e:
        log.error(f"Analysis failed: {e}")
    try:
        db.write_log("开始生成洞察", "INFO", "insights")
        engine = InsightEngine(db=db)
        engine.run()
        log.info("Insights generated")
        db.write_log("洞察生成完成", "INFO", "insights")
    except Exception as e:
        log.error(f"Insights failed: {e}")
    try:
        db.write_log("Governor 开始检查任务", "INFO", "governor")
        governor = Governor(db=db)
        dispatched = governor.run_batch()
        if dispatched:
            db.write_log(f"Governor dispatched {len(dispatched)} tasks in parallel", "INFO", "governor")
        else:
            db.write_log("Governor: nothing to dispatch", "INFO", "governor")
    except Exception as e:
        log.error(f"Governor failed: {e}")

    # 自检 issues → 自我改进任务
    try:
        health = HealthCheck(db=db)
        report = health.run()
        for issue in report.get("issues", []):
            if issue["level"] == "high":
                governor = Governor(db=db)
                if governor.db.count_running_tasks() < 3:
                    task_id = governor.db.create_task(
                        action=f"修复自检问题：{issue['summary']}",
                        reason=f"自检发现 {issue['component']} 存在问题",
                        priority="high",
                        spec={
                            "problem": issue["summary"],
                            "behavior_chain": "health_check → issue detected",
                            "observation": f"组件 {issue['component']} 报告：{issue['summary']}",
                            "expected": "问题解决，下次自检通过",
                            "summary": f"自我修复：{issue['summary'][:50]}",
                            "importance": "管家自己的问题必须自己解决",
                        },
                        source="auto",
                    )
                    db.write_log(f"自检生成修复任务 #{task_id}：{issue['summary'][:50]}", "INFO", "health")
                    break  # 一次只生成一个，防止洪泛
    except Exception as e:
        log.error(f"Health → Governor failed: {e}")


def start():
    db = EventsDB(DB_PATH)
    scheduler = BlockingScheduler()

    def _collectors():
        run_collectors()
        try:
            job = scheduler.get_job("collectors")
            if job and job.next_run_time:
                EventsDB(DB_PATH).set_scheduler_status("next_collectors", job.next_run_time.isoformat())
        except Exception as e:
            log.warning(f"Failed to update next_collectors status: {e}")

    def _analysis():
        run_analysis()
        try:
            job = scheduler.get_job("analysis")
            if job and job.next_run_time:
                EventsDB(DB_PATH).set_scheduler_status("next_analysis", job.next_run_time.isoformat())
        except Exception as e:
            log.warning(f"Failed to update next_analysis status: {e}")

    def _profile_periodic():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始周期性画像分析", "INFO", "profile_analyst")
            analyst = ProfileAnalyst(db=db)
            analyst.run(analysis_type='periodic')
            db.write_log("周期性画像分析完成", "INFO", "profile_analyst")
        except Exception as e:
            log.error(f"ProfileAnalyst periodic failed: {e}")
            db.write_log(f"画像分析失败: {e}", "ERROR", "profile_analyst")

    def _profile_daily():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始晨报画像分析（昨日）", "INFO", "profile_analyst")
            analyst = ProfileAnalyst(db=db)
            analyst.run(analysis_type='daily')
            db.write_log("晨报画像分析完成", "INFO", "profile_analyst")
        except Exception as e:
            log.error(f"ProfileAnalyst daily failed: {e}")
            db.write_log(f"晨报画像分析失败: {e}", "ERROR", "profile_analyst")

    def _debt_scan():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始增量注意力债务扫描", "INFO", "debt_scanner")
            scanner = DebtScanner(db=db)
            debts = scanner.run(full_scan=False)
            db.write_log(f"注意力债务扫描完成：发现 {len(debts)} 个遗留问题", "INFO", "debt_scanner")
        except Exception as e:
            log.error(f"DebtScanner failed: {e}")
            db.write_log(f"注意力债务扫描失败: {e}", "ERROR", "debt_scanner")

    def _debt_resolve():
        db = EventsDB(DB_PATH)
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

    def _performance_report():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("吏部开始生成绩效报告", "INFO", "performance")
            perf = PerformanceReport(db=db)
            perf.run()
        except Exception as e:
            log.error(f"PerformanceReport failed: {e}")
            db.write_log(f"吏部绩效报告失败: {e}", "ERROR", "performance")

    def _voice_refresh():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始刷新声音池", "INFO", "voice_picker")
            ids = refresh_voice_pool(pool_size=12)
            db.write_log(f"声音池刷新完成：{len(ids)} 个新声音", "INFO", "voice_picker")
        except Exception as e:
            log.error(f"Voice refresh failed: {e}")
            db.write_log(f"声音池刷新失败: {e}", "ERROR", "voice_picker")

    def _skill_evolution():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始 Skill 演进分析", "INFO", "skill_evolver")
            results = run_evolution()
            summary = ", ".join(f"{k}: {v}" for k, v in (results or {}).items())
            db.write_log(f"Skill 演进分析完成: {summary}", "INFO", "skill_evolver")
        except Exception as e:
            log.error(f"SkillEvolver failed: {e}")
            db.write_log(f"Skill 演进分析失败: {e}", "ERROR", "skill_evolver")

    scheduler.add_job(_collectors, "interval", hours=1, id="collectors")
    scheduler.add_job(_analysis, "interval", hours=6, id="analysis")
    scheduler.add_job(_profile_periodic, "interval", hours=6, id="profile_periodic")
    scheduler.add_job(_profile_daily, "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
    scheduler.add_job(_debt_scan, "interval", hours=12, id="debt_scan")
    scheduler.add_job(_debt_resolve, "interval", hours=12, start_date="2026-01-01 01:00:00", timezone="Asia/Shanghai", id="debt_resolve")
    scheduler.add_job(_performance_report, "cron", hour=8, timezone="Asia/Shanghai", id="performance_report")
    scheduler.add_job(_voice_refresh, "interval", days=7, id="voice_refresh")
    scheduler.add_job(_skill_evolution, "cron", day_of_week="mon", hour=9, timezone="Asia/Shanghai", id="skill_evolution")

    def _policy_suggestions():
        db = EventsDB(DB_PATH)
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

    scheduler.add_job(_policy_suggestions, "cron", hour=7, timezone="Asia/Shanghai", id="policy_suggestions")

    def _weekly_audit():
        """每周三触发兵部安全扫描 + 吏部绩效 + 礼部债务扫描（并行场景 deep_scan）。"""
        db = EventsDB(DB_PATH)
        try:
            from src.governance.governor import Governor
            gov = Governor(db=db, db_path=DB_PATH)
            results = gov.run_parallel_scenario("deep_scan")
            if results:
                db.write_log(f"每周审计：deep_scan 派发 {len(results)} 个任务", "INFO", "scheduler")
            else:
                db.write_log("每周审计：deep_scan 无可用 slot 或派发失败", "WARNING", "scheduler")
        except Exception as e:
            log.error(f"Weekly audit failed: {e}")
            db.write_log(f"每周审计失败: {e}", "ERROR", "scheduler")

    scheduler.add_job(_weekly_audit, "cron", day_of_week="wed", hour=10, timezone="Asia/Shanghai", id="weekly_audit")

    db.write_log("调度器已启动，采集：每小时，分析：每6小时，画像分析：每6小时+每日06:00，债务扫描：每12小时，债务解决：每12小时(+1h offset)，吏部绩效：每日08:00，声音池：每7天，技能演进：每周一09:00，策略建议：每日07:00，每周审计(兵部+吏部+礼部)：每周三10:00", "INFO", "scheduler")

    log.info("Scheduler started. Collectors: hourly. Analysis: every 6 hours. Debt scan: every 12 hours.")
    log.info("Running initial collection...")
    _collectors()

    # 启动后运行一次增量债务扫描，然后尝试转化 debt 为任务
    log.info("Running initial debt scan...")
    _debt_scan()
    log.info("Running initial debt resolve...")
    _debt_resolve()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
