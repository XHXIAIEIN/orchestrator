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
            "browser": self._check_browser(),
            "channels": self._check_channels(),
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
        """检查 DB 大小、增长趋势、journal mode 一致性、残留锁文件。"""
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
            # Journal mode 一致性检查
            jmode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        if size_mb > 100:
            self.issues.append({"level": "high", "component": "db",
                                "summary": f"DB 过大：{size_mb:.0f}MB，需要归档"})
        elif size_mb > 50:
            self.issues.append({"level": "medium", "component": "db",
                                "summary": f"DB 偏大：{size_mb:.0f}MB，关注增长"})

        # Journal mode 不应该是 WAL（Docker NTFS 不兼容）
        if jmode and jmode.lower() == "wal":
            self.issues.append({"level": "high", "component": "db",
                                "summary": "DB journal_mode=WAL，Docker NTFS 下会导致 database is locked"})

        # 检查残留的 WAL/SHM 文件（上次异常退出可能留下）
        stale_files = []
        for suffix in ("-wal", "-shm", "-journal"):
            stale = Path(self.db_path + suffix)
            if stale.exists():
                stale_size = stale.stat().st_size
                stale_files.append(f"{stale.name}({stale_size}B)")
        if stale_files:
            self.issues.append({"level": "medium", "component": "db",
                                "summary": f"DB 残留锁文件：{', '.join(stale_files)}"})

        # 锁测试：快速尝试写入并立即回滚
        lock_ok = True
        try:
            with self.db._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("ROLLBACK")
        except Exception as e:
            lock_ok = False
            self.issues.append({"level": "high", "component": "db",
                                "summary": f"DB 写锁测试失败：{e}"})

        return {"size_mb": round(size_mb, 1), "total_events": total_events,
                "events_24h": recent_events, "journal_mode": jmode,
                "stale_files": stale_files, "lock_ok": lock_ok}

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

    def _check_browser(self) -> dict:
        """检查浏览器运行时状态。"""
        try:
            from src.core.browser_runtime import BrowserRuntime
            rt = BrowserRuntime.from_env()
            info = rt.health()
            if info["status"] not in ("healthy", "running", "disabled"):
                self.issues.append({
                    "level": "low", "component": "browser_runtime",
                    "summary": f"Browser runtime: {info['status']}",
                })
            return info
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _check_channels(self) -> dict:
        """检查 Telegram / WeChat bot 是否在线、最近是否有消息活动。"""
        result = {}
        try:
            from src.channels.registry import get_channel_registry
            reg = get_channel_registry()
            for name, ch in reg._channels.items():
                ch_info = {"registered": True}
                # 检查是否有 _stop_event（说明有轮询线程）
                stop_ev = getattr(ch, "_stop_event", None)
                if stop_ev is not None:
                    ch_info["running"] = not stop_ev.is_set()
                    if stop_ev.is_set():
                        self.issues.append({
                            "level": "high", "component": f"channel:{name}",
                            "summary": f"{name} channel 已停止（stop_event set）",
                        })
                result[name] = ch_info
        except Exception as e:
            log.debug(f"Channel check failed: {e}")

        # 检查最近聊天消息活跃度
        try:
            with self.db._connect() as conn:
                row = conn.execute(
                    "SELECT created_at FROM chat_messages ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    last_msg = row[0]
                    hours_ago = (datetime.now(timezone.utc) -
                                 datetime.fromisoformat(last_msg.replace('Z', '+00:00'))).total_seconds() / 3600
                    result["last_chat_message"] = {"time": last_msg, "hours_ago": round(hours_ago, 1)}
        except Exception:
            pass

        return result
