"""
VS Code Activity Collector — 从 VS Code 的本地 state.vscdb 采集开发活动。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from src.storage.events_db import EventsDB


class VSCodeCollector:
    def __init__(self, db: EventsDB, vscode_path: str = None):
        self.db = db
        if vscode_path:
            self.vscode_path = Path(vscode_path)
        else:
            env = os.environ.get("VSCODE_DATA_PATH")
            if env:
                self.vscode_path = Path(env)
            else:
                self.vscode_path = Path.home() / "AppData/Roaming/Code/User"

    def collect(self) -> int:
        count = 0
        count += self._collect_recent_workspaces()
        count += self._collect_active_workspaces()
        return count

    def _read_state_db(self, db_path: Path, key: str):
        """安全读取 state.vscdb（复制后读取，避免锁冲突）"""
        if not db_path.exists():
            return None
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".vscdb", delete=False)
            tmp.close()
            shutil.copy2(str(db_path), tmp.name)
            conn = sqlite3.connect(tmp.name)
            row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
            return None
        except Exception:
            return None
        finally:
            if tmp:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

    def _collect_recent_workspaces(self) -> int:
        """从 recently opened 列表采集项目信息"""
        global_db = self.vscode_path / "globalStorage" / "state.vscdb"
        data = self._read_state_db(global_db, "history.recentlyOpenedPathsList")
        if not data or "entries" not in data:
            return 0

        new_count = 0
        for entry in data["entries"]:
            try:
                uri = entry.get("folderUri") or entry.get("fileUri") or ""
                if not uri:
                    continue

                # Parse file:///d%3A/path -> D:/path
                parsed = urlparse(uri)
                path_str = unquote(parsed.path).lstrip("/")
                if len(path_str) > 2 and path_str[1] == ":":
                    path_str = path_str[0].upper() + path_str[1:]

                project_path = Path(path_str)
                project_name = project_path.name

                # Check if the directory still exists and when it was last modified
                if not project_path.exists():
                    continue

                # Use directory mtime as proxy for last activity
                mtime = project_path.stat().st_mtime
                cutoff = time.time() - 30 * 86400  # 30 days
                if mtime < cutoff:
                    continue

                ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                dedup_key = hashlib.md5(f"vscode:project:{path_str}:{int(mtime // 86400)}".encode()).hexdigest()

                # Score based on recency
                days_ago = (time.time() - mtime) / 86400
                score = max(0.2, min(1.0, 1.0 - days_ago / 30))

                inserted = self.db.insert_event(
                    source="vscode",
                    category="dev",
                    title=project_name,
                    duration_minutes=0,
                    score=score,
                    tags=["dev", "vscode", "project"],
                    metadata={
                        "path": path_str,
                        "type": "folder" if entry.get("folderUri") else "file",
                    },
                    dedup_key=dedup_key,
                    occurred_at=ts,
                )
                if inserted:
                    new_count += 1
            except Exception:
                continue

        return new_count

    def _collect_active_workspaces(self) -> int:
        """通过 workspaceStorage 目录的修改时间检测最近活跃的 workspace"""
        ws_root = self.vscode_path / "workspaceStorage"
        if not ws_root.exists():
            return 0

        new_count = 0
        cutoff = time.time() - 7 * 86400  # 7 days

        for ws_dir in ws_root.iterdir():
            if not ws_dir.is_dir():
                continue
            try:
                state_db = ws_dir / "state.vscdb"
                if not state_db.exists():
                    continue

                mtime = state_db.stat().st_mtime
                if mtime < cutoff:
                    continue

                # Try to find workspace.json for the folder path
                ws_json = ws_dir / "workspace.json"
                folder_path = ""
                if ws_json.exists():
                    try:
                        ws_data = json.loads(ws_json.read_text(encoding="utf-8"))
                        folder_uri = ws_data.get("folder", "")
                        if folder_uri:
                            parsed = urlparse(folder_uri)
                            folder_path = unquote(parsed.path).lstrip("/")
                    except Exception:
                        pass

                if not folder_path:
                    continue

                project_name = Path(folder_path).name
                ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                dedup_key = hashlib.md5(f"vscode:active:{folder_path}:{int(mtime // 3600)}".encode()).hexdigest()

                days_ago = (time.time() - mtime) / 86400
                score = max(0.3, min(1.0, 1.0 - days_ago / 7))

                inserted = self.db.insert_event(
                    source="vscode",
                    category="dev",
                    title=f"{project_name} (活跃)",
                    duration_minutes=0,
                    score=score,
                    tags=["dev", "vscode", "workspace", "active"],
                    metadata={
                        "path": folder_path,
                        "workspace_hash": ws_dir.name,
                    },
                    dedup_key=dedup_key,
                    occurred_at=ts,
                )
                if inserted:
                    new_count += 1
            except Exception:
                continue

        return new_count
