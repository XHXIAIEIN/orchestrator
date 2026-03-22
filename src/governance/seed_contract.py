"""
Seed Contract — 部门声明式依赖图。

organvm 启发：每个部门 YAML 声明 produces/consumes/subscriptions，
事件路由从声明生成。

用途：
  - 自动发现部门间依赖关系
  - 任务派单时检查前置依赖是否满足
  - Dashboard 展示部门协作图
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEPT_ROOT = _REPO_ROOT / "departments"


@dataclass
class SeedContract:
    """部门的种子合约。"""
    department: str
    produces: list[str] = field(default_factory=list)     # 产出事件/数据
    consumes: list[str] = field(default_factory=list)     # 消费事件/数据
    subscriptions: list[str] = field(default_factory=list)  # 订阅的事件总线事件


# 内置合约定义（可被 blueprint.yaml 的 contract 字段覆盖）
BUILTIN_CONTRACTS: dict[str, SeedContract] = {
    "engineering": SeedContract(
        department="engineering",
        produces=["code_change", "commit", "fix_applied"],
        consumes=["task_spec", "review_feedback", "rework_request"],
        subscriptions=["task.assigned.engineering", "review.failed"],
    ),
    "operations": SeedContract(
        department="operations",
        produces=["collector_repair", "config_update", "health_report"],
        consumes=["collector_failure", "health_check_request"],
        subscriptions=["collector.failed", "task.assigned.operations"],
    ),
    "protocol": SeedContract(
        department="protocol",
        produces=["debt_scan_result", "attention_audit", "scout_report"],
        consumes=["scan_request"],
        subscriptions=["task.assigned.protocol", "schedule.debt_scan"],
    ),
    "security": SeedContract(
        department="security",
        produces=["vulnerability_report", "secret_scan_result"],
        consumes=["scan_request", "code_change"],
        subscriptions=["task.assigned.security", "code_change"],
    ),
    "quality": SeedContract(
        department="quality",
        produces=["review_result", "test_report", "verdict"],
        consumes=["code_change", "commit", "review_request"],
        subscriptions=["task.assigned.quality", "task.completed.engineering"],
    ),
    "personnel": SeedContract(
        department="personnel",
        produces=["performance_report", "trend_analysis"],
        consumes=["run_logs", "task_history"],
        subscriptions=["task.assigned.personnel", "schedule.performance"],
    ),
}


def load_contract(department: str) -> SeedContract:
    """加载部门合约。优先从 blueprint.yaml 读取，fallback 到内置。"""
    bp_path = _DEPT_ROOT / department / "blueprint.yaml"
    if bp_path.exists():
        try:
            raw = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
            contract_raw = raw.get("contract") if raw else None
            if contract_raw and isinstance(contract_raw, dict):
                return SeedContract(
                    department=department,
                    produces=contract_raw.get("produces", []),
                    consumes=contract_raw.get("consumes", []),
                    subscriptions=contract_raw.get("subscriptions", []),
                )
        except Exception:
            pass

    return BUILTIN_CONTRACTS.get(department, SeedContract(department=department))


def load_all_contracts() -> dict[str, SeedContract]:
    """加载所有部门合约。"""
    contracts = {}
    for dept in BUILTIN_CONTRACTS:
        contracts[dept] = load_contract(dept)
    return contracts


def get_dependency_graph() -> dict:
    """生成部门依赖图。返回 {dept: {upstream: [...], downstream: [...]}}。"""
    contracts = load_all_contracts()
    graph = {dept: {"upstream": [], "downstream": []} for dept in contracts}

    for dept, contract in contracts.items():
        for other_dept, other_contract in contracts.items():
            if dept == other_dept:
                continue
            # dept consumes what other produces → other is upstream
            overlap = set(contract.consumes) & set(other_contract.produces)
            if overlap:
                graph[dept]["upstream"].append({"dept": other_dept, "data": list(overlap)})
                graph[other_dept]["downstream"].append({"dept": dept, "data": list(overlap)})

    return graph


def check_dependencies_met(department: str, available_data: list[str]) -> tuple[bool, list[str]]:
    """检查部门的前置依赖是否满足。"""
    contract = load_contract(department)
    missing = [c for c in contract.consumes if c not in available_data]
    return len(missing) == 0, missing
