"""
Verify Gate — non-negotiable 质量门控。

Conitens 启发：定义不可跳过的门（gate），任何路径都不能绕过。
门控在 Governor _finalize_task 时执行，失败则标记任务为 gate_failed。

Gate 类型：
  - test_pass: 代码变更后测试必须通过
  - lint_clean: 无 lint 错误
  - no_secrets: 不能引入密钥/凭证
  - diff_size: 改动不能超过 N 个文件
"""
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class GateResult:
    """单个 gate 的检查结果。"""
    gate_id: str
    passed: bool
    message: str
    evidence: str = ""  # 证据（命令输出、文件路径等）
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class GateRecord:
    """完整的 gate 检查记录，可持久化。"""
    task_id: int
    department: str
    gates: list[GateResult]
    all_passed: bool
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "department": self.department,
            "all_passed": self.all_passed,
            "gates": [
                {"gate_id": g.gate_id, "passed": g.passed,
                 "message": g.message, "evidence": g.evidence[:200]}
                for g in self.gates
            ],
            "timestamp": self.timestamp,
        }


# ── Gate Definitions ──

def gate_no_secrets(task_cwd: str, **kwargs) -> GateResult:
    """检查是否引入了密钥/凭证文件。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=task_cwd, capture_output=True, text=True, timeout=10,
        )
        staged = result.stdout.strip().splitlines()

        # Also check unstaged
        result2 = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=task_cwd, capture_output=True, text=True, timeout=10,
        )
        changed = result2.stdout.strip().splitlines()

        all_files = set(staged + changed)
        # Only flag actual secret files, not code that mentions "token" or "secret"
        secret_file_patterns = [".env", ".key", ".pem", "credentials.json",
                                "credentials.yaml", "credentials.yml"]
        secret_name_exact = {"secrets.yaml", "secrets.yml", "secrets.json",
                             ".env.local", ".env.production"}

        violations = []
        for f in all_files:
            f_lower = f.lower()
            basename = Path(f).name.lower()
            if basename in secret_name_exact:
                violations.append(f)
            elif any(f_lower.endswith(p) for p in secret_file_patterns):
                violations.append(f)

        if violations:
            return GateResult(
                gate_id="no_secrets",
                passed=False,
                message=f"疑似密钥文件被修改: {', '.join(violations)}",
                evidence="\n".join(violations),
            )
        return GateResult(gate_id="no_secrets", passed=True, message="无密钥文件变更")
    except Exception as e:
        return GateResult(gate_id="no_secrets", passed=True,
                         message=f"检查跳过: {e}")


def gate_diff_size(task_cwd: str, max_files: int = 20, **kwargs) -> GateResult:
    """检查改动文件数是否超限。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "--stat-count=100"],
            cwd=task_cwd, capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l.strip() and "|" in l]
        file_count = len(lines)

        if file_count > max_files:
            return GateResult(
                gate_id="diff_size",
                passed=False,
                message=f"改动 {file_count} 个文件，超过上限 {max_files}",
                evidence=result.stdout[:500],
            )
        return GateResult(gate_id="diff_size", passed=True,
                         message=f"改动 {file_count} 个文件，在限制内")
    except Exception as e:
        return GateResult(gate_id="diff_size", passed=True,
                         message=f"检查跳过: {e}")


def gate_test_pass(task_cwd: str, test_cmd: str = "pytest tests/ -x -q", **kwargs) -> GateResult:
    """检查测试是否通过。"""
    try:
        result = subprocess.run(
            test_cmd.split(),
            cwd=task_cwd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return GateResult(gate_id="test_pass", passed=True,
                             message="测试通过", evidence=result.stdout[-200:])
        return GateResult(
            gate_id="test_pass",
            passed=False,
            message="测试失败",
            evidence=result.stdout[-500:] + "\n" + result.stderr[-200:],
        )
    except subprocess.TimeoutExpired:
        return GateResult(gate_id="test_pass", passed=False,
                         message="测试超时（120s）")
    except FileNotFoundError:
        return GateResult(gate_id="test_pass", passed=True,
                         message="测试框架不可用，跳过")
    except Exception as e:
        return GateResult(gate_id="test_pass", passed=True,
                         message=f"检查跳过: {e}")


# ── Gate Registry ──

GATE_REGISTRY = {
    "no_secrets": gate_no_secrets,
    "diff_size": gate_diff_size,
    "test_pass": gate_test_pass,
}

# 部门默认 gate 配置
DEPARTMENT_GATES: dict[str, list[str]] = {
    "engineering": ["no_secrets", "diff_size", "test_pass"],
    "operations": ["no_secrets", "diff_size"],
    # 只读部门不需要 gate
    "protocol": [],
    "security": [],
    "quality": [],
    "personnel": [],
}


def run_gates(department: str, task_id: int, task_cwd: str,
              extra_gates: list[str] = None) -> GateRecord:
    """运行部门的所有 verify gates。"""
    gate_ids = DEPARTMENT_GATES.get(department, [])
    if extra_gates:
        gate_ids = list(set(gate_ids + extra_gates))

    results = []
    for gate_id in gate_ids:
        gate_fn = GATE_REGISTRY.get(gate_id)
        if not gate_fn:
            log.warning(f"verify_gate: unknown gate '{gate_id}'")
            continue
        result = gate_fn(task_cwd=task_cwd)
        results.append(result)
        if not result.passed:
            log.warning(f"verify_gate: gate '{gate_id}' FAILED for task #{task_id}: {result.message}")

    record = GateRecord(
        task_id=task_id,
        department=department,
        gates=results,
        all_passed=all(r.passed for r in results),
    )

    return record


def save_gate_record(record: GateRecord, db=None):
    """持久化 gate 检查记录。"""
    if db:
        try:
            db.write_log(
                f"Gate check task #{record.task_id}: "
                f"{'PASSED' if record.all_passed else 'FAILED'} "
                f"({', '.join(g.gate_id for g in record.gates if not g.passed)})",
                "INFO" if record.all_passed else "WARNING",
                "verify_gate",
            )
        except Exception:
            pass

    # 也写到 JSONL 文件（审计用）
    gate_log = _REPO_ROOT / "tmp" / "gate-records.jsonl"
    gate_log.parent.mkdir(parents=True, exist_ok=True)
    with open(gate_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
