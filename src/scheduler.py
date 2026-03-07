import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from src.config import load_api_key
from src.storage.events_db import EventsDB
from src.collectors.claude_collector import ClaudeCollector
from src.collectors.browser_collector import BrowserCollector
from src.collectors.git_collector import GitCollector
from src.collectors.steam_collector import SteamCollector
from src.collectors.youtube_music_collector import YouTubeMusicCollector
from src.analyst import DailyAnalyst
from src.insights import InsightEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DB_PATH = str(BASE_DIR / "events.db")


def run_collectors():
    db = EventsDB(DB_PATH)
    results = {}
    for name, collector in [
        ("claude", ClaudeCollector(db=db)),
        ("browser", BrowserCollector(db=db)),
        ("git", GitCollector(db=db)),
        ("steam", SteamCollector(db=db)),
        ("youtube_music", YouTubeMusicCollector(db=db)),
    ]:
        try:
            count = collector.collect()
            results[name] = count
        except Exception as e:
            log.error(f"Collector [{name}] failed: {e}")
            results[name] = -1
    log.info(f"Collection done: {results}")
    return results


def run_analysis():
    api_key = load_api_key()
    if not api_key:
        log.warning("No API key, skipping analysis")
        return
    db = EventsDB(DB_PATH)
    try:
        analyst = DailyAnalyst(api_key=api_key, db=db)
        result = analyst.run()
        log.info(f"Analysis done: {result.get('summary', '')[:80]}")
    except Exception as e:
        log.error(f"Analysis failed: {e}")
    try:
        engine = InsightEngine(api_key=api_key, db=db)
        engine.run()
        log.info("Insights generated")
    except Exception as e:
        log.error(f"Insights failed: {e}")


def start():
    scheduler = BlockingScheduler()
    scheduler.add_job(run_collectors, "interval", hours=1, id="collectors")
    scheduler.add_job(run_analysis, "interval", hours=1, id="analysis")

    log.info("Scheduler started. Collectors: hourly. Analysis: hourly.")
    log.info("Running initial collection...")
    run_collectors()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    start()
