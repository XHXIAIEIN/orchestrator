import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.storage.events_db import EventsDB
from src.jobs import run_job
from src.jobs.collectors import run_collectors
from src.jobs.analysis import run_analysis
from src.jobs.maintenance import debt_scan, debt_resolve, voice_refresh, memory_hygiene, experience_cull, hotness_sweep
from src.jobs.periodic import (
    profile_periodic, profile_daily,
    performance_report, skill_evolution,
    policy_suggestions, weekly_audit,
    skill_vetting,
)
from src.jobs.sync_vectors import sync_vectors
from src.jobs.proactive_jobs import proactive_scan, proactive_daily_digest, proactive_weekly_digest
from src.jobs.evolution_jobs import evolution_cycle, steal_patrol

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "data" / "events.db")


def _init_db(retries: int = 5, delay: float = 3.0) -> EventsDB:
    """Init DB with retry — Docker bind-mount may need time to settle."""
    for attempt in range(retries):
        try:
            return EventsDB(DB_PATH)
        except Exception as e:
            log.warning(f"DB init attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                import time
                time.sleep(delay)
    # Last attempt — let it crash with full traceback
    return EventsDB(DB_PATH)


def _jitter_seconds(job_id: str, cap: int = 90) -> int:
    """Deterministic jitter: hash(job_id) % cap.  Spreads cron jobs across
    a window so they don't all fire at second-0.  Same id → same offset,
    so restarts don't shuffle the schedule.  (R49 Qwen Code — Cron Jitter)"""
    return hash(job_id) % cap


def start():
    db = _init_db()
    s = BlockingScheduler()

    # ── Core jobs — cron jobs get deterministic second-offset to avoid thundering herd ──
    s.add_job(lambda: run_job("collectors", run_collectors, db), "interval", hours=1, id="collectors")
    s.add_job(lambda: run_job("analysis", run_analysis, db), "cron", hour=4, second=_jitter_seconds("analysis"), timezone="Asia/Shanghai", id="analysis")
    s.add_job(lambda: run_job("profile_periodic", profile_periodic, db), "interval", hours=6, id="profile_periodic")
    s.add_job(lambda: run_job("profile_daily", profile_daily, db), "cron", hour=6, second=_jitter_seconds("profile_daily"), timezone="Asia/Shanghai", id="profile_daily")
    s.add_job(lambda: run_job("debt_scan", debt_scan, db), "interval", hours=12, id="debt_scan")
    s.add_job(lambda: run_job("debt_resolve", debt_resolve, db), "interval", hours=12, start_date="2026-01-01 01:00:00", timezone="Asia/Shanghai", id="debt_resolve")
    s.add_job(lambda: run_job("performance_report", performance_report, db), "cron", hour=8, second=_jitter_seconds("performance_report"), timezone="Asia/Shanghai", id="performance_report")
    s.add_job(lambda: run_job("voice_refresh", voice_refresh, db), "interval", days=7, id="voice_refresh")
    s.add_job(lambda: run_job("memory_hygiene", memory_hygiene, db), "cron", day_of_week="sun", hour=6, second=_jitter_seconds("memory_hygiene"), timezone="Asia/Shanghai", id="memory_hygiene")
    s.add_job(lambda: run_job("experience_cull", experience_cull, db), "cron", hour=3, second=_jitter_seconds("experience_cull"), timezone="Asia/Shanghai", id="experience_cull")
    s.add_job(lambda: run_job("skill_evolution", skill_evolution, db), "cron", day_of_week="mon", hour=9, second=_jitter_seconds("skill_evolution"), timezone="Asia/Shanghai", id="skill_evolution")
    s.add_job(lambda: run_job("policy_suggestions", policy_suggestions, db), "cron", hour=7, second=_jitter_seconds("policy_suggestions"), timezone="Asia/Shanghai", id="policy_suggestions")
    s.add_job(lambda: run_job("weekly_audit", weekly_audit, db), "cron", day_of_week="wed", hour=10, second=_jitter_seconds("weekly_audit"), timezone="Asia/Shanghai", id="weekly_audit")
    s.add_job(lambda: run_job("skill_vetting", skill_vetting, db), "cron", day_of_week="sat", hour=9, second=_jitter_seconds("skill_vetting"), timezone="Asia/Shanghai", id="skill_vetting")
    s.add_job(lambda: run_job("hotness_sweep", hotness_sweep, db), "cron", hour=5, second=_jitter_seconds("hotness_sweep"), timezone="Asia/Shanghai", id="hotness_sweep")
    s.add_job(lambda: run_job("sync_vectors", sync_vectors, db), "interval", hours=1, id="sync_vectors")

    # ── Proactive push engine ──
    s.add_job(lambda: run_job("proactive_scan", proactive_scan, db), "interval", minutes=5, id="proactive_scan")
    s.add_job(lambda: run_job("proactive_daily", proactive_daily_digest, db), "cron", hour=9, second=_jitter_seconds("proactive_daily"), timezone="Asia/Shanghai", id="proactive_daily")
    s.add_job(lambda: run_job("proactive_weekly", proactive_weekly_digest, db), "cron", day_of_week="mon", hour=9, minute=30, second=_jitter_seconds("proactive_weekly"), timezone="Asia/Shanghai", id="proactive_weekly")

    # ── Evolution Loop ──
    s.add_job(lambda: run_job("evolution_cycle", evolution_cycle, db), "interval", minutes=30, id="evolution_cycle")
    s.add_job(lambda: run_job("steal_patrol", steal_patrol, db), "cron", day_of_week="wed", hour=14, second=_jitter_seconds("steal_patrol"), timezone="Asia/Shanghai", id="steal_patrol")

    # ── Agent Cron: 部门级定时任务 (Round 16 LobeHub) ──
    try:
        from src.governance.agent_cron import AgentCronScheduler
        agent_cron = AgentCronScheduler()
        agent_cron.load_from_blueprints()

        def _run_agent_cron_check():
            due_jobs = agent_cron.check_due()
            for job in due_jobs:
                log.info(f"AgentCron: dispatching {job.department}/{job.name}")
                try:
                    from src.governance.governor import Governor
                    gov = Governor(db=db)
                    gov._dispatch_task(
                        spec={"department": job.department, **job.payload},
                        action=job.payload.get("action", job.name),
                        reason=f"agent_cron: {job.name}",
                        priority="medium",
                        source="agent_cron",
                    )
                    agent_cron.mark_executed(job.department, job.name)
                except Exception as e:
                    log.warning(f"AgentCron: failed to dispatch {job.department}/{job.name}: {e}")

        s.add_job(_run_agent_cron_check, "interval", minutes=1, id="agent_cron_check")
        log.info(f"AgentCron: loaded {len(agent_cron.list_jobs())} department cron jobs")
    except Exception as e:
        log.debug(f"AgentCron init skipped: {e}")

    # 启动 Channel 层（Telegram polling 等）+ 注册入站命令 handler
    try:
        from src.channels.registry import get_channel_registry
        from src.channels.inbound import register_inbound_handlers
        channel_reg = get_channel_registry()
        channel_reg.start_all()
        register_inbound_handlers(db_path=DB_PATH)

        # ApprovalGateway — 可选，连接 Channel 层实现多通道审批
        try:
            from src.governance.approval import init_approval_gateway
            init_approval_gateway(channel_registry=channel_reg)
            log.info("ApprovalGateway initialized with channel registry")
        except Exception as e:
            log.debug(f"ApprovalGateway init skipped: {e}")

        channel_status = channel_reg.get_status()
        if channel_status:
            db.write_log(f"Channel 层已启动: {', '.join(channel_status.keys())}", "INFO", "channels")
            log.info(f"Channels started: {list(channel_status.keys())}")
        else:
            log.info("No channels configured (set TELEGRAM_BOT_TOKEN or WECOM_WEBHOOK_URL)")
    except Exception as e:
        log.warning(f"Channel layer init failed (non-fatal): {e}")

    # ── Proactive Engine: 主动推送扫描 (Reverse Prompting) ──
    try:
        from src.proactive.engine import ProactiveEngine, set_proactive_engine
        from src.proactive.config import SCAN_INTERVAL_MINUTES
        from src.core.llm_router import LLMRouter

        proactive_engine = ProactiveEngine(
            db=db,
            registry=channel_reg if 'channel_reg' in locals() else None,
            llm_router=LLMRouter(),
        )
        set_proactive_engine(proactive_engine)
        s.add_job(
            lambda: proactive_engine.scan_cycle(),
            "interval",
            minutes=SCAN_INTERVAL_MINUTES,
            id="proactive_scan",
        )
        log.info(f"ProactiveEngine: scanning every {SCAN_INTERVAL_MINUTES}min")
    except Exception as e:
        log.debug(f"ProactiveEngine init skipped: {e}")

    # BrowserRuntime — 可选，浏览器感官层
    browser_runtime = None
    try:
        from src.core.browser_runtime import BrowserRuntime
        browser_runtime = BrowserRuntime.from_env()
        if browser_runtime._enabled:
            if browser_runtime.start():
                db.write_log(f"BrowserRuntime started: {browser_runtime.health()}", "INFO", "browser")
                log.info(f"BrowserRuntime started: port={browser_runtime._debug_port}")
            else:
                log.info("BrowserRuntime: Chrome not available, running without browser")
        else:
            log.info("BrowserRuntime: disabled by BROWSER_RUNTIME_ENABLED=false")
    except Exception as e:
        log.warning(f"BrowserRuntime init failed (non-fatal): {e}")

    db.write_log("调度器已启动，采集：每小时，日报：每日04:00，画像分析：每6小时+每日06:00，债务扫描：每12小时，债务解决：每12小时(+1h offset)，吏部绩效：每日08:00，声音池：每7天，技能演进：每周一09:00，策略建议：每日07:00，每周审计(兵部+吏部+礼部)：每周三10:00，主动推送：每5分钟扫描+每日09:00日报+每周一09:30周报，进化循环：每30分钟，偷师巡查：每周三14:00", "INFO", "scheduler")
    log.info("Scheduler started. Collectors: hourly. Analysis: daily 04:00 CST. Debt scan: every 12 hours.")

    # ── Zombie Task Reaper: 定时清理卡死任务 ──
    # Fix: _reap_zombie_tasks 原来只在 dispatch 时触发，没有新任务就永远不会清理。
    # 现在独立定时跑，确保 stuck tasks 不会永久占满线程池。
    try:
        from src.governance.dispatcher import TaskDispatcher
        from src.governance.scrutiny import Scrutinizer
        _reaper_dispatcher = TaskDispatcher(db=db, scrutinizer=Scrutinizer(db=db))

        def _reap_zombie_tasks():
            try:
                _reaper_dispatcher._reap_zombie_tasks()
            except Exception as e:
                log.warning(f"ZombieReaper: error during reap cycle: {e}")

        s.add_job(_reap_zombie_tasks, "interval", minutes=1, id="zombie_task_reaper")
        log.info("ZombieReaper: enabled, checking every 1 minute")
    except Exception as e:
        log.warning(f"ZombieReaper init failed (non-fatal): {e}")

    # ── Startup Cleanup: 清理上次运行残留的 running 任务 ──
    try:
        running_tasks = db.get_running_tasks()
        if running_tasks:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            for t in running_tasks:
                db.update_task(t["id"], status="failed",
                               output="startup cleanup: task was running when container restarted",
                               finished_at=now)
                log.warning(f"Startup cleanup: marked stale task #{t['id']} as failed")
            log.info(f"Startup cleanup: cleared {len(running_tasks)} stale running tasks")
    except Exception as e:
        log.warning(f"Startup cleanup failed (non-fatal): {e}")

    # 启动后跑一次初始采集 + 债务扫描
    log.info("Running initial collection...")
    run_job("collectors", run_collectors, db)

    log.info("Running initial debt scan...")
    run_job("debt_scan", debt_scan, db)

    log.info("Running initial debt resolve...")
    run_job("debt_resolve", debt_resolve, db)

    # Add BrowserRuntime tab reaper job if available
    if browser_runtime and browser_runtime.available:
        s.add_job(
            lambda: browser_runtime._reap_zombie_tabs_internal(),
            "interval", seconds=60, id="browser_tab_reaper"
        )

    # Register BrowserRuntime cleanup on exit
    import atexit
    if browser_runtime:
        atexit.register(browser_runtime.stop)

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
