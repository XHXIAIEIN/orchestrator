"""
Domain Pack — 核心引擎零领域代码，部门行为通过配置+动态加载注入。

Lumina OS 启发：引擎和领域完全解耦。

当前状态：
  - SKILL.md 是领域 prompt（已解耦）
  - blueprint.yaml 是领域配置（已解耦）
  - guidelines/ 是领域规则（已解耦）

Domain Pack 进一步形式化这个模式，提供：
  1. 标准化的 domain pack 结构
  2. 动态加载/热更新能力
  3. domain pack 校验
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEPT_ROOT = _REPO_ROOT / "departments"


@dataclass
class DomainPack:
    """一个部门的完整领域包。"""
    department: str
    version: str = "1"

    # 核心文件
    skill_prompt: str = ""          # SKILL.md 内容
    blueprint: dict = field(default_factory=dict)  # blueprint.yaml 解析后
    guidelines: list[dict] = field(default_factory=list)  # guidelines/*.md
    learned_skills: str = ""        # learned-skills.md

    # 元数据
    files_present: list[str] = field(default_factory=list)
    valid: bool = True
    errors: list[str] = field(default_factory=list)


def load_domain_pack(department: str) -> DomainPack:
    """加载一个部门的完整 domain pack。"""
    dept_dir = _DEPT_ROOT / department
    if not dept_dir.exists():
        return DomainPack(department=department, valid=False,
                          errors=[f"目录不存在: {dept_dir}"])

    pack = DomainPack(department=department)
    files = []

    # SKILL.md
    skill_path = dept_dir / "SKILL.md"
    if skill_path.exists():
        pack.skill_prompt = skill_path.read_text(encoding="utf-8")
        files.append("SKILL.md")
    else:
        pack.errors.append("缺少 SKILL.md")

    # blueprint.yaml
    bp_path = dept_dir / "blueprint.yaml"
    if bp_path.exists():
        try:
            pack.blueprint = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
            files.append("blueprint.yaml")
        except Exception as e:
            pack.errors.append(f"blueprint.yaml 解析失败: {e}")

    # guidelines/
    guide_dir = dept_dir / "guidelines"
    if guide_dir.exists():
        for gf in sorted(guide_dir.glob("*.md")):
            try:
                pack.guidelines.append({
                    "name": gf.stem,
                    "content": gf.read_text(encoding="utf-8"),
                })
                files.append(f"guidelines/{gf.name}")
            except Exception:
                pass

    # learned-skills.md
    learned_path = dept_dir / "learned-skills.md"
    if learned_path.exists():
        pack.learned_skills = learned_path.read_text(encoding="utf-8")
        files.append("learned-skills.md")

    pack.files_present = files
    pack.version = pack.blueprint.get("version", "1")
    pack.valid = len(pack.errors) == 0

    return pack


def load_all_domain_packs() -> dict[str, DomainPack]:
    """加载所有部门的 domain pack。"""
    packs = {}
    if not _DEPT_ROOT.exists():
        return packs

    for dept_dir in sorted(_DEPT_ROOT.iterdir()):
        if not dept_dir.is_dir() or dept_dir.name.startswith((".", "_", "shared")):
            continue
        packs[dept_dir.name] = load_domain_pack(dept_dir.name)

    return packs


def validate_domain_pack(pack: DomainPack) -> list[str]:
    """校验 domain pack 的完整性。返回问题列表。"""
    issues = list(pack.errors)

    if not pack.skill_prompt:
        issues.append("SKILL.md 为空")

    if not pack.blueprint:
        issues.append("缺少 blueprint.yaml")
    else:
        # 校验必要字段
        required = ["name_zh", "model", "policy"]
        for field_name in required:
            if field_name not in pack.blueprint:
                issues.append(f"blueprint.yaml 缺少必要字段: {field_name}")

    return issues


def get_pack_summary() -> dict:
    """获取所有 domain pack 的摘要。"""
    packs = load_all_domain_packs()
    return {
        dept: {
            "valid": pack.valid,
            "version": pack.version,
            "files": len(pack.files_present),
            "guidelines": len(pack.guidelines),
            "errors": pack.errors,
        }
        for dept, pack in packs.items()
    }
