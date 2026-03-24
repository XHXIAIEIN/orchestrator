"""
吏部 — 绩效管理。
纯 SQL 聚合，不用 LLM。每日生成一次组件绩效报告，写入 logs。
由 scheduler 定时调用。
"""
import logging
from datetime import datetime, timezone, timedelta

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class PerformanceReport:
    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())

    def run(self) -> dict:
        """生成绩效报告：采集器、Governor 任务、分析器。"""
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collectors": self._collector_stats(),
            "tasks": self._task_stats(),
            "departments": self._department_stats(),
            "system": self._system_stats(),
        }

        summary = self._format_summary(report)
        self.db.write_log(f"吏部绩效报告：{summary}", "INFO", "performance")
        log.info(f"PerformanceReport: {summary}")

        return report

    def _collector_stats(self) -> dict:
        """每个采集器：最近 7 天采集量、成功率、平均每次采集数。"""
        since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        since_1d = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        with self.db._connect() as conn:
            # 按 source 分组统计
            rows = conn.execute(
                "SELECT source, COUNT(*) as count FROM events "
                "WHERE occurred_at >= ? GROUP BY source ORDER BY count DESC",
                (since_7d,)
            ).fetchall()
            weekly = {r["source"]: r["count"] for r in rows}

            rows = conn.execute(
                "SELECT source, COUNT(*) as count FROM events "
                "WHERE occurred_at >= ? GROUP BY source ORDER BY count DESC",
                (since_1d,)
            ).fetchall()
            daily = {r["source"]: r["count"] for r in rows}

            # 采集器日志中的失败次数
            fail_rows = conn.execute(
                "SELECT COUNT(*) as count FROM logs "
                "WHERE source = 'collector' AND level = 'ERROR' AND created_at >= ?",
                (since_7d,)
            ).fetchone()
            collector_errors = fail_rows["count"] if fail_rows else 0

        return {
            "weekly_by_source": weekly,
            "daily_by_source": daily,
            "collector_errors_7d": collector_errors,
        }

    def _task_stats(self) -> dict:
        """Governor 任务统计：成功率、平均耗时、各状态计数。"""
        since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        with self.db._connect() as conn:
            # 总体统计
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed, "
                "SUM(CASE WHEN status = 'scrutiny_failed' THEN 1 ELSE 0 END) as rejected "
                "FROM tasks WHERE created_at >= ?",
                (since_7d,)
            ).fetchone()

            total = row["total"] or 0
            done = row["done"] or 0
            failed = row["failed"] or 0
            rejected = row["rejected"] or 0

            # 平均执行时间（只算完成的任务）
            duration_row = conn.execute(
                "SELECT AVG("
                "  (julianday(finished_at) - julianday(started_at)) * 86400"
                ") as avg_seconds "
                "FROM tasks WHERE status = 'done' AND started_at IS NOT NULL "
                "AND finished_at IS NOT NULL AND created_at >= ?",
                (since_7d,)
            ).fetchone()
            avg_duration = round(duration_row["avg_seconds"] or 0, 1)

        success_rate = round(done / total * 100, 1) if total > 0 else 0

        return {
            "total_7d": total,
            "done": done,
            "failed": failed,
            "rejected_by_scrutiny": rejected,
            "success_rate_pct": success_rate,
            "avg_duration_seconds": avg_duration,
        }

    def _department_stats(self) -> dict:
        """各部门任务统计（最近 7 天）。"""
        since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        with self.db._connect() as conn:
            rows = conn.execute(
                "SELECT spec, status FROM tasks WHERE created_at >= ?",
                (since_7d,)
            ).fetchall()

        import json
        dept_stats = {}
        for row in rows:
            try:
                spec = json.loads(row["spec"])
            except (json.JSONDecodeError, TypeError):
                spec = {}
            dept = spec.get("department", "unknown")
            if dept not in dept_stats:
                dept_stats[dept] = {"total": 0, "done": 0, "failed": 0}
            dept_stats[dept]["total"] += 1
            if row["status"] == "done":
                dept_stats[dept]["done"] += 1
            elif row["status"] in ("failed", "scrutiny_failed"):
                dept_stats[dept]["failed"] += 1

        return dept_stats

    def _system_stats(self) -> dict:
        """系统指标：DB 大小、日志量。"""
        since_1d = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        db_size = self.db.get_size_bytes()
        with self.db._connect() as conn:
            log_count = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE created_at >= ?",
                (since_1d,)
            ).fetchone()[0]

        return {
            "db_size_mb": round(db_size / (1024 * 1024), 1),
            "logs_24h": log_count,
        }

    def _format_summary(self, report: dict) -> str:
        """一句话摘要。"""
        tasks = report["tasks"]
        collectors = report["collectors"]
        total_events = sum(collectors["weekly_by_source"].values())

        parts = [
            f"任务 {tasks['done']}/{tasks['total_7d']}({tasks['success_rate_pct']}%)",
            f"均耗时 {tasks['avg_duration_seconds']}s",
            f"采集 {total_events} 事件/周",
            f"DB {report['system']['db_size_mb']}MB",
        ]
        if tasks["rejected_by_scrutiny"]:
            parts.append(f"门下省驳回 {tasks['rejected_by_scrutiny']}")
        if collectors["collector_errors_7d"]:
            parts.append(f"采集错误 {collectors['collector_errors_7d']}")

        return " | ".join(parts)
