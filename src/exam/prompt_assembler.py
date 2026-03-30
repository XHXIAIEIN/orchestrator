"""Prompt Assembler — build the full prompt for a division agent during exam.

Assembly order:
  [1] Department SKILL.md (base capability)
  [2] Division prompt.md (specialized capability)
  [3] Division exam.md (exam-specific tips, only in exam mode)
  [4] Coach-injected learnings (historical failure patterns for this dimension)
  [5] The question itself
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent


def _read_file(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        log.warning(f"prompt_assembler: failed to read {path}: {e}")
    return ""


def assemble_exam_prompt(
    department: str,
    division: str,
    question: dict,
    learnings: list[str],
    exam_mode: bool = True,
) -> str:
    """Assemble the full prompt for a division agent answering an exam question."""
    parts = []

    # [1] Department SKILL.md
    skill_path = _REPO_ROOT / "departments" / department / "SKILL.md"
    skill_content = _read_file(skill_path)
    if skill_content:
        parts.append(skill_content)

    # [2] Division prompt.md
    div_prompt_path = _REPO_ROOT / "departments" / department / division / "prompt.md"
    div_content = _read_file(div_prompt_path)
    if div_content:
        parts.append(div_content)

    # [3] Division exam.md (exam mode only)
    if exam_mode:
        exam_path = _REPO_ROOT / "departments" / department / division / "exam.md"
        exam_content = _read_file(exam_path)
        if exam_content:
            parts.append(exam_content)

    # [4] Coach-injected learnings
    if learnings:
        learnings_block = "## Coach Notes — This Dimension's Known Pitfalls\n\n"
        learnings_block += "\n".join(f"- {l}" for l in learnings)
        parts.append(learnings_block)

    # [5] Question
    q_block = f"## Question: {question.get('id', 'unknown')}\n\n{question.get('prompt', '')}"
    parts.append(q_block)

    return "\n\n---\n\n".join(parts)
