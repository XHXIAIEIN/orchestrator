"""Executor Prompt Builder — assemble the full prompt for task execution."""
import logging

from src.governance.scrutiny import classify_cognitive_mode
from src.governance.policy.blueprint import AuthorityCeiling
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS,
    load_department,
)
# Context Engine (Round 16 LobeHub upgrade — provider/processor pipeline)
# Sole context assembly path. context_assembler.py is deprecated.
from src.governance.context.engine import ContextEngine, TaskContext
_context_engine = ContextEngine.default()

# Optional imports
try:
    from src.governance.audit.run_logger import format_runs_for_context, load_recent_runs
except ImportError:
    format_runs_for_context = None
    load_recent_runs = None

# Condenser — optional context compression before LLM execution
try:
    from src.governance.condenser.context_condenser import condense_context as _condense_context
except ImportError:
    _condense_context = None

try:
    from src.governance.policy.prompt_canary import should_use_canary, get_canary_prompt
except ImportError:
    should_use_canary = None
    get_canary_prompt = None

# Voice Directive — department voice injection (gstack)
try:
    from src.governance.voice_directive import VoiceDirective as _VoiceDirective
except ImportError:
    _VoiceDirective = None

log = logging.getLogger(__name__)


def build_execution_prompt(task: dict, dept_key: str, dept: dict,
                           task_cwd: str, project_name: str,
                           blueprint=None, session_id: str = "", tier=None) -> str:
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

    # ── Voice Directive: inject department voice parameters (gstack) ──
    if _VoiceDirective:
        try:
            voice = _VoiceDirective.for_department(dept_key)
            voice_block = voice.to_prompt_block()
            if voice_block:
                prompt += "\n\n" + voice_block
        except Exception:
            pass

    prompt += "\n\n" + base_prompt
    spec = task.get('spec', {})
    extra = spec.get('extra_instructions', '')
    if extra:
        prompt += '\n\n## Extra Instructions\n' + extra
    if runs_context:
        prompt += "\n\n" + runs_context

    # 动态上下文组装 — ContextEngine pipeline (唯一路径)
    try:
        ctx = TaskContext.from_task(task, department=dept_key)
        ctx.cwd = task_cwd
        ctx.project_name = project_name
        dynamic_ctx = _context_engine.assemble(ctx, budget_tokens=2000)
        if dynamic_ctx:
            prompt += "\n\n" + dynamic_ctx
    except Exception as e:
        log.warning(f"TaskExecutor: context assembly failed ({e}), continuing without dynamic context")

    # ── Condenser: optional context compression (post-assembly, pre-execution) ──
    # Configurable per-department via manifest.yaml `condenser:` section.
    if _condense_context:
        condenser_config = _get_condenser_config(dept, blueprint)
        prompt = _condense_context(prompt, dept_key=dept_key, config=condenser_config)

    return prompt


def _get_condenser_config(dept: dict, blueprint=None) -> dict:
    """Extract condenser config from department dict or blueprint.

    Departments can configure condenser behavior in manifest.yaml:
        condenser:
          enabled: true
          max_tokens: 128000
          high_water: 0.85
    """
    config = {}
    # dept dict may carry raw manifest fields
    if isinstance(dept, dict) and "condenser" in dept:
        raw = dept["condenser"]
        if isinstance(raw, dict):
            config.update(raw)
    # Blueprint may also carry condenser overrides
    if blueprint and hasattr(blueprint, "condenser"):
        bp_config = getattr(blueprint, "condenser", None)
        if isinstance(bp_config, dict):
            config.update(bp_config)
    return config
