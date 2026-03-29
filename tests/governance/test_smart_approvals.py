"""Tests for Smart Approvals."""
from src.governance.smart_approvals import (
    SmartApprovals, normalize_command,
)


def test_normalize_strips_uuids():
    assert "<UUID>" in normalize_command("delete task 550e8400-e29b-41d4-a716-446655440000")


def test_normalize_strips_large_numbers():
    result = normalize_command("process batch 1234567890")
    assert "<NUM>" in result


def test_normalize_keeps_small_numbers():
    result = normalize_command("listen on port 8080")
    assert "8080" in result


def test_normalize_strips_quoted_strings():
    result = normalize_command('git commit -m "fix bug"')
    assert "<STR>" in result


def test_normalize_strips_single_quoted_strings():
    result = normalize_command("echo 'hello world'")
    assert "<STR>" in result


def test_not_auto_approve_first_time():
    sa = SmartApprovals(threshold=2)
    assert not sa.should_auto_approve("git push origin main")


def test_auto_approve_after_threshold():
    sa = SmartApprovals(threshold=2)
    sa.record("git push origin feature", "approve")
    assert not sa.should_auto_approve("git push origin feature")
    sa.record("git push origin feature", "approve")
    assert sa.should_auto_approve("git push origin feature")


def test_deny_resets_trust():
    sa = SmartApprovals(threshold=2)
    sa.record("rm -rf /tmp", "approve")
    sa.record("rm -rf /tmp", "approve")
    sa.record("rm -rf /tmp", "deny")
    assert not sa.should_auto_approve("rm -rf /tmp")


def test_decay_expires_trust():
    sa = SmartApprovals(threshold=1, decay_days=0)  # instant decay
    sa.record("ls -la", "approve")
    # Approval is in the past, decay_days=0 means instant expiry
    import time
    time.sleep(0.01)
    assert not sa.should_auto_approve("ls -la")


def test_get_trusted_commands():
    sa = SmartApprovals(threshold=2)
    sa.record("git status", "approve")
    sa.record("git status", "approve")
    sa.record("docker ps", "approve")
    trusted = sa.get_trusted_commands()
    assert len(trusted) == 1  # only git status met threshold
    assert trusted[0]["pattern"] == "git status"


def test_revoke_trust():
    sa = SmartApprovals(threshold=1)
    sa.record("dangerous cmd", "approve")
    sa.revoke_trust("dangerous cmd")
    assert not sa.should_auto_approve("dangerous cmd")


def test_stats():
    sa = SmartApprovals(threshold=1)
    sa.record("cmd1", "approve")
    sa.should_auto_approve("cmd1")
    stats = sa.get_stats()
    assert stats["recorded"] == 1
    assert stats["auto_approved"] == 1
    assert stats["tracked_commands"] == 1


def test_deny_after_approve_blocks():
    """Denial after approval should block auto-approve even with enough approvals."""
    sa = SmartApprovals(threshold=2)
    sa.record("risky cmd", "approve")
    sa.record("risky cmd", "approve")
    sa.record("risky cmd", "deny")
    # Deny resets approvals to 0, so threshold not met
    assert not sa.should_auto_approve("risky cmd")


def test_re_approve_after_deny():
    """Can rebuild trust after a denial."""
    sa = SmartApprovals(threshold=2)
    sa.record("cmd", "approve")
    sa.record("cmd", "approve")
    sa.record("cmd", "deny")
    # Now re-approve
    sa.record("cmd", "approve")
    sa.record("cmd", "approve")
    assert sa.should_auto_approve("cmd")


def test_normalize_idempotent():
    cmd = "git push origin main"
    assert normalize_command(cmd) == normalize_command(normalize_command(cmd))


def test_auto_approved_count_increments():
    sa = SmartApprovals(threshold=1)
    sa.record("git status", "approve")
    sa.should_auto_approve("git status")
    sa.should_auto_approve("git status")
    trusted = sa.get_trusted_commands()
    assert trusted[0]["auto_approved"] == 2
