"""Agent Cron — 部门级定时执行调度器。

LobeHub Round 16 P0 #5: 每个部门可通过 blueprint.yaml 的 cron_jobs 字段
声明自己的定时任务，AgentCronScheduler 统一管理。

存储: SQLite (data/agent_cron.db)
Cron 解析: 自实现（不依赖 croniter），支持标准 5 字段格式。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DEPARTMENTS_DIR = BASE_DIR / "departments"

# ---------------------------------------------------------------------------
# Cron expression parser (5-field: min hour dom month dow)
# ---------------------------------------------------------------------------

_DOW_MAP = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_field(token: str, lo: int, hi: int, aliases: dict[str, int] | None = None) -> set[int]:
    """Parse a single cron field token into a set of valid integer values."""
    result: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if aliases:
            for name, val in aliases.items():
                part = part.replace(name, str(val))

        # Handle step: */n or range/n
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)

        if part == "*":
            result.update(range(lo, hi + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            result.update(range(int(a), int(b) + 1, step))
        else:
            result.add(int(part))

    return {v for v in result if lo <= v <= hi}


def cron_matches(expression: str, dt: datetime) -> bool:
    """Check if *dt* matches a 5-field cron expression (minute hour dom month dow)."""
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {expression!r}")

    minutes = _parse_field(parts[0], 0, 59)
    hours = _parse_field(parts[1], 0, 23)
    doms = _parse_field(parts[2], 1, 31)
    months = _parse_field(parts[3], 1, 12, _MONTH_MAP)
    dows = _parse_field(parts[4], 0, 6, _DOW_MAP)

    # Python weekday: Monday=0 … Sunday=6  →  cron: Sunday=0 … Saturday=6
    cron_dow = (dt.weekday() + 1) % 7

    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in doms
        and dt.month in months
        and cron_dow in dows
    )


# ---------------------------------------------------------------------------
# CronJob dataclass
# ---------------------------------------------------------------------------

@dataclass
class CronJob:
    department: str
    name: str
    cron_expression: str
    payload: dict = field(default_factory=dict)
    max_executions: Optional[int] = None
    remaining_executions: Optional[int] = None
    execution_conditions: dict = field(default_factory=dict)
    enabled: bool = True
    last_executed_at: Optional[datetime] = None

    @property
    def job_id(self) -> str:
        return f"{self.department}:{self.name}"

    def is_expired(self) -> bool:
        """True if max_executions was set and remaining is 0."""
        if self.max_executions is None:
            return False
        return (self.remaining_executions or 0) <= 0


# ---------------------------------------------------------------------------
# AgentCronScheduler
# ---------------------------------------------------------------------------

class AgentCronScheduler:
    """SQLite-backed cron scheduler for department-level recurring tasks."""

    DDL = """
    CREATE TABLE IF NOT EXISTS cron_jobs (
        department   TEXT NOT NULL,
        name         TEXT NOT NULL,
        cron_expression TEXT NOT NULL,
        payload      TEXT NOT NULL DEFAULT '{}',
        max_executions INTEGER,
        remaining_executions INTEGER,
        execution_conditions TEXT NOT NULL DEFAULT '{}',
        enabled      INTEGER NOT NULL DEFAULT 1,
        last_executed_at TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (department, name)
    );
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = DATA_DIR / "agent_cron.db"
        self._db_path = str(db_path)
        self._init_db()

    # -- DB helpers ----------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(self.DDL)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> CronJob:
        last = row["last_executed_at"]
        return CronJob(
            department=row["department"],
            name=row["name"],
            cron_expression=row["cron_expression"],
            payload=json.loads(row["payload"]),
            max_executions=row["max_executions"],
            remaining_executions=row["remaining_executions"],
            execution_conditions=json.loads(row["execution_conditions"]),
            enabled=bool(row["enabled"]),
            last_executed_at=datetime.fromisoformat(last) if last else None,
        )

    # -- Public API ----------------------------------------------------------

    def register(self, job: CronJob) -> None:
        """Register (upsert) a cron job."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO cron_jobs
                    (department, name, cron_expression, payload,
                     max_executions, remaining_executions, execution_conditions,
                     enabled, last_executed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(department, name) DO UPDATE SET
                    cron_expression = excluded.cron_expression,
                    payload = excluded.payload,
                    max_executions = excluded.max_executions,
                    remaining_executions = excluded.remaining_executions,
                    execution_conditions = excluded.execution_conditions,
                    enabled = excluded.enabled,
                    updated_at = datetime('now')
                """,
                (
                    job.department,
                    job.name,
                    job.cron_expression,
                    json.dumps(job.payload, ensure_ascii=False),
                    job.max_executions,
                    job.remaining_executions,
                    json.dumps(job.execution_conditions, ensure_ascii=False),
                    int(job.enabled),
                    job.last_executed_at.isoformat() if job.last_executed_at else None,
                ),
            )
        log.info("Registered cron job %s:%s [%s]", job.department, job.name, job.cron_expression)

    def unregister(self, department: str, name: str) -> bool:
        """Remove a cron job. Returns True if a row was deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM cron_jobs WHERE department = ? AND name = ?",
                (department, name),
            )
        deleted = cur.rowcount > 0
        if deleted:
            log.info("Unregistered cron job %s:%s", department, name)
        return deleted

    def list_jobs(self, department: str | None = None) -> list[CronJob]:
        """List all jobs, optionally filtered by department."""
        with self._conn() as conn:
            if department:
                rows = conn.execute(
                    "SELECT * FROM cron_jobs WHERE department = ? ORDER BY name",
                    (department,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cron_jobs ORDER BY department, name"
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def check_due(self, now: datetime | None = None) -> list[CronJob]:
        """Return jobs that should fire at *now* (default: current UTC minute).

        A job is due when:
        1. enabled = True
        2. cron_expression matches *now*
        3. Not expired (remaining_executions > 0 or unlimited)
        4. execution_conditions are met (placeholder — always True for now)
        """
        if now is None:
            now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        due: list[CronJob] = []
        for job in self.list_jobs():
            if not job.enabled:
                continue
            if job.is_expired():
                continue
            try:
                if not cron_matches(job.cron_expression, now):
                    continue
            except ValueError as e:
                log.warning("Bad cron expression for %s: %s", job.job_id, e)
                continue
            # Condition check — extensible hook point
            if not self._check_conditions(job):
                continue
            due.append(job)
        return due

    def mark_executed(self, department: str, name: str, at: datetime | None = None) -> None:
        """Record execution: update last_executed_at, decrement remaining."""
        if at is None:
            at = datetime.now(timezone.utc)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE cron_jobs
                SET last_executed_at = ?,
                    remaining_executions = CASE
                        WHEN remaining_executions IS NOT NULL
                        THEN MAX(remaining_executions - 1, 0)
                        ELSE NULL
                    END,
                    updated_at = datetime('now')
                WHERE department = ? AND name = ?
                """,
                (at.isoformat(), department, name),
            )
        log.info("Marked executed: %s:%s at %s", department, name, at.isoformat())

    # -- Blueprint loading ---------------------------------------------------

    def load_from_blueprints(self, departments_dir: Path | None = None) -> list[CronJob]:
        """Scan all departments' blueprint.yaml for `cron_jobs` and register them.

        Blueprint cron_jobs format:
            cron_jobs:
              - name: daily_performance_review
                cron: "0 9 * * *"
                payload: {action: "review_performance"}
                max_executions: null
                conditions: {min_events: 5}

        Returns list of registered CronJobs.
        """
        root = departments_dir or DEPARTMENTS_DIR
        loaded: list[CronJob] = []

        if not root.is_dir():
            log.warning("Departments directory not found: %s", root)
            return loaded

        for bp_path in sorted(root.glob("*/blueprint.yaml")):
            dept_name = bp_path.parent.name
            try:
                data = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
            except Exception as e:
                log.warning("Failed to parse %s: %s", bp_path, e)
                continue

            cron_entries = data.get("cron_jobs")
            if not cron_entries:
                continue

            for entry in cron_entries:
                if not isinstance(entry, dict) or "name" not in entry or "cron" not in entry:
                    log.warning("Invalid cron_jobs entry in %s: %s", bp_path, entry)
                    continue

                max_exec = entry.get("max_executions")
                job = CronJob(
                    department=dept_name,
                    name=entry["name"],
                    cron_expression=entry["cron"],
                    payload=entry.get("payload", {}),
                    max_executions=max_exec,
                    remaining_executions=max_exec,
                    execution_conditions=entry.get("conditions", {}),
                    enabled=entry.get("enabled", True),
                )
                self.register(job)
                loaded.append(job)

        log.info("Loaded %d cron jobs from blueprints", len(loaded))
        return loaded

    # -- Condition checking (extensible) -------------------------------------

    @staticmethod
    def _check_conditions(job: CronJob) -> bool:
        """Evaluate execution_conditions. Returns True if all conditions met.

        Supported conditions (extensible):
        - min_events: int — placeholder, always True until EventsDB integration
        """
        # No conditions → always eligible
        if not job.execution_conditions:
            return True

        # Future: plug in EventsDB queries, system state checks, etc.
        # For now all conditions pass — the structure is in place for wiring.
        return True
