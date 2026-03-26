"""Tasks-related methods for EventsDB."""
import json
import logging
from datetime import datetime, timezone, timedelta


_ALLOWED_TASK_COLUMNS = {
    'spec', 'action', 'reason', 'priority', 'source',
    'status', 'output', 'approved_at', 'started_at', 'finished_at',
    'scrutiny_note', 'parent_task_id',
}

_log = logging.getLogger(__name__)

# ── Watchdog Configuration (stolen from agent-lightning Round 8) ──
# Embedded health detection: piggyback on write operations, zero extra threads.
_WATCHDOG_TIMEOUT_MINUTES = 15       # Task running longer than this → timeout
_WATCHDOG_HEARTBEAT_MINUTES = 10     # No heartbeat for this long → unresponsive
_WATCHDOG_SCAN_INTERVAL_S = 30       # Minimum seconds between scans (debounce)
_watchdog_last_scan = None           # Timestamp of last watchdog scan


class TasksMixin:

    def create_task(self, action: str, reason: str, priority: str,
                    spec: dict, source: str = 'auto',
                    parent_task_id: int = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        status = 'pending' if source == 'auto' else 'awaiting_approval'
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO tasks (spec, action, reason, priority, source, status, created_at, parent_task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (json.dumps(spec, ensure_ascii=False, default=str), action, reason, priority, source, status, now,
                 parent_task_id)
            )
            return cur.lastrowid

    def update_task(self, task_id: int, **kwargs):
        if not kwargs:
            return
        invalid = set(kwargs) - _ALLOWED_TASK_COLUMNS
        if invalid:
            raise ValueError(f"Invalid task columns: {invalid}")
        sets = ', '.join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [task_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", vals)

        # ── Watchdog: piggyback scan on write ops ──
        self._watchdog_scan(exclude_task_id=task_id)

    def get_tasks(self, limit: int = 50) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d['spec'] = json.loads(d['spec'])
            result.append(d)
        return result

    def get_task(self, task_id: int):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['spec'] = json.loads(d['spec'])
        return d

    def get_running_task(self):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('running', 'scrutinizing') LIMIT 1"
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d['spec'] = json.loads(d['spec'])
        return d

    def get_running_tasks(self) -> list:
        """返回所有正在运行或审查中的任务。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('running', 'scrutinizing')"
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d['spec'] = json.loads(d['spec'])
            result.append(d)
        return result

    def count_running_tasks(self) -> int:
        """返回正在运行的任务数。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('running', 'scrutinizing')"
            ).fetchone()
        return row[0]

    # ── Watchdog: Embedded Health Detection ──
    # Stolen from agent-lightning (Round 8): instead of a dedicated watchdog thread,
    # we piggyback on existing write operations. Every update_task() call triggers a
    # debounced scan for stuck/unresponsive tasks. Zero overhead when nothing is stuck.

    def _watchdog_scan(self, exclude_task_id: int = None):
        """Scan for timed-out / unresponsive tasks. Debounced to avoid hot-path cost."""
        global _watchdog_last_scan
        now = datetime.now(timezone.utc)

        # Debounce: skip if last scan was < N seconds ago
        if _watchdog_last_scan and (now - _watchdog_last_scan).total_seconds() < _WATCHDOG_SCAN_INTERVAL_S:
            return
        _watchdog_last_scan = now

        timeout_cutoff = (now - timedelta(minutes=_WATCHDOG_TIMEOUT_MINUTES)).isoformat()
        reaped = []

        try:
            with self._connect() as conn:
                # 1. Timeout detection: running tasks past deadline
                stuck_rows = conn.execute(
                    "SELECT id, action, started_at FROM tasks "
                    "WHERE status = 'running' AND started_at < ?",
                    (timeout_cutoff,)
                ).fetchall()

                for row in stuck_rows:
                    tid = row['id'] if isinstance(row, dict) else row[0]
                    if tid == exclude_task_id:
                        continue  # Don't reap the task being updated right now

                    started = row['started_at'] if isinstance(row, dict) else row[2]
                    action = row['action'] if isinstance(row, dict) else row[1]
                    minutes = (now - datetime.fromisoformat(started)).total_seconds() / 60

                    # 2. Heartbeat check: was there a recent heartbeat?
                    hb = conn.execute(
                        "SELECT created_at FROM heartbeats WHERE task_id = ? "
                        "ORDER BY id DESC LIMIT 1",
                        (tid,)
                    ).fetchone()

                    if hb:
                        hb_time = hb['created_at'] if isinstance(hb, dict) else hb[0]
                        hb_age = (now - datetime.fromisoformat(hb_time)).total_seconds() / 60
                        if hb_age < _WATCHDOG_HEARTBEAT_MINUTES:
                            # Recent heartbeat — task is alive, just slow
                            continue
                        tag = f"UNRESPONSIVE: no heartbeat for {hb_age:.0f}m"
                    else:
                        tag = f"TIMEOUT: running for {minutes:.0f}m with no heartbeats"

                    # Reap it
                    conn.execute(
                        "UPDATE tasks SET status = 'failed', output = ?, finished_at = ? "
                        "WHERE id = ? AND status = 'running'",
                        (f"[WATCHDOG: {tag}]", now.isoformat(), tid)
                    )
                    reaped.append((tid, tag, action))

        except Exception as e:
            _log.debug(f"Watchdog scan error: {e}")
            return

        for tid, tag, action in reaped:
            _log.warning(f"Watchdog reaped task #{tid} ({action[:50]}): {tag}")
