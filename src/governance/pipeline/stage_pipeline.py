"""
Stage Pipeline — 可配置的执行阶段序列。

bored 启发：workflow 拆成可配置 stage 序列，每个 stage 是一个 .md prompt，
扩展 = 加文件。

当前 Governor 的五阶段（Resolve→Verify→Plan→Apply→Status）是硬编码的。
Stage Pipeline 让部门可以通过 blueprint.yaml 声明自定义 stage 序列。

例如：engineering 的 pipeline 可以是：
  preflight → scrutiny → execute → test → review

而 protocol 的 pipeline 是：
  preflight → execute → report

每个 stage 可以有：
  - name: 阶段名
  - type: builtin（内置）或 prompt（从 .md 文件加载）
  - skip_if: 跳过条件
  - on_fail: 失败策略
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


@dataclass
class Stage:
    """单个执行阶段。"""
    name: str
    type: str = "builtin"      # builtin | prompt | gate
    prompt_file: str = ""      # type=prompt 时，.md 文件路径
    skip_if: str = ""          # 跳过条件：read_only, no_tests, scout_task
    on_fail: str = "abort"     # abort | continue | retry | escalate
    timeout_s: int = 0         # 0 = 继承全局


@dataclass
class Pipeline:
    """完整的执行管线。"""
    department: str
    stages: list[Stage] = field(default_factory=list)


# ── 默认 pipeline 定义 ──
# 可以被 blueprint.yaml 中的 pipeline 字段覆盖

DEFAULT_PIPELINES: dict[str, list[Stage]] = {
    "engineering": [
        Stage("preflight", "builtin"),
        Stage("novelty_check", "builtin", skip_if="rework_task"),
        Stage("scrutiny", "builtin"),
        Stage("execute", "builtin"),
        Stage("verify_gates", "gate"),
        Stage("deslop", "builtin"),
        Stage("quality_review", "builtin", skip_if="scout_task"),
    ],
    "operations": [
        Stage("preflight", "builtin"),
        Stage("scrutiny", "builtin"),
        Stage("execute", "builtin"),
        Stage("verify_gates", "gate"),
    ],
    "protocol": [
        Stage("preflight", "builtin"),
        Stage("execute", "builtin"),
    ],
    "security": [
        Stage("preflight", "builtin"),
        Stage("execute", "builtin"),
    ],
    "quality": [
        Stage("preflight", "builtin"),
        Stage("execute", "builtin"),
    ],
    "personnel": [
        Stage("preflight", "builtin"),
        Stage("execute", "builtin"),
    ],
}


def get_pipeline(department: str, blueprint=None) -> Pipeline:
    """获取部门的执行管线。优先用 blueprint 配置，fallback 到默认。"""
    # 尝试从 blueprint 加载自定义 pipeline
    if blueprint and hasattr(blueprint, 'extra') and blueprint.extra.get('pipeline'):
        stages = _parse_pipeline_config(blueprint.extra['pipeline'])
        if stages:
            return Pipeline(department=department, stages=stages)

    # Fallback 到默认
    default_stages = DEFAULT_PIPELINES.get(department, DEFAULT_PIPELINES["protocol"])
    return Pipeline(department=department, stages=list(default_stages))


def _parse_pipeline_config(raw: list) -> list[Stage]:
    """解析 blueprint.yaml 中的 pipeline 配置。"""
    if not raw:
        return []

    stages = []
    for item in raw:
        if isinstance(item, str):
            stages.append(Stage(name=item))
        elif isinstance(item, dict):
            stages.append(Stage(
                name=item.get("name", "unknown"),
                type=item.get("type", "builtin"),
                prompt_file=item.get("prompt_file", ""),
                skip_if=item.get("skip_if", ""),
                on_fail=item.get("on_fail", "abort"),
                timeout_s=item.get("timeout_s", 0),
            ))
    return stages


def should_skip_stage(stage: Stage, task_spec: dict) -> bool:
    """判断是否应该跳过某个 stage。"""
    if not stage.skip_if:
        return False

    skip_conditions = {
        "read_only": lambda s: s.get("department") in ("protocol", "security", "quality", "personnel"),
        "no_tests": lambda s: not _has_tests(s.get("cwd", "")),
        "scout_task": lambda s: s.get("is_scout", False),
        "rework_task": lambda s: s.get("rework_count", 0) > 0,
    }

    checker = skip_conditions.get(stage.skip_if)
    if checker:
        return checker(task_spec)

    return False


def _has_tests(cwd: str) -> bool:
    """检查项目是否有测试文件。"""
    if not cwd:
        return False
    test_dirs = [Path(cwd) / "tests", Path(cwd) / "test"]
    return any(d.exists() for d in test_dirs)


def has_stage(department: str, stage_name: str, blueprint=None) -> bool:
    """Check if a department's pipeline includes a given stage."""
    pipeline = get_pipeline(department, blueprint)
    return any(s.name == stage_name for s in pipeline.stages)


def format_pipeline_status(pipeline: Pipeline, completed: list[str],
                            current: str = "", failed: str = "") -> str:
    """格式化 pipeline 执行状态（用于日志/dashboard）。"""
    lines = [f"Pipeline: {pipeline.department}"]
    for stage in pipeline.stages:
        if stage.name in completed:
            mark = "✅"
        elif stage.name == current:
            mark = "🔄"
        elif stage.name == failed:
            mark = "❌"
        else:
            mark = "⬜"
        lines.append(f"  {mark} {stage.name}")
    return "\n".join(lines)
