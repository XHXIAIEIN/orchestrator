"""R74 ChatDev: Organization Culture Variable Injection.

Injects ${ORCHESTRATOR_CONTEXT} into all sub-agent system prompts to
establish unified identity. Replaces ChatDev's ${COMMON_PROMPT} pattern.

The culture block is:
    1. Loaded from config/culture.md (user-customizable) or fallback default
    2. Variable-expanded with runtime context (project name, session, etc.)
    3. Prepended to every sub-agent's system prompt via inject_culture()

This ensures all sub-agents share a common understanding of:
    - Who they are (Orchestrator agents)
    - What project they're working on
    - What constraints they operate under
    - How they should communicate

Integration: Called in executor_prompt.build_execution_prompt() and
             any sub-agent dispatch path.

Source: ChatDev 2.0 ${COMMON_PROMPT} (R74 deep steal)
"""
from __future__ import annotations

import logging
import os
import string
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not (_REPO_ROOT / "src").is_dir():
    _REPO_ROOT = _REPO_ROOT.parent

# ── Default culture block (used when config/culture.md doesn't exist) ──

_DEFAULT_CULTURE = """\
You are an Orchestrator agent — part of an AI-powered system that monitors, \
analyzes, and acts on behalf of the project owner. Your work is coordinated by \
the Governor, which assigns tasks and reviews results.

Current context: project=${project}, department=${department}.

Core principles:
- Execute directly and report results, not progress updates.
- Be specific: file paths, line numbers, concrete actions.
- Match existing code style. Minimal diff.
- Never expose the owner's personal information.
"""


@lru_cache(maxsize=1)
def _load_culture_template() -> str:
    """Load culture template from config/culture.md or use default.

    Cached because the file rarely changes during a session.
    """
    culture_path = _REPO_ROOT / "config" / "culture.md"
    if culture_path.is_file():
        try:
            content = culture_path.read_text(encoding="utf-8").strip()
            if content:
                log.debug("culture_inject: loaded from %s", culture_path)
                return content
        except OSError as exc:
            log.warning("culture_inject: failed to read %s: %s", culture_path, exc)

    return _DEFAULT_CULTURE


def render_culture(
    project: str = "",
    department: str = "",
    session_id: str = "",
    extra_vars: dict[str, str] | None = None,
) -> str:
    """Render the culture template with runtime variables.

    Uses safe_substitute so missing variables don't raise errors.
    Also checks ORCHESTRATOR_CONTEXT env var for overrides.
    """
    # Env var override takes absolute precedence
    env_override = os.environ.get("ORCHESTRATOR_CONTEXT")
    if env_override:
        return env_override

    template = _load_culture_template()

    variables = {
        "project": project or "unknown",
        "department": department or "general",
        "session_id": session_id or "n/a",
    }
    if extra_vars:
        variables.update(extra_vars)

    # safe_substitute: unresolved ${vars} are left as-is, no KeyError
    return string.Template(template).safe_substitute(variables)


def inject_culture(
    prompt: str,
    project: str = "",
    department: str = "",
    session_id: str = "",
    extra_vars: dict[str, str] | None = None,
) -> str:
    """Prepend culture block to a prompt.

    If the prompt already contains the culture marker, skip injection
    to avoid duplication (idempotent).
    """
    marker = "<!-- orchestrator-culture -->"
    if marker in prompt:
        return prompt

    culture = render_culture(
        project=project,
        department=department,
        session_id=session_id,
        extra_vars=extra_vars,
    )

    return f"{marker}\n{culture}\n{marker}\n\n{prompt}"


def clear_cache() -> None:
    """Clear the culture template cache (for testing or config reload)."""
    _load_culture_template.cache_clear()
