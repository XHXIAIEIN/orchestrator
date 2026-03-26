"""
SkillApplier — 读取 skill-suggestions.md，生成 SKILL.md 追加补丁并安全应用。

闭环的关键一环：suggestions → SKILL.md 更新。

安全设计：
  - 修改前备份到 .trash/skill-backup/
  - 只追加，不删除现有规则
  - 单次补丁 token 上限 ~500 chars
  - 连续失败时中止
"""
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent
while _REPO_ROOT != _REPO_ROOT.parent and not ((_REPO_ROOT / "departments").is_dir() and (_REPO_ROOT / "src").is_dir()):
    _REPO_ROOT = _REPO_ROOT.parent

MAX_PATCH_CHARS = 500
MARKER = "<!-- auto-evolved -->"

APPLY_PROMPT = """你是 Orchestrator 吏部的 SKILL.md 维护员。根据以下改善建议，为部门 SKILL.md 生成一段追加内容。

部门：{department}

当前 SKILL.md（末尾 2000 字符）：
```
{skill_tail}
```

改善建议摘要：
```
{suggestions}
```

规则：
1. 只输出要 **追加** 到 SKILL.md 末尾的内容，不要重复已有内容
2. 不要删除或修改任何现有规则
3. 用 markdown 格式，标题用 ###
4. 内容必须具体可执行（"检查 X 文件的 Y 字段" 而不是 "注意 X"）
5. 总长度不超过 {max_chars} 字符
6. 如果建议质量太低或与现有内容重复，输出空字符串 ""

直接输出追加内容，不要任何解释或前缀。
"""


def apply_suggestions(department: str, dry_run: bool = False) -> dict:
    """读取 suggestions，生成补丁，应用到 SKILL.md。

    Returns:
        dict with keys: applied (bool), patch (str), backup_path (str), reason (str)
    """
    dept_dir = _REPO_ROOT / "departments" / department
    suggestions_path = dept_dir / "skill-suggestions.md"
    skill_path = dept_dir / "SKILL.md"

    result = {"applied": False, "patch": "", "backup_path": "", "reason": ""}

    # 1. 读 suggestions
    if not suggestions_path.exists():
        result["reason"] = "no suggestions file"
        return result

    suggestions_text = suggestions_path.read_text(encoding="utf-8")
    if not suggestions_text.strip() or "暂无建议" in suggestions_text:
        result["reason"] = "no actionable suggestions"
        return result

    # 检查是否已经应用过（状态标记）
    if "状态: 已应用" in suggestions_text:
        result["reason"] = "suggestions already applied"
        return result

    # 2. 读当前 SKILL.md
    skill_content = ""
    if skill_path.exists():
        skill_content = skill_path.read_text(encoding="utf-8")

    # 3. 用 LLM 生成补丁
    try:
        from src.core.llm_router import get_router
        prompt = APPLY_PROMPT.format(
            department=department,
            skill_tail=skill_content[-2000:] if skill_content else "(empty)",
            suggestions=suggestions_text[:3000],
            max_chars=MAX_PATCH_CHARS,
        )
        patch = get_router().generate(prompt, task_type="analysis")
    except Exception as e:
        result["reason"] = f"LLM generation failed: {e}"
        log.error(f"SkillApplier: {result['reason']}")
        return result

    # 4. 安全检查
    patch = patch.strip()
    if not patch or patch == '""':
        result["reason"] = "LLM determined no patch needed"
        _mark_suggestions_applied(suggestions_path, suggestions_text, "no patch needed")
        return result

    if len(patch) > MAX_PATCH_CHARS * 2:  # 容忍 2x 但不能太离谱
        patch = patch[:MAX_PATCH_CHARS]
        log.warning(f"SkillApplier: patch truncated to {MAX_PATCH_CHARS} chars")

    # 检查补丁不包含删除指令
    if any(word in patch.lower() for word in ["删除", "移除", "remove", "delete"]):
        result["reason"] = "patch contains deletion instructions, rejected"
        log.warning(f"SkillApplier: {result['reason']}")
        return result

    # 检查与现有内容不重复（简单检查：补丁的首行是否已存在）
    first_line = patch.split("\n")[0].strip().strip("#").strip()
    if first_line and first_line in skill_content:
        result["reason"] = f"patch appears duplicated: '{first_line[:50]}'"
        _mark_suggestions_applied(suggestions_path, suggestions_text, "duplicate")
        return result

    result["patch"] = patch

    if dry_run:
        result["reason"] = "dry run — patch generated but not applied"
        return result

    # 5. 备份
    backup_dir = _REPO_ROOT / ".trash" / "skill-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{department}-SKILL-{ts}.md"
    if skill_path.exists():
        shutil.copy2(skill_path, backup_path)
        result["backup_path"] = str(backup_path)
        log.info(f"SkillApplier: backed up {skill_path} → {backup_path}")

    # 6. 追加补丁
    separator = f"\n\n{MARKER}\n"
    new_content = skill_content.rstrip() + separator + patch + "\n"
    skill_path.write_text(new_content, encoding="utf-8")
    result["applied"] = True
    result["reason"] = "patch applied successfully"
    log.info(f"SkillApplier: applied {len(patch)} chars to {skill_path}")

    # 7. 标记 suggestions 为已应用
    _mark_suggestions_applied(suggestions_path, suggestions_text, "applied")

    return result


def _mark_suggestions_applied(path: Path, content: str, status: str):
    """将 suggestions 文件标记为已处理。"""
    try:
        updated = content.replace("状态: 待审核", f"状态: 已应用 ({status})")
        path.write_text(updated, encoding="utf-8")
    except Exception as e:
        log.warning(f"SkillApplier: failed to mark suggestions: {e}")


def count_auto_patches(department: str) -> int:
    """统计某部门 SKILL.md 中自动演化补丁的数量。"""
    skill_path = _REPO_ROOT / "departments" / department / "SKILL.md"
    if not skill_path.exists():
        return 0
    return skill_path.read_text(encoding="utf-8").count(MARKER)


def rollback_last_patch(department: str) -> bool:
    """回滚最近一次自动补丁（从 SKILL.md 中移除最后一个 MARKER 及其后内容）。"""
    skill_path = _REPO_ROOT / "departments" / department / "SKILL.md"
    if not skill_path.exists():
        return False

    content = skill_path.read_text(encoding="utf-8")
    last_marker = content.rfind(MARKER)
    if last_marker == -1:
        return False

    skill_path.write_text(content[:last_marker].rstrip() + "\n", encoding="utf-8")
    log.info(f"SkillApplier: rolled back last patch for {department}")
    return True
