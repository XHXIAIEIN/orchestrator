import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.storage.events_db import EventsDB
from src.jobs import run_job
from src.jobs.collectors import run_collectors
from src.jobs.analysis import run_analysis
from src.jobs.maintenance import debt_scan, debt_resolve, voice_refresh
from src.jobs.periodic import (
    profile_periodic, profile_daily,
    performance_report, skill_evolution,
    policy_suggestions, weekly_audit,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def start():
    db = EventsDB(DB_PATH)
    s = BlockingScheduler()

    s.add_job(lambda: run_job("collectors", run_collectors, db), "interval", hours=1, id="collectors")
    s.add_job(lambda: run_job("analysis", run_analysis, db), "interval", hours=6, id="analysis")
    s.add_job(lambda: run_job("profile_periodic", profile_periodic, db), "interval", hours=6, id="profile_periodic")
    s.add_job(lambda: run_job("profile_daily", profile_daily, db), "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
    s.add_job(lambda: run_job("debt_scan", debt_scan, db), "interval", hours=12, id="debt_scan")
    s.add_job(lambda: run_job("debt_resolve", debt_resolve, db), "interval", hours=12, start_date="2026-01-01 01:00:00", timezone="Asia/Shanghai", id="debt_resolve")
    s.add_job(lambda: run_job("performance_report", performance_report, db), "cron", hour=8, timezone="Asia/Shanghai", id="performance_report")
    s.add_job(lambda: run_job("voice_refresh", voice_refresh, db), "interval", days=7, id="voice_refresh")
    s.add_job(lambda: run_job("skill_evolution", skill_evolution, db), "cron", day_of_week="mon", hour=9, timezone="Asia/Shanghai", id="skill_evolution")
    s.add_job(lambda: run_job("policy_suggestions", policy_suggestions, db), "cron", hour=7, timezone="Asia/Shanghai", id="policy_suggestions")
    s.add_job(lambda: run_job("weekly_audit", weekly_audit, db), "cron", day_of_week="wed", hour=10, timezone="Asia/Shanghai", id="weekly_audit")

    # 启动 Channel 层（Telegram polling 等）+ 注册入站命令 handler
    try:
        from src.channels.registry import get_channel_registry
        from src.channels.inbound import register_inbound_handlers
        channel_reg = get_channel_registry()
        channel_reg.start_all()
        register_inbound_handlers(db_path=DB_PATH)
        channel_status = channel_reg.get_status()
        if channel_status:
            db.write_log(f"Channel 层已启动: {', '.join(channel_status.keys())}", "INFO", "channels")
            log.info(f"Channels started: {list(channel_status.keys())}")
        else:
            log.info("No channels configured (set TELEGRAM_BOT_TOKEN or WECOM_WEBHOOK_URL)")
    except Exception as e:
        log.warning(f"Channel layer init failed (non-fatal): {e}")

    db.write_log("调度器已启动，采集：每小时，分析：每6小时，画像分析：每6小时+每日06:00，债务扫描：每12小时，债务解决：每12小时(+1h offset)，吏部绩效：每日08:00，声音池：每7天，技能演进：每周一09:00，策略建议：每日07:00，每周审计(兵部+吏部+礼部)：每周三10:00", "INFO", "scheduler")
    log.info("Scheduler started. Collectors: hourly. Analysis: every 6 hours. Debt scan: every 12 hours.")

    # 启动后跑一次初始采集 + 债务扫描
    log.info("Running initial collection...")
    run_job("collectors", run_collectors, db)

    log.info("Running initial debt scan...")
    run_job("debt_scan", debt_scan, db)

    log.info("Running initial debt resolve...")
    run_job("debt_resolve", debt_resolve, db)

    try:
        s.start()
    except (KeyboardInterrupt, SystemExit):
        try:
            from src.channels.registry import get_channel_registry
            get_channel_registry().stop_all()
        except Exception:
            pass
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
