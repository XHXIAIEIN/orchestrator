"""Governor prompt templates, department definitions, and dispatch config.

Prompt loading order (first match wins):
  1. SOUL/private/prompts/{name}.md  — personal overrides (gitignored)
  2. SOUL/prompts/{name}.md          — public defaults (tracked)
"""
import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_PROMPT_DIRS = [
    _REPO_ROOT / "SOUL" / "private" / "prompts",  # personal override
    _REPO_ROOT / "SOUL" / "public" / "prompts",    # public default
]


def _load_prompt(name: str) -> str:
    """Load a prompt template. Private overrides public."""
    for d in _PROMPT_DIRS:
        path = d / f"{name}.md"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            log.warning(f"prompts: failed to load {path}: {e}")
    return ""


def _load_cognitive_modes() -> dict[str, str]:
    """Parse SOUL/private/prompts/cognitive_modes.md into {mode: prompt} dict."""
    raw = _load_prompt("cognitive_modes")
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


# ── Prompt templates (loaded from SOUL/private/prompts/) ──

TASK_PROMPT_TEMPLATE = _load_prompt("task")
SCRUTINY_PROMPT = _load_prompt("scrutiny")
COGNITIVE_MODE_PROMPTS = _load_cognitive_modes()

# ── Second opinion model ──
SECOND_OPINION_MODEL = "claude-haiku-4-5-20251001"

# ── 六部路由表 ──
# Department prompt_prefix is the inline fallback; SKILL.md files take priority at runtime.
DEPARTMENTS = {
    "engineering": {
        "name": "工部",
        "skill_path": "departments/engineering/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 工部——代码工程部门。",
        "tools": "Bash,Read,Edit,Write,Glob,Grep",
    },
    "operations": {
        "name": "户部",
        "skill_path": "departments/operations/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 户部——系统运维部门。",
        "tools": "Bash,Read,Edit,Write,Glob,Grep",
    },
    "protocol": {
        "name": "礼部",
        "skill_path": "departments/protocol/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 礼部——注意力审计部门。",
        "tools": "Read,Glob,Grep",
    },
    "security": {
        "name": "兵部",
        "skill_path": "departments/security/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 兵部——安全防御部门。",
        "tools": "Bash,Read,Glob,Grep",
    },
    "quality": {
        "name": "刑部",
        "skill_path": "departments/quality/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 刑部——质量验收部门。",
        "tools": "Bash,Read,Glob,Grep",
    },
    "personnel": {
        "name": "吏部",
        "skill_path": "departments/personnel/SKILL.md",
        "prompt_prefix": "你是 Orchestrator 吏部——绩效管理部门。",
        "tools": "Read,Glob,Grep",
    },
}

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
    skill_path = Path(__file__).parent.parent / "departments" / name / "SKILL.md"
    try:
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"prompts: failed to load SKILL.md for {name}: {e}")
    return None


def find_git_bash() -> str | None:
    """Find git-bash path for Windows Agent SDK compatibility."""
    bash = shutil.which("bash")
    if bash:
        return bash
    for candidate in [
        Path("D:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/bin/bash.exe"),
    ]:
        if candidate.exists():
            return str(candidate)
    return None
