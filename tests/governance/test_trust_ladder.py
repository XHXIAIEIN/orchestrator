"""Tests for Trust Ladder."""
from src.governance.trust_ladder import TrustLadder


def test_first_time_not_trusted():
    """First time seeing an operation, should not be trusted."""
    ladder = TrustLadder()
    assert not ladder.is_trusted("git_push", "deploy to staging")


def test_trusted_after_approval():
    """After explicit approval, same operation should be trusted."""
    ladder = TrustLadder()
    ladder.record_approval("git_push", "deploy to staging")
    assert ladder.is_trusted("git_push", "deploy to staging")


def test_different_operation_not_trusted():
    """Approving one operation should not trust a different one."""
    ladder = TrustLadder()
    ladder.record_approval("git_push", "deploy to staging")
    assert not ladder.is_trusted("db_migrate", "run migration")


def test_trust_expires():
    """Trust should expire after TTL."""
    ladder = TrustLadder(trust_ttl_s=0)  # instant expiry
    ladder.record_approval("git_push", "deploy to staging")
    assert not ladder.is_trusted("git_push", "deploy to staging")


def test_fingerprint_change_resets_trust():
    """Config fingerprint change should reset all trust."""
    ladder = TrustLadder()
    ladder.record_approval("git_push", "deploy to staging")
    ladder.update_fingerprint("new_config_hash")
    assert not ladder.is_trusted("git_push", "deploy to staging")


def test_get_stats():
    """Should report trust stats."""
    ladder = TrustLadder()
    ladder.record_approval("git_push", "deploy")
    ladder.record_approval("db_migrate", "run migration")
    stats = ladder.get_stats()
    assert stats["trusted_operations"] == 2
