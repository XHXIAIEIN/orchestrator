"""Executor Prompt Builder — assemble the full prompt for task execution."""
import logging
from pathlib import Path

from src.governance.scrutiny import classify_cognitive_mode
from src.governance.policy.blueprint import AuthorityCeiling
from src.governance.context.prompts import (
    TASK_PROMPT_TEMPLATE, COGNITIVE_MODE_PROMPTS,
    load_department, load_prompt,
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

    # ── Methodology Router (Round 35 PUA steal — task type → thinking framework) ──
    methodology_prompt = _resolve_methodology(task, cognitive_mode)

    # 注入最近执行记录
    recent_runs = load_recent_runs(dept_key, n=5) if load_recent_runs else []
    runs_context = format_runs_for_context(recent_runs) if format_runs_for_context else ""

    # 组装最终 prompt
    prompt = dept_prompt
    if mode_prompt:
        prompt += "\n\n" + mode_prompt
    if methodology_prompt:
        prompt += "\n\n" + methodology_prompt

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

    # ── Context Access: progressive disclosure via ctx_read ──
    if session_id:
        ctx_instructions = f"""

## Context Access (Progressive Disclosure)

You have access to additional context stored in a database. Read what you need — don't read everything.

**Tool:** `python scripts/ctx_read.py --session {session_id} <command>`

**Commands:**
- `--list` — see all available context keys and their token sizes
- `--key <key>` — read a specific context entry
- `--layer <0-3>` — read all entries in a layer
- `--budget <N>` — limit read to N tokens

**Layers:**
- L0 (in this prompt): identity, task description
- L1: session state, predecessor task outputs, conversation summary
- L2: file contents, memory entries, conversation fragments
- L3: full conversation transcript, codebase search, department history

**Start with `--list` to see what's available, then read what's relevant to your task.**
"""
        prompt += ctx_instructions

        # Inject L0 catalog directly (agent sees what's available without a tool call)
        try:
            _db_path = str(Path(task_cwd) / "data" / "events.db") if task_cwd else "data/events.db"
            if not Path(_db_path).exists():
                _db_path = "data/events.db"
            from src.storage.events_db import EventsDB as _EDB
            _db = _EDB(_db_path)
            catalog_row = _db.get_context(session_id, "catalog")
            if catalog_row:
                prompt += "\n" + catalog_row["content"]
        except Exception:
            pass  # Catalog injection is best-effort

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

    # ── Dynamic Context Assembly ──
    try:
        ctx = TaskContext.from_task(task, department=dept_key)
        ctx.cwd = task_cwd
        ctx.project_name = project_name
        budget = tier.prompt_budget if tier else 2000
        dynamic_ctx = _context_engine.assemble(ctx, budget_tokens=budget)
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


# ── Methodology Router (stolen from PUA flavor-based methodology, Round 35) ──
# Maps task characteristics to thinking frameworks. Deterministic, not LLM-judged.
# The methodology is injected into the task prompt as a ~80 token compass.

_METHODOLOGY_TABLE = {
    "debug": {
        "name": "RCA (Root Cause Analysis)",
        "principle": "Diagnose before treating",
        "steps": "1. Reproduce 2. Hypothesize (2-3 causes) 3. Verify each 4. Fix confirmed cause 5. Regression test",
    },
    "build": {
        "name": "First Principles",
        "principle": "Question every assumption",
        "steps": "1. Simplest version? 2. What constraints? 3. Build minimal 4. Iterate",
    },
    "review": {
        "name": "Subtraction",
        "principle": "Less is more",
        "steps": "1. What can be removed? 2. What can be simplified? 3. Blast radius? 4. One owner per decision",
    },
    "research": {
        "name": "Search First",
        "principle": "Don't reinvent",
        "steps": "1. Search codebase 2. Search docs 3. Search web 4. Synthesize 5. Form opinion",
    },
    "architect": {
        "name": "Working Backwards",
        "principle": "Start from the user",
        "steps": "1. Ideal usage 2. Define interface 3. Design implementation 4. Identify risks",
    },
    "performance": {
        "name": "Measure First",
        "principle": "No premature optimization",
        "steps": "1. Profile/benchmark 2. Identify bottleneck 3. Hypothesize fix 4. Implement 5. Measure again",
    },
    "deploy": {
        "name": "Closed Loop",
        "principle": "Every action has verification",
        "steps": "1. Pre-check 2. Execute 3. Verify 4. Monitor 5. Rollback plan ready",
    },
    "refactor": {
        "name": "Preserve Behavior",
        "principle": "Tests are the contract",
        "steps": "1. Tests pass 2. Refactor one thing 3. Tests pass again 4. Repeat",
    },
}

# Keywords that signal each methodology type (checked against action + problem text)
_METHODOLOGY_SIGNALS = {
    "debug": ["fix", "bug", "error", "broken", "fail", "crash", "issue", "debug", "修复", "报错", "崩溃"],
    "build": ["add", "create", "implement", "new feature", "build", "新建", "新增", "实现"],
    "review": ["review", "audit", "check", "inspect", "审查", "检查"],
    "research": ["research", "investigate", "find out", "explore", "understand", "调研", "研究", "了解"],
    "architect": ["design", "architect", "restructure", "plan", "设计", "架构", "规划"],
    "performance": ["performance", "slow", "optimize", "speed", "latency", "性能", "优化", "慢"],
    "deploy": ["deploy", "release", "publish", "ship", "部署", "发布", "上线"],
    "refactor": ["refactor", "clean", "reorganize", "simplify", "重构", "简化", "整理"],
}


def _resolve_methodology(task: dict, cognitive_mode: str) -> str:
    """Resolve methodology for a task. Returns a compact prompt block or empty string.

    Priority:
    1. Cognitive mode override: hypothesis → RCA, designer → Working Backwards
    2. Keyword matching against action + problem text
    3. No match → no injection (direct mode tasks don't need methodology)
    """
    # Cognitive mode overrides
    if cognitive_mode == "hypothesis":
        method = _METHODOLOGY_TABLE["debug"]
    elif cognitive_mode == "designer":
        method = _METHODOLOGY_TABLE["architect"]
    elif cognitive_mode == "direct":
        return ""  # Trivial tasks don't need methodology
    else:
        # Keyword matching
        spec = task.get("spec", {}) if isinstance(task.get("spec"), dict) else {}
        text = f"{task.get('action', '')} {spec.get('problem', '')} {spec.get('summary', '')}".lower()

        method = None
        for method_key, signals in _METHODOLOGY_SIGNALS.items():
            if any(sig in text for sig in signals):
                method = _METHODOLOGY_TABLE[method_key]
                break

    if not method:
        return ""

    return (
        f"[Methodology: {method['name']}]\n"
        f"{method['principle']}\n"
        f"Steps: {method['steps']}"
    )
