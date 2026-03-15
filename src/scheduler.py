import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.storage.events_db import EventsDB
from src.collectors.claude_collector import ClaudeCollector
from src.collectors.browser_collector import BrowserCollector
from src.collectors.git_collector import GitCollector
from src.collectors.steam_collector import SteamCollector
from src.collectors.youtube_music_collector import YouTubeMusicCollector
from src.collectors.codebase_collector import CodebaseCollector
from src.analyst import DailyAnalyst
from src.insights import InsightEngine
from src.governor import Governor
from src.profile_analyst import ProfileAnalyst
from src.health import HealthCheck
from src.debt_scanner import DebtScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "events.db")


def run_collectors():
    db = EventsDB(DB_PATH)
    db.write_log("开始采集数据", "INFO", "collector")
    results = {}
    for name, collector in [
        ("claude", ClaudeCollector(db=db)),
        ("browser", BrowserCollector(db=db)),
        ("git", GitCollector(db=db)),
        ("steam", SteamCollector(db=db)),
        ("youtube_music", YouTubeMusicCollector(db=db)),
        ("orchestrator_codebase", CodebaseCollector(db=db)),
    ]:
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
        governor.run()
        db.write_log("Governor 执行完毕", "INFO", "governor")
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
        except Exception:
            pass

    def _analysis():
        run_analysis()
        try:
            job = scheduler.get_job("analysis")
            if job and job.next_run_time:
                EventsDB(DB_PATH).set_scheduler_status("next_analysis", job.next_run_time.isoformat())
        except Exception:
            pass

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

    scheduler.add_job(_collectors, "interval", hours=1, id="collectors")
    scheduler.add_job(_analysis, "interval", hours=6, id="analysis")
    scheduler.add_job(_profile_periodic, "interval", hours=6, id="profile_periodic")
    scheduler.add_job(_profile_daily, "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
    scheduler.add_job(_debt_scan, "interval", hours=12, id="debt_scan")

    db.write_log("调度器已启动，采集：每小时，分析：每6小时，画像分析：每6小时+每日06:00，债务扫描：每12小时", "INFO", "scheduler")

    log.info("Scheduler started. Collectors: hourly. Analysis: every 6 hours. Debt scan: every 12 hours.")
    log.info("Running initial collection...")
    _collectors()

    # 启动后运行一次增量债务扫描
    log.info("Running initial debt scan...")
    _debt_scan()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
