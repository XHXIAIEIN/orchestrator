"""Analysis job — daily analyst, insights, governor dispatch, and health → task creation."""
import logging

from src.storage.events_db import EventsDB
from src.analysis.analyst import DailyAnalyst
from src.analysis.insights import InsightEngine
from src.governance.governor import Governor
from src.core.health import HealthCheck

log = logging.getLogger(__name__)


def run_analysis(db: EventsDB):
    try:
        db.write_log("开始每日分析", "INFO", "analyst")
        analyst = DailyAnalyst(db=db)
        result = analyst.run()
        if result and result.get("summary"):
            log.info(f"Analysis done: {result['summary'][:80]}")
            db.write_log(f"每日分析完成：{result['summary'][:60]}", "INFO", "analyst")
        else:
            log.warning("Analysis returned empty result")
            db.write_log("每日分析失败：Claude 返回空结果，日报未生成", "WARNING", "analyst")
    except Exception as e:
        log.error(f"Analysis failed: {e}")
        db.write_log(f"每日分析异常：{e}", "ERROR", "analyst")
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
