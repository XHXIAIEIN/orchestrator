"""
TokenAccountant — 预算降级链。

Lucentia 启发：每个部门日预算 + 单任务上限，超预算自动降级模型而非拒绝。

预算层级：
  月度总额 → 部门日额 → 单任务上限
超预算时，按降级链自动切换更便宜的模型。
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    """预算配置。"""
    monthly_total_usd: float = 50.0     # 月度总额
    daily_per_dept_usd: float = 5.0     # 部门日额
    per_task_max_usd: float = 1.0       # 单任务上限


# 降级链：从贵到便宜
MODEL_DOWNGRADE_CHAIN = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]


@dataclass
class UsageRecord:
    """单次使用记录。"""
    task_id: int
    department: str
    model: str
    cost_usd: float
    timestamp: str


@dataclass
class BudgetState:
    """当前预算状态。"""
    config: BudgetConfig = field(default_factory=BudgetConfig)
    records: list[UsageRecord] = field(default_factory=list)

    @property
    def monthly_spent(self) -> float:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return sum(
            r.cost_usd for r in self.records
            if r.timestamp >= month_start.isoformat()
        )

    @property
    def monthly_remaining(self) -> float:
        return max(0, self.config.monthly_total_usd - self.monthly_spent)

    def daily_spent(self, department: str) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(
            r.cost_usd for r in self.records
            if r.department == department and r.timestamp[:10] == today
        )

    def daily_remaining(self, department: str) -> float:
        return max(0, self.config.daily_per_dept_usd - self.daily_spent(department))


class TokenAccountant:
    """预算管理器。跟踪 token 消耗，超预算时推荐降级模型。"""

    def __init__(self, db=None):
        self._db = db
        self.config = BudgetConfig()
        self.state = BudgetState(config=self.config)
        self._load_history()

    def _load_history(self):
        """从 agent_events 表加载最近的成本数据。"""
        if not self._db:
            return
        try:
            # 取最近 30 天的 agent_result 事件
            since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            with self._db._connect() as conn:
                rows = conn.execute(
                    "SELECT ae.task_id, ae.data, ae.created_at, "
                    "json_extract(t.spec, '$.department') as department "
                    "FROM agent_events ae "
                    "LEFT JOIN tasks t ON ae.task_id = t.id "
                    "WHERE ae.event_type = 'agent_result' AND ae.created_at >= ?",
                    (since,)
                ).fetchall()

            for row in rows:
                try:
                    data = json.loads(row["data"])
                    cost = data.get("cost_usd", 0) or 0
                    if cost > 0:
                        self.state.records.append(UsageRecord(
                            task_id=row["task_id"],
                            department=row["department"] or "unknown",
                            model="unknown",
                            cost_usd=cost,
                            timestamp=row["created_at"],
                        ))
                except (json.JSONDecodeError, TypeError):
                    continue

            log.info(f"token_budget: loaded {len(self.state.records)} cost records")
        except Exception as e:
            log.warning(f"token_budget: failed to load history: {e}")

    def record_usage(self, task_id: int, department: str, model: str, cost_usd: float):
        """记录一次使用。"""
        self.state.records.append(UsageRecord(
            task_id=task_id,
            department=department,
            model=model,
            cost_usd=cost_usd,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def recommend_model(self, department: str, preferred_model: str) -> str:
        """根据预算状态推荐模型。超预算时自动降级。

        Returns: 推荐使用的模型 ID
        """
        # 月度总额检查
        if self.state.monthly_remaining <= 0:
            log.warning(f"token_budget: monthly budget exhausted, forcing cheapest model")
            return MODEL_DOWNGRADE_CHAIN[-1]

        # 部门日额检查
        daily_remaining = self.state.daily_remaining(department)
        if daily_remaining <= 0:
            log.info(f"token_budget: {department} daily budget exhausted, downgrading model")
            return _downgrade(preferred_model)

        # 日额低于 20%，预防性降级
        if daily_remaining < self.config.daily_per_dept_usd * 0.2:
            log.info(f"token_budget: {department} daily budget low ({daily_remaining:.2f}), downgrading")
            return _downgrade(preferred_model)

        return preferred_model

    def get_summary(self) -> dict:
        """返回预算摘要。"""
        depts = set(r.department for r in self.state.records)
        dept_daily = {d: self.state.daily_spent(d) for d in depts}

        return {
            "monthly_total": self.config.monthly_total_usd,
            "monthly_spent": round(self.state.monthly_spent, 4),
            "monthly_remaining": round(self.state.monthly_remaining, 4),
            "daily_per_dept": self.config.daily_per_dept_usd,
            "dept_today": dept_daily,
            "total_records": len(self.state.records),
        }


def _downgrade(model: str) -> str:
    """在降级链中找到下一个更便宜的模型。"""
    try:
        idx = MODEL_DOWNGRADE_CHAIN.index(model)
        if idx < len(MODEL_DOWNGRADE_CHAIN) - 1:
            downgraded = MODEL_DOWNGRADE_CHAIN[idx + 1]
            log.info(f"token_budget: downgrading {model} → {downgraded}")
            return downgraded
    except ValueError:
        pass
    # 已经是最便宜的，或不在链中
    return MODEL_DOWNGRADE_CHAIN[-1]
