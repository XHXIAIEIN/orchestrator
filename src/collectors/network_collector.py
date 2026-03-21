"""
Network Traffic Collector — 采集当前网络连接快照。
使用 psutil 或 subprocess 调用系统命令获取活跃 TCP 连接。
"""
import hashlib
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from src.storage.events_db import EventsDB
from src.collectors.base import ICollector, CollectorMeta

# 常见端口 → 服务映射
PORT_SERVICES = {
    22: "SSH", 80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
    6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt", 27017: "MongoDB",
    6333: "Qdrant", 11434: "Ollama", 23714: "Orchestrator", 23715: "TTS",
    3389: "RDP", 53: "DNS", 993: "IMAP", 587: "SMTP",
}

# 进程分类
PROCESS_CATEGORIES = {
    "dev": ["code", "node", "python", "git", "docker", "npm", "bun", "cargo", "go"],
    "ai": ["claude", "ollama", "anthropic"],
    "browser": ["chrome", "firefox", "edge", "msedge", "brave"],
    "gaming": ["steam", "epicgames", "riot"],
    "media": ["qqmusic", "spotify", "vlc", "mpv"],
    "communication": ["discord", "telegram", "wechat", "qq"],
    "system": ["svchost", "system", "lsass", "services", "explorer"],
}


def categorize_process(name: str) -> str:
    name_lower = name.lower().replace(".exe", "")
    for cat, patterns in PROCESS_CATEGORIES.items():
        if any(p in name_lower for p in patterns):
            return cat
    return "other"


class NetworkCollector(ICollector):
    @classmethod
    def metadata(cls) -> CollectorMeta:
        return CollectorMeta(
            name="network", display_name="Network", category="core",
            env_vars=[], requires=[],
            event_sources=["network"], default_enabled=True,
        )

    def __init__(self, db: EventsDB):
        super().__init__(db)
        self.db = db

    def collect(self) -> int:
        """采集当前网络连接快照"""
        connections = self._get_connections()
        if not connections:
            return 0

        # 过滤 localhost → localhost 的连接
        connections = [
            c for c in connections
            if not (c["remote_addr"] in ("127.0.0.1", "::1", "0.0.0.0")
                    and c["local_addr"] in ("127.0.0.1", "::1", "0.0.0.0"))
        ]
        if not connections:
            return 0

        # 按进程分组
        by_process = defaultdict(list)
        for conn in connections:
            by_process[conn["process"]].append(conn)

        new_count = 0
        snapshot_time = datetime.now(timezone.utc)
        snapshot_hour = snapshot_time.strftime("%Y-%m-%dT%H")

        # 1. 按进程类别汇总
        category_counts = Counter()
        for proc_name, conns in by_process.items():
            cat = categorize_process(proc_name)
            category_counts[cat] += len(conns)

        # 总体网络快照
        dedup_key = hashlib.md5(f"network:snapshot:{snapshot_hour}".encode()).hexdigest()
        total_conns = len(connections)
        unique_remotes = len(set(c["remote_addr"] for c in connections if c["remote_addr"]))
        top_processes = sorted(by_process.items(), key=lambda x: len(x[1]), reverse=True)[:5]

        inserted = self.db.insert_event(
            source="network",
            category="system",
            title=f"网络快照: {total_conns} 连接, {unique_remotes} 远程地址",
            duration_minutes=0,
            score=min(1.0, total_conns / 100),
            tags=["network", "snapshot"],
            metadata={
                "total_connections": total_conns,
                "unique_remotes": unique_remotes,
                "by_category": dict(category_counts),
                "top_processes": [
                    {"name": name, "connections": len(conns)}
                    for name, conns in top_processes
                ],
            },
            dedup_key=dedup_key,
            occurred_at=snapshot_time.isoformat(),
        )
        if inserted:
            new_count += 1

        # 2. 记录有趣的进程连接（非系统的，连接数 >= 2）
        for proc_name, conns in by_process.items():
            cat = categorize_process(proc_name)
            if cat == "system":
                continue
            if len(conns) < 2:
                continue

            remote_ports = [c["remote_port"] for c in conns if c["remote_port"]]
            services = [PORT_SERVICES.get(p, f"port:{p}") for p in set(remote_ports)]

            dedup_key = hashlib.md5(
                f"network:process:{proc_name}:{snapshot_hour}".encode()
            ).hexdigest()

            inserted = self.db.insert_event(
                source="network",
                category=cat,
                title=f"{proc_name}: {len(conns)} 连接",
                duration_minutes=0,
                score=min(1.0, len(conns) / 20),
                tags=["network", cat, proc_name.lower()],
                metadata={
                    "process": proc_name,
                    "connection_count": len(conns),
                    "services": services[:10],
                    "remote_addrs": list(set(c["remote_addr"] for c in conns))[:10],
                },
                dedup_key=dedup_key,
                occurred_at=snapshot_time.isoformat(),
            )
            if inserted:
                new_count += 1

        return new_count

    def _get_connections(self) -> list[dict]:
        """获取当前活跃的 TCP 连接"""
        try:
            import psutil
            return self._get_via_psutil()
        except ImportError:
            pass
        return self._get_via_netstat()

    def _get_via_psutil(self) -> list[dict]:
        import psutil
        connections = []
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != "ESTABLISHED":
                continue
            try:
                proc = psutil.Process(conn.pid) if conn.pid else None
                connections.append({
                    "process": proc.name() if proc else "unknown",
                    "pid": conn.pid or 0,
                    "local_addr": conn.laddr.ip if conn.laddr else "",
                    "local_port": conn.laddr.port if conn.laddr else 0,
                    "remote_addr": conn.raddr.ip if conn.raddr else "",
                    "remote_port": conn.raddr.port if conn.raddr else 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return connections

    def _get_via_netstat(self) -> list[dict]:
        """用 netstat -ano 解析连接（Windows 兼容）"""
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
        except Exception:
            return []

        connections = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0] != "TCP":
                continue
            if parts[3] != "ESTABLISHED":
                continue

            try:
                local = parts[1].rsplit(":", 1)
                remote = parts[2].rsplit(":", 1)
                pid = int(parts[4])
                proc_name = self._pid_to_name(pid)

                connections.append({
                    "process": proc_name,
                    "pid": pid,
                    "local_addr": local[0] if len(local) > 1 else "",
                    "local_port": int(local[1]) if len(local) > 1 else 0,
                    "remote_addr": remote[0] if len(remote) > 1 else "",
                    "remote_port": int(remote[1]) if len(remote) > 1 else 0,
                })
            except (ValueError, IndexError):
                continue

        return connections

    def _pid_to_name(self, pid: int) -> str:
        """PID → 进程名"""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                parts = result.stdout.strip().split(",")
                if parts:
                    return parts[0].strip('"')
        except Exception:
            pass
        return f"pid:{pid}"
