"""
Tests for Mitchell Rule — auto_apply_rules() in PolicyAdvisor.

Mitchell 法则: agent 犯了一个错, 就在 harness 里加一个机制确保它再也不犯。
"""
import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch
from src.governance.policy.policy_advisor import PolicyAdvisor, AUTO_APPLY_THRESHOLD


@pytest.fixture
def tmp_dept(tmp_path):
    """Create a temporary department directory with a blueprint and denial events."""
    dept_dir = tmp_path / "departments" / "test_dept"
    dept_dir.mkdir(parents=True)

    blueprint = {
        "version": "1",
        "name_zh": "测试部",
        "model": "claude-sonnet-4-6",
        "policy": {
            "allowed_tools": ["Bash", "Read"],
            "denied_tools": ["WebFetch"],
        },
        "max_turns": 25,
        "timeout_s": 300,
    }
    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path, "w") as f:
        yaml.dump(blueprint, f)

    # 4 tool_blocked denials for 'Edit'
    denials = []
    for i in range(4):
        denials.append({
            "ts": f"2026-03-25T0{i}:00:00",
            "department": "test_dept",
            "task_id": i,
            "type": "tool_blocked",
            "detail": f"Tool 'Edit' not in allowed_tools",
            "suggested_fix": "Add Edit to allowed_tools",
        })
    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        for d in denials:
            f.write(json.dumps(d) + "\n")

    return tmp_path, dept_dir


def test_auto_apply_adds_tool(tmp_dept):
    """tool_blocked 4次 → Edit 应自动加入 allowed_tools"""
    tmp_path, dept_dir = tmp_dept
    advisor = PolicyAdvisor()

    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        denials = advisor.load_denials("test_dept")
        assert len(denials) == 4

        agg = advisor.aggregate_denials("test_dept")
        assert agg["total"] >= AUTO_APPLY_THRESHOLD

        applied = advisor.auto_apply_rules("test_dept")

    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path) as f:
        bp = yaml.safe_load(f)

    assert "Edit" in bp["policy"]["allowed_tools"]
    assert len(applied) >= 1
    assert applied[0]["rule_type"] == "add_allowed_tool"


def test_auto_apply_respects_denied_tools(tmp_dept):
    """denied_tools 里的工具不应被自动添加到 allowed_tools"""
    tmp_path, dept_dir = tmp_dept

    # 5 denials for WebFetch (which is in denied_tools)
    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        for i in range(5):
            f.write(json.dumps({
                "ts": f"2026-03-25T0{i}:00:00",
                "department": "test_dept",
                "task_id": i,
                "type": "tool_blocked",
                "detail": "Tool 'WebFetch' not in allowed_tools",
            }) + "\n")

    advisor = PolicyAdvisor()
    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path) as f:
        bp = yaml.safe_load(f)

    assert "WebFetch" not in bp["policy"]["allowed_tools"]
    # No rules should have been applied (WebFetch is denied)
    assert not any(r.get("tool") == "WebFetch" for r in applied)


def test_auto_apply_increases_max_turns(tmp_dept):
    """max_turns 被耗尽 4次 → max_turns 应自动增加，但不超过 50"""
    tmp_path, dept_dir = tmp_dept

    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        for i in range(4):
            f.write(json.dumps({
                "ts": f"2026-03-25T0{i}:00:00",
                "department": "test_dept",
                "task_id": i,
                "type": "max_turns",
                "detail": "Agent used 25/25 turns",
            }) + "\n")

    advisor = PolicyAdvisor()
    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path) as f:
        bp = yaml.safe_load(f)

    assert bp["max_turns"] > 25
    assert bp["max_turns"] <= 50
    assert any(r["rule_type"] == "increase_max_turns" for r in applied)


def test_auto_apply_increases_timeout(tmp_dept):
    """timeout 发生 4次 → timeout_s 应自动增加，但不超过 600"""
    tmp_path, dept_dir = tmp_dept

    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        for i in range(4):
            f.write(json.dumps({
                "ts": f"2026-03-25T0{i}:00:00",
                "department": "test_dept",
                "task_id": i,
                "type": "timeout",
                "detail": "Task timed out (current limit: 300s)",
            }) + "\n")

    advisor = PolicyAdvisor()
    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path) as f:
        bp = yaml.safe_load(f)

    assert bp["timeout_s"] > 300
    assert bp["timeout_s"] <= 600
    assert any(r["rule_type"] == "increase_timeout" for r in applied)


def test_auto_apply_below_threshold(tmp_dept):
    """denial 数量不足阈值时不应应用任何规则"""
    tmp_path, dept_dir = tmp_dept

    # Only 1 denial (below threshold of 3)
    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        f.write(json.dumps({
            "ts": "2026-03-25T00:00:00",
            "department": "test_dept",
            "task_id": 1,
            "type": "tool_blocked",
            "detail": "Tool 'Edit' blocked",
        }) + "\n")

    advisor = PolicyAdvisor()
    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    assert applied == []


def test_auto_apply_logs_to_jsonl(tmp_dept):
    """auto-applied-rules.jsonl 应该被写入审计日志"""
    tmp_path, dept_dir = tmp_dept
    advisor = PolicyAdvisor()

    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    assert len(applied) >= 1

    log_path = dept_dir / "auto-applied-rules.jsonl"
    assert log_path.exists()

    lines = [json.loads(l) for l in log_path.read_text().strip().split("\n") if l.strip()]
    assert len(lines) == len(applied)
    assert all("rule_type" in entry for entry in lines)
    assert all("ts" in entry for entry in lines)


def test_auto_apply_no_duplicate_tools(tmp_dept):
    """工具已在 allowed_tools 中时不应重复添加"""
    tmp_path, dept_dir = tmp_dept

    # Bash is already in allowed_tools
    denials_path = dept_dir / "policy-denials.jsonl"
    with open(denials_path, "w") as f:
        for i in range(4):
            f.write(json.dumps({
                "ts": f"2026-03-25T0{i}:00:00",
                "department": "test_dept",
                "task_id": i,
                "type": "tool_blocked",
                "detail": "Tool 'Bash' not in allowed_tools",
            }) + "\n")

    advisor = PolicyAdvisor()
    with patch.object(advisor, "_dept_dir", return_value=dept_dir):
        applied = advisor.auto_apply_rules("test_dept")

    bp_path = dept_dir / "blueprint.yaml"
    with open(bp_path) as f:
        bp = yaml.safe_load(f)

    # Bash should appear exactly once
    assert bp["policy"]["allowed_tools"].count("Bash") == 1
    # No rule applied (already in allowed)
    assert not any(r.get("tool") == "Bash" for r in applied)
