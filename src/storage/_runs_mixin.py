"""Runs, logs, sub-runs, sessions, heartbeats, file-index, experiences, agent-events methods for EventsDB."""
import json
from datetime import datetime, timezone


class RunsMixin:

    def write_log(self, message: str, level: str = 'INFO', source: str = 'system',
                  run_id: str = None, step: str = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO logs (level, source, message, run_id, step, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (level, source, message, run_id, step, now)
            )

    def get_logs(self, since_id: int = 0, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, level, source, message, created_at FROM logs WHERE id > ? ORDER BY id ASC LIMIT ?",
                (since_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def set_scheduler_status(self, key: str, value: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scheduler_status (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now)
            )

    def get_scheduler_status(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM scheduler_status").fetchall()
        return {r['key']: r['value'] for r in rows}

    def append_run_log(self, department: str, task_id: int, mode: str,
                       summary: str, files_changed: list, commit_hash: str,
                       status: str, duration_s: int, notes: str,
                       entry_hash: str, prev_hash: str,
                       created_at: str = None) -> int:
        ts = created_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO run_logs "
                "(department, task_id, mode, summary, files_changed, commit_hash, "
                " status, duration_s, notes, hash, prev_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (department, task_id, mode, summary,
                 json.dumps(files_changed, ensure_ascii=False),
                 commit_hash, status, duration_s, notes,
                 entry_hash, prev_hash, ts)
            )
            return cursor.lastrowid

    def get_recent_run_logs(self, department: str, n: int = 5) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_logs WHERE department = ? "
                "ORDER BY id DESC LIMIT ?",
                (department, n)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["files_changed"] = json.loads(d["files_changed"])
            result.append(d)
        result.reverse()
        return result

    def get_all_run_logs(self, department: str = None,
                         limit: int = 100) -> list:
        with self._connect() as conn:
            if department:
                rows = conn.execute(
                    "SELECT * FROM run_logs WHERE department = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (department, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM run_logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["files_changed"] = json.loads(d["files_changed"])
            result.append(d)
        return result

    def get_department_run_stats(self) -> dict:
        """返回每个部门的运行统计：总数、成功率、最近记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT department, COUNT(*) as total, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as success_count "
                "FROM run_logs GROUP BY department"
            ).fetchall()
        stats = {}
        for row in rows:
            d = dict(row)
            dept = d["department"]
            stats[dept] = {
                "total": d["total"],
                "success_count": d["success_count"],
                "success_rate": round(d["success_count"] / d["total"], 2) if d["total"] > 0 else 0,
            }
        return stats

    def get_last_run_hash(self, department: str = None) -> str:
        """获取最后一条 run_log 的 hash，用于构建哈希链。"""
        with self._connect() as conn:
            if department:
                row = conn.execute(
                    "SELECT hash FROM run_logs WHERE department = ? ORDER BY id DESC LIMIT 1",
                    (department,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT hash FROM run_logs ORDER BY id DESC LIMIT 1"
                ).fetchone()
        return row["hash"] if row else ""

    # ── Sub-runs (per-stage tracking) ──

    def create_sub_run(self, task_id: int, stage_name: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO sub_runs (task_id, stage_name, status, started_at, created_at) "
                "VALUES (?, ?, 'running', ?, ?)",
                (task_id, stage_name, now, now)
            )
            return cursor.lastrowid

    def finish_sub_run(self, sub_run_id: int, status: str,
                       duration_ms: int = 0, cost_usd: float = 0,
                       output_preview: str = ""):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sub_runs SET status = ?, finished_at = ?, "
                "duration_ms = ?, cost_usd = ?, output_preview = ? WHERE id = ?",
                (status, now, duration_ms, cost_usd, output_preview[:500], sub_run_id)
            )

    def get_sub_runs(self, task_id: int) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sub_runs WHERE task_id = ? ORDER BY id ASC",
                (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Experiences ──

    def add_experience(self, date: str, type: str, summary: str, detail: str, instance: str = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO experiences (date, type, summary, detail, instance, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (date, type, summary, detail, instance, now)
            )
            return cursor.lastrowid

    def get_recent_experiences(self, n: int = 10) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, type, summary, detail, instance FROM experiences "
                "ORDER BY date DESC, id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_experiences_by_type(self, type: str, n: int = 20) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, type, summary, detail, instance FROM experiences "
                "WHERE type = ? ORDER BY date DESC LIMIT ?",
                (type, n)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_experiences(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]

    # ── Agent Events ──

    def add_agent_event(self, task_id: int, event_type: str, data: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_events (task_id, event_type, data, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, json.dumps(data, ensure_ascii=False, default=str), now)
            )
            return cursor.lastrowid

    def get_agent_events(self, task_id: int, limit: int = 100) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, task_id, event_type, data, created_at FROM agent_events "
                "WHERE task_id = ? ORDER BY id ASC LIMIT ?",
                (task_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_live_agent_events(self, since_id: int = 0, limit: int = 50) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, task_id, event_type, data, created_at FROM agent_events "
                "WHERE id > ? ORDER BY id ASC LIMIT ?",
                (since_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Task Sessions (cross-heartbeat context recovery) ──

    def save_session(self, task_id: int, agent_id: str, session_data: dict):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_sessions "
                "(task_id, agent_id, session_data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, agent_id, json.dumps(session_data, ensure_ascii=False, default=str),
                 now, now)
            )

    def get_session(self, task_id: int, agent_id: str = "") -> dict:
        with self._connect() as conn:
            if agent_id:
                row = conn.execute(
                    "SELECT session_data FROM task_sessions "
                    "WHERE task_id = ? AND agent_id = ?",
                    (task_id, agent_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT session_data FROM task_sessions WHERE task_id = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (task_id,)
                ).fetchone()
        return json.loads(row["session_data"]) if row else {}

    # ── Heartbeats ──

    def record_heartbeat(self, task_id: int, agent_id: str = "",
                         status: str = "alive", progress_pct: int = 0,
                         message: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO heartbeats (task_id, agent_id, status, progress_pct, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, agent_id, status, progress_pct, message, now)
            )
            return cursor.lastrowid

    def get_last_heartbeat(self, task_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM heartbeats WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,)
            ).fetchone()
        return dict(row) if row else {}

    # ── File Index (CAFI) ──

    def upsert_file_index(self, path: str, routing_hint: str,
                          tags: list, embedding: list = None):
        now = datetime.now(timezone.utc).isoformat()
        emb_json = json.dumps(embedding) if embedding else None
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO file_index (path, routing_hint, tags, embedding, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, routing_hint, json.dumps(tags), emb_json, now)
            )

    def query_file_index(self, tags: list = None, limit: int = 20) -> list:
        with self._connect() as conn:
            if tags:
                # 简单 tag 匹配（JSON 字符串包含检查）
                placeholders = " OR ".join(["tags LIKE ?"] * len(tags))
                params = [f"%{t}%" for t in tags] + [limit]
                rows = conn.execute(
                    f"SELECT path, routing_hint, tags FROM file_index "
                    f"WHERE {placeholders} ORDER BY updated_at DESC LIMIT ?",
                    params
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path, routing_hint, tags FROM file_index "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]
