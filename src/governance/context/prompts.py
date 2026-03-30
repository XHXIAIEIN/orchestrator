"""Governor prompt templates, department definitions, and dispatch config.

Prompt loading order (first match wins):
  1. SOUL/private/prompts/{name}.md  — personal overrides (gitignored)
  2. SOUL/public/prompts/{name}.md    — public defaults (tracked)
"""
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent
_PROMPT_DIRS = [
    _REPO_ROOT / "SOUL" / "private" / "prompts",  # personal override
    _REPO_ROOT / "SOUL" / "public" / "prompts",    # public default
]


def load_prompt(name: str) -> str:
    """Load a prompt template. Private overrides public."""
    for d in _PROMPT_DIRS:
        path = d / f"{name}.md"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            log.warning(f"prompts: failed to load {path}: {e}")
    return ""


def load_cognitive_modes() -> dict[str, str]:
    """Parse SOUL/private/prompts/cognitive_modes.md into {mode: prompt} dict."""
    raw = load_prompt("cognitive_modes")
    if not raw:
        return {"direct": "", "react": "", "hypothesis": "", "designer": ""}
    modes = {}
    current_mode = None
    current_lines = []
    for line in raw.splitlines():
        header = re.match(r'^## (\w+)', line)
        if header:
            if current_mode is not None:
                modes[current_mode] = "\n".join(current_lines).strip()
            current_mode = header.group(1)
            current_lines = []
        elif current_mode is not None:
            current_lines.append(line)
    if current_mode is not None:
        modes[current_mode] = "\n".join(current_lines).strip()
    return modes


# ── Prompt templates (loaded from SOUL/) ──

TASK_PROMPT_TEMPLATE = load_prompt("task")
SCRUTINY_PROMPT = load_prompt("scrutiny")
COGNITIVE_MODE_PROMPTS = load_cognitive_modes()

# ── Second opinion model ──
from src.core.llm_router import MODEL_HAIKU
SECOND_OPINION_MODEL = MODEL_HAIKU

# ── 六部路由表 (manifest-driven auto-discovery) ──
# Loaded from departments/*/manifest.yaml by registry.py.
# This import replaces the former hardcoded DEPARTMENTS dict.
from src.governance.registry import DEPARTMENTS

# ── Parallel dispatch scenarios ──
PARALLEL_SCENARIOS = {
    "full_audit": {
        "description": "Full system audit: security + quality + protocol in parallel",
        "departments": ["security", "quality", "protocol"],
    },
    "code_and_review": {
        "description": "Engineering fix + quality review on different projects",
        "departments": ["engineering", "quality"],
    },
    "system_health": {
        "description": "Operations health check + personnel performance report",
        "departments": ["operations", "personnel"],
    },
    "deep_scan": {
        "description": "Protocol debt scan + security audit + personnel metrics",
        "departments": ["protocol", "security", "personnel"],
    },
    "full_pipeline": {
        "description": "All read-only departments scan simultaneously",
        "departments": ["protocol", "security", "quality", "personnel"],
    },
}


def load_department(name: str) -> str | None:
    """从 departments/{name}/SKILL.md 加载部门 prompt。文件不存在时返回 None（fallback 到 DEPARTMENTS dict）。"""
    skill_path = _REPO_ROOT / "departments" / name / "SKILL.md"
    try:
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"prompts: failed to load SKILL.md for {name}: {e}")
    return None


def load_division(department: str, division: str, include_exam: bool = False) -> str | None:
    """Load division-level prompt from departments/{dept}/{division}/prompt.md.

    Optionally appends exam.md if include_exam=True (exam mode only).
    Returns None if no prompt.md exists.
    """
    div_dir = _REPO_ROOT / "departments" / department / division
    prompt_path = div_dir / "prompt.md"
    parts = []
    try:
        if prompt_path.exists():
            parts.append(prompt_path.read_text(encoding="utf-8").strip())
    except Exception as e:
        log.warning(f"prompts: failed to load division prompt {prompt_path}: {e}")

    if include_exam:
        exam_path = div_dir / "exam.md"
        try:
            if exam_path.exists():
                parts.append(exam_path.read_text(encoding="utf-8").strip())
        except Exception as e:
            log.warning(f"prompts: failed to load exam prompt {exam_path}: {e}")

    return "\n\n".join(parts) if parts else None


def find_git_bash() -> str | None:
    """Find git-bash path for Windows Agent SDK compatibility.

    Agent SDK requires Git/bin/bash.exe (not usr/bin/bash.EXE).
    Check explicit paths first before falling back to shutil.which.
    """
    for candidate in [
        Path("D:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/bin/bash.exe"),
    ]:
        if candidate.exists():
            return str(candidate)
    bash = shutil.which("bash")
    if bash:
        return bash
    return None
