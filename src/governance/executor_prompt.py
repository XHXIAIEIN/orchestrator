"""Executor Prompt Builder — assemble the full prompt for task execution."""
import logging

from src.governance.scrutiny import classify_cognitive_mode
from src.governance.policy.blueprint import AuthorityCeiling
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS,
    load_department, load_prompt,
)
from src.governance.context.context_assembler import assemble_context

# Optional imports
try:
    from src.governance.audit.run_logger import format_runs_for_context, load_recent_runs
except ImportError:
    format_runs_for_context = None
    load_recent_runs = None

try:
    from src.governance.policy.prompt_canary import should_use_canary, get_canary_prompt
except ImportError:
    should_use_canary = None
    get_canary_prompt = None

log = logging.getLogger(__name__)


def build_execution_prompt(task: dict, dept_key: str, dept: dict,
                           task_cwd: str, project_name: str,
                           blueprint=None) -> str:
    """Assemble the full prompt: department identity + authority + cognitive mode + task + context."""
    base_prompt = TASK_PROMPT_TEMPLATE.format(
        cwd=task_cwd,
        project=project_name,
        problem=task.get("spec", {}).get("problem", ""),
        behavior_chain=task.get("spec", {}).get("behavior_chain", ""),
        observation=task.get("spec", {}).get("observation", ""),
        expected=task.get("spec", {}).get("expected", ""),
        action=task.get("action", ""),
        reason=task.get("reason", ""),
    )
    # 优先从 SKILL.md 加载部门 prompt，fallback 到内置 dict
    # Canary: 如果有 canary prompt 且该任务被分到 canary 组，用新 prompt
    task_id_for_canary = task.get("id", 0)
    if should_use_canary and should_use_canary(task_id_for_canary, dept_key):
        canary_prompt = get_canary_prompt(dept_key) if get_canary_prompt else None
        if canary_prompt:
            dept_prompt = canary_prompt
            log.info(f"TaskExecutor: task #{task_id_for_canary} using CANARY prompt for {dept_key}")
        else:
            skill_content = load_department(dept_key)
            dept_prompt = skill_content if skill_content else dept["prompt_prefix"]
    else:
        skill_content = load_department(dept_key)
        dept_prompt = skill_content if skill_content else dept["prompt_prefix"]

    # Authority ceiling 注入
    if blueprint:
        ceiling = blueprint.authority
        authority_prompt = (
            f"\n\n## Authority Ceiling: {ceiling.name}\n"
            f"你的权限等级为 {ceiling.name}（{ceiling.value}/4）。"
        )
        if ceiling <= AuthorityCeiling.READ:
            authority_prompt += "\n你只能观察和报告。不可修改任何文件。"
        elif ceiling <= AuthorityCeiling.PROPOSE:
            authority_prompt += "\n你可以写提案文件，不可修改已有源码。"
        elif ceiling <= AuthorityCeiling.MUTATE:
            authority_prompt += "\n你可以修改文件，但不可 git commit/push。提交由人类决定。"
        dept_prompt += authority_prompt

    # 认知模式注入
    cognitive_mode = classify_cognitive_mode(task)
    mode_prompt = COGNITIVE_MODE_PROMPTS.get(cognitive_mode, "")

    # 注入最近执行记录
    recent_runs = load_recent_runs(dept_key, n=5) if load_recent_runs else []
    runs_context = format_runs_for_context(recent_runs) if format_runs_for_context else ""

    # 组装最终 prompt
    prompt = dept_prompt
    if mode_prompt:
        prompt += "\n\n" + mode_prompt
    prompt += "\n\n" + base_prompt
    if runs_context:
        prompt += "\n\n" + runs_context

    # ── Synthesis Discipline: inject for multi-agent dispatch tasks ──
    spec = task.get("spec", {})
    is_multi_agent = bool(
        spec.get("sub_tasks")
        or spec.get("departments")
        or spec.get("scout_task_id")
        or spec.get("fact_layer_task_id")
    )
    if is_multi_agent:
        synthesis_prompt = load_prompt("synthesis_discipline")
        if synthesis_prompt:
            prompt += "\n\n" + synthesis_prompt
            log.info(f"TaskExecutor: injected synthesis_discipline for multi-agent task")

    # ── Collaboration Mode: inject if specified ──
    collab_mode = spec.get("collaboration_mode")
    if collab_mode:
        collab_prompt = load_prompt("collaboration_modes")
        if collab_prompt:
            prompt += f"\n\n[Active Collaboration Mode: {collab_mode}]\n{collab_prompt}"
            log.info(f"TaskExecutor: injected collaboration_mode={collab_mode}")

    # 动态上下文组装
    try:
        dynamic_ctx = assemble_context(dept_key, task)
        if dynamic_ctx:
            prompt += "\n\n" + dynamic_ctx
    except Exception as e:
        log.warning(f"TaskExecutor: context assembly failed ({e}), continuing without dynamic context")

    return prompt
