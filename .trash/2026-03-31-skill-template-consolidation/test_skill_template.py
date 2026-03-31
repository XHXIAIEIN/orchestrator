"""Tests for Autonomous Skill Templates."""
import os
from src.governance.skill_template import (
    SkillTemplate, SkillRegistry, Precondition, AgentConfig,
    _check_one, load_skill_yaml,
)


def test_skill_template_defaults():
    skill = SkillTemplate(name="test", description="desc", department="engineering", intent="code_fix")
    assert skill.enabled is True
    assert skill.tools == []
    assert skill.schedule == ""
    assert skill.agent.model == "claude-sonnet-4-6"


def test_to_task_spec():
    skill = SkillTemplate(
        name="security-scan",
        description="Scan for vulnerabilities",
        department="security",
        intent="security_scan",
        tools=["Bash", "Read", "Grep"],
    )
    spec = skill.to_task_spec()
    assert spec["department"] == "security"
    assert spec["intent"] == "security_scan"
    assert spec["source"] == "skill_template:security-scan"
    assert "Bash" in spec["allowed_tools"]


def test_precondition_env_var():
    os.environ["TEST_SKILL_VAR"] = "hello"
    pre = Precondition(type="env_var", name="TEST_SKILL_VAR")
    passed, msg = _check_one(pre)
    assert passed is True
    del os.environ["TEST_SKILL_VAR"]


def test_precondition_env_var_missing():
    pre = Precondition(type="env_var", name="DEFINITELY_NOT_SET_XYZ123")
    passed, msg = _check_one(pre)
    assert passed is False


def test_precondition_file_exists():
    pre = Precondition(type="file_exists", path="src/")
    passed, msg = _check_one(pre)
    assert passed is True


def test_precondition_file_missing():
    pre = Precondition(type="file_exists", path="nonexistent_dir_xyz/")
    passed, msg = _check_one(pre)
    assert passed is False


def test_all_preconditions_met():
    skill = SkillTemplate(
        name="test", description="", department="engineering", intent="test",
        preconditions=[
            Precondition(type="file_exists", path="src/", required=True),
            Precondition(type="file_exists", path="nonexistent_xyz/", required=False),
        ],
    )
    assert skill.all_preconditions_met() is True  # optional failure doesn't block


def test_all_preconditions_not_met():
    skill = SkillTemplate(
        name="test", description="", department="engineering", intent="test",
        preconditions=[
            Precondition(type="file_exists", path="nonexistent_xyz/", required=True),
        ],
    )
    assert skill.all_preconditions_met() is False


def test_registry_register_and_list():
    reg = SkillRegistry()
    reg.register(SkillTemplate(name="a", description="", department="engineering", intent="test"))
    reg.register(SkillTemplate(name="b", description="", department="security", intent="test", schedule="0 * * * *"))
    assert len(reg.list_all()) == 2
    assert len(reg.list_scheduled()) == 1
    assert len(reg.list_by_department("engineering")) == 1


def test_registry_get():
    reg = SkillRegistry()
    skill = SkillTemplate(name="findme", description="", department="engineering", intent="test")
    reg.register(skill)
    assert reg.get("findme") is skill
    assert reg.get("nonexistent") is None


def test_registry_stats():
    reg = SkillRegistry()
    reg.register(SkillTemplate(name="a", description="", department="engineering", intent="t1"))
    reg.register(SkillTemplate(name="b", description="", department="security", intent="t2", enabled=False))
    stats = reg.get_stats()
    assert stats["total"] == 2
    assert stats["enabled"] == 1


def test_load_skill_yaml(tmp_path):
    """Load a skill from YAML file."""
    yaml_content = """
name: daily-scan
description: "Daily security scan"
department: security
intent: security_scan
tools: [Bash, Read, Grep]
schedule: "0 6 * * *"
preconditions:
  - type: file_exists
    path: src/
agent:
  model: claude-haiku-4-5-20251001
  max_turns: 10
  timeout_s: 120
tags: [security, automated]
"""
    yaml_file = tmp_path / "daily-scan.yaml"
    yaml_file.write_text(yaml_content)

    skill = load_skill_yaml(yaml_file)
    assert skill is not None
    assert skill.name == "daily-scan"
    assert skill.department == "security"
    assert skill.schedule == "0 6 * * *"
    assert len(skill.tools) == 3
    assert skill.agent.max_turns == 10
    assert len(skill.preconditions) == 1
    assert skill.tags == ["security", "automated"]
