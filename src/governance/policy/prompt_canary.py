"""
Canary/Shadow Prompt 部署 — prompt 迭代时 A/B 测试。

Ferment 启发：prompt 迭代时 canary 分流，shadow 模式对比新旧效果。

两种模式：
  1. Canary: 一部分任务用新 prompt，其余用旧 prompt。按比例分流。
  2. Shadow: 所有任务同时用新旧 prompt 执行，对比结果但只采纳旧 prompt 的输出。

用例：
  - 部门 SKILL.md 更新时，先 canary 测试新版本
  - 认知模式 prompt 调整时，shadow 比较新旧效果
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
CANARY_CONFIG_PATH = _REPO_ROOT / "departments" / "shared" / "canary.yaml"


@dataclass
class CanaryConfig:
    """Canary 配置。"""
    enabled: bool = False
    department: str = ""       # 哪个部门在做 canary
    new_prompt_path: str = ""  # 新 prompt 文件路径
    traffic_pct: int = 20     # 新 prompt 分流比例（0-100）
    started_at: str = ""
    results: list = field(default_factory=list)


@dataclass
class CanaryResult:
    """单次 canary 执行结果。"""
    task_id: int
    variant: str  # "canary" or "control"
    status: str   # "done" or "failed"
    output_preview: str
    duration_s: int
    timestamp: str


def load_canary_config() -> CanaryConfig:
    """加载 canary 配置。"""
    if not CANARY_CONFIG_PATH.exists():
        return CanaryConfig()

    try:
        import yaml
        raw = yaml.safe_load(CANARY_CONFIG_PATH.read_text(encoding="utf-8"))
        if not raw or not isinstance(raw, dict):
            return CanaryConfig()

        return CanaryConfig(
            enabled=raw.get("enabled", False),
            department=raw.get("department", ""),
            new_prompt_path=raw.get("new_prompt_path", ""),
            traffic_pct=raw.get("traffic_pct", 20),
            started_at=raw.get("started_at", ""),
        )
    except Exception as e:
        log.warning(f"canary: failed to load config: {e}")
        return CanaryConfig()


def should_use_canary(task_id: int, department: str) -> bool:
    """判断该任务是否应该使用 canary prompt。

    基于 task_id 的确定性哈希，保证同一任务每次都走相同路径。
    """
    config = load_canary_config()
    if not config.enabled or config.department != department:
        return False

    # 确定性分流：hash(task_id) % 100 < traffic_pct
    h = hashlib.md5(str(task_id).encode()).hexdigest()
    bucket = int(h[:8], 16) % 100
    return bucket < config.traffic_pct


def get_canary_prompt(department: str) -> Optional[str]:
    """获取 canary 版本的 prompt。如果没有 canary 配置则返回 None。"""
    config = load_canary_config()
    if not config.enabled or not config.new_prompt_path:
        return None

    prompt_path = _REPO_ROOT / config.new_prompt_path
    if not prompt_path.exists():
        log.warning(f"canary: new prompt path not found: {prompt_path}")
        return None

    return prompt_path.read_text(encoding="utf-8")


def record_canary_result(task_id: int, variant: str, status: str,
                          output: str, duration_s: int):
    """记录 canary 执行结果。"""
    result = CanaryResult(
        task_id=task_id,
        variant=variant,
        status=status,
        output_preview=output[:200],
        duration_s=duration_s,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # 追加到 canary 结果文件
    results_path = _REPO_ROOT / "tmp" / "canary-results.jsonl"
    results_path.parent.mkdir(parents=True, exist_ok=True)

    with open(results_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "task_id": result.task_id,
            "variant": result.variant,
            "status": result.status,
            "output_preview": result.output_preview,
            "duration_s": result.duration_s,
            "timestamp": result.timestamp,
        }, ensure_ascii=False) + "\n")

    log.info(f"canary: recorded {variant} result for task #{task_id}: {status}")


def get_canary_summary() -> dict:
    """汇总 canary 测试结果。"""
    results_path = _REPO_ROOT / "tmp" / "canary-results.jsonl"
    if not results_path.exists():
        return {"total": 0, "canary": {}, "control": {}}

    canary_results = {"total": 0, "done": 0, "failed": 0, "avg_duration": 0}
    control_results = {"total": 0, "done": 0, "failed": 0, "avg_duration": 0}

    durations = {"canary": [], "control": []}

    for line in results_path.read_text(encoding="utf-8").strip().splitlines():
        try:
            r = json.loads(line)
            variant = r.get("variant", "")
            status = r.get("status", "")
            duration = r.get("duration_s", 0)

            target = canary_results if variant == "canary" else control_results
            target["total"] += 1
            if status == "done":
                target["done"] += 1
            else:
                target["failed"] += 1
            durations[variant].append(duration)
        except json.JSONDecodeError:
            continue

    for variant in ["canary", "control"]:
        target = canary_results if variant == "canary" else control_results
        if durations[variant]:
            target["avg_duration"] = round(sum(durations[variant]) / len(durations[variant]), 1)

    return {
        "total": canary_results["total"] + control_results["total"],
        "canary": canary_results,
        "control": control_results,
    }
