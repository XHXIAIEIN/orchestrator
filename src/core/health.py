"""
Self Health Check — Orchestrator 的自我感知。
知道自己哪里坏了、哪里在膨胀、哪里没干活。
由 scheduler 每小时调用一次（和采集器一起跑）。
"""
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.storage.events_db import EventsDB

log = logging.getLogger(__name__)


class HealthCheck:
    def __init__(self, db: EventsDB = None, db_path: str = None):
        self.db = db or (EventsDB(db_path) if db_path else EventsDB())
        self.db_path = self.db.db_path
        self.issues = []

    def run(self) -> dict:
        """跑一轮完整的自检，返回报告。"""
        self.issues = []

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "db": self._check_db(),
            "collectors": self._check_collectors(),
            "governor": self._check_governor(),
            "container": self._check_container(),
            "departments": self._check_departments(),
            "issues": [],
        }
        report["issues"] = self.issues
        report["healthy"] = len(self.issues) == 0

        if self.issues:
            self.db.write_log(
                f"自检发现 {len(self.issues)} 个问题：{'; '.join(i['summary'] for i in self.issues[:3])}",
                "WARNING", "health"
            )
        else:
            self.db.write_log("自检通过", "INFO", "health")

        return report

    def _check_db(self) -> dict:
        """检查 DB 大小和增长趋势。"""
        db_file = Path(self.db_path)
        size_mb = db_file.stat().st_size / (1024 * 1024) if db_file.exists() else 0

        # 事件总数
        with self.db._connect() as conn:
            total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            # 最近24h新增
            yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            recent_events = conn.execute(
                "SELECT COUNT(*) FROM events WHERE occurred_at > ?", (yesterday,)
            ).fetchone()[0]

        if size_mb > 100:
            self.issues.append({"level": "high", "component": "db",
                                "summary": f"DB 过大：{size_mb:.0f}MB，需要归档"})
        elif size_mb > 50:
            self.issues.append({"level": "medium", "component": "db",
                                "summary": f"DB 偏大：{size_mb:.0f}MB，关注增长"})

        return {"size_mb": round(size_mb, 1), "total_events": total_events,
                "events_24h": recent_events}

    def _check_collectors(self) -> dict:
        """检查每个采集器最近是否在工作。"""
        sources = ["claude", "browser", "git", "steam", "youtube_music"]
        status = {}

        with self.db._connect() as conn:
            for src in sources:
                # browser 实际存为 browser_chrome_profile1 等，git 存为 orchestrator_codebase
                # 用 LIKE 前缀匹配，别再自己误诊自己了
                row = conn.execute(
                    "SELECT occurred_at FROM events WHERE source = ? OR source LIKE ? || '_%' ORDER BY occurred_at DESC LIMIT 1",
                    (src, src)
                ).fetchone()
                if row:
                    last = row[0]
                    hours_ago = (datetime.now(timezone.utc) -
                                 datetime.fromisoformat(last.replace('Z', '+00:00'))).total_seconds() / 3600
                    status[src] = {"last_event": last, "hours_ago": round(hours_ago, 1)}

                    if hours_ago > 48:
                        self.issues.append({"level": "medium", "component": f"collector:{src}",
                                            "summary": f"{src} 采集器 {hours_ago:.0f}h 无新数据"})
                else:
                    status[src] = {"last_event": None, "hours_ago": None}
                    self.issues.append({"level": "high", "component": f"collector:{src}",
                                        "summary": f"{src} 采集器从未采到数据"})

        return status

    def _check_governor(self) -> dict:
        """检查 Governor 任务执行情况。"""
        with self.db._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'failed'").fetchone()[0]
            done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0]
            running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'running'").fetchone()[0]
            stuck = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'running' AND started_at < ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),)
            ).fetchone()[0]

        if stuck > 0:
            self.issues.append({"level": "high", "component": "governor",
                                "summary": f"有 {stuck} 个任务卡在 running 超过 10 分钟"})

        if total > 0 and failed / total > 0.5:
            self.issues.append({"level": "medium", "component": "governor",
                                "summary": f"任务失败率 {failed}/{total} ({failed*100//total}%)"})

        return {"total": total, "done": done, "failed": failed, "running": running, "stuck": stuck}

    def _check_container(self) -> dict:
        """检查 Docker 容器状态（仅限容器内执行时有意义）。"""
        # 检查内存使用
        mem_info = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if parts[0] in ("MemTotal:", "MemAvailable:"):
                        mem_info[parts[0].rstrip(":")] = int(parts[1]) * 1024  # KB to bytes
        except (FileNotFoundError, PermissionError):
            pass  # 不在 Linux 容器内

        # 检查磁盘
        disk_info = {}
        try:
            st = os.statvfs("/orchestrator")
            disk_info["total_gb"] = round(st.f_blocks * st.f_frsize / (1024**3), 1)
            disk_info["free_gb"] = round(st.f_bavail * st.f_frsize / (1024**3), 1)
            if disk_info["free_gb"] < 1:
                self.issues.append({"level": "high", "component": "disk",
                                    "summary": f"磁盘空间不足：{disk_info['free_gb']}GB"})
        except (OSError, AttributeError):
            pass  # Windows 没有 statvfs

        return {"memory": mem_info, "disk": disk_info}

    def _check_departments(self) -> dict:
        """Validate all department domain packs — manifest, SKILL.md, blueprint completeness."""
        try:
            from src.governance.context.domain_pack import load_all_domain_packs, validate_domain_pack
            packs = load_all_domain_packs()
            result = {}
            for dept, pack in packs.items():
                issues = validate_domain_pack(pack)
                result[dept] = {
                    "valid": pack.valid and not issues,
                    "files": len(pack.files_present),
                    "issues": issues,
                }
                if issues:
                    self.issues.append({
                        "level": "medium", "component": f"dept:{dept}",
                        "summary": f"{dept} domain pack: {'; '.join(issues[:2])}",
                    })
            return result
        except Exception as e:
            log.debug(f"Department check failed: {e}")
            return {}
