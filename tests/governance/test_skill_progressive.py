import pytest
from pathlib import Path
from src.governance.skill_cas import SkillCAS, SkillMeta


def _make_skill_dir(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "code-review").mkdir()
    (skill_dir / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code for bugs\ncategory: quality\n---\n\n"
        "Full content of code review skill with many instructions..." * 50
    )
    (skill_dir / "testing").mkdir()
    (skill_dir / "testing" / "SKILL.md").write_text(
        "---\nname: testing\ndescription: Write unit tests\ncategory: dev\n---\n\n"
        "Full content of testing skill..." * 50
    )
    return skill_dir


def test_scan_returns_metadata_only(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    cas = SkillCAS(store_path=tmp_path / "store")
    metas = cas.scan_skills(skill_dir)
    assert len(metas) == 2
    names = {m.name for m in metas}
    assert names == {"code-review", "testing"}
    for m in metas:
        assert m.description
        assert m.full_content is None


def test_load_skill_returns_full_content(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    cas = SkillCAS(store_path=tmp_path / "store")
    cas.scan_skills(skill_dir)
    content = cas.load_skill("code-review", skill_dir)
    assert content is not None
    assert "Full content of code review" in content
    assert len(content) > 100


def test_load_nonexistent_skill(tmp_path):
    cas = SkillCAS(store_path=tmp_path / "store")
    content = cas.load_skill("nonexistent", tmp_path)
    assert content is None
