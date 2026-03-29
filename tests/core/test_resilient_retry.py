"""Tests for Resilient Retry — stolen from ChatDev 2.0."""
import pytest
from src.core.resilient_retry import RetryPolicy, resilient_call


class RateLimitError(Exception):
    status_code = 429

class AuthError(Exception):
    status_code = 401

class WrappedError(Exception):
    pass


def test_retry_on_exception_type():
    policy = RetryPolicy(max_attempts=3, retry_on_types=["RateLimitError"],
                         min_wait_s=0.01, max_wait_s=0.05)
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RateLimitError("rate limited")
        return "ok"
    result = resilient_call(flaky, policy)
    assert result == "ok"
    assert call_count["n"] == 3


def test_no_retry_on_blacklisted_type():
    policy = RetryPolicy(max_attempts=5, retry_on_types=["RateLimitError"],
                         no_retry_types=["AuthError"],
                         min_wait_s=0.01, max_wait_s=0.05)
    with pytest.raises(AuthError):
        resilient_call(lambda: (_ for _ in ()).throw(AuthError("bad auth")), policy)


def test_retry_on_status_code():
    policy = RetryPolicy(max_attempts=3, retry_on_status_codes=[429, 500, 502, 503],
                         min_wait_s=0.01, max_wait_s=0.05)
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RateLimitError("rate limited")
        return "ok"
    result = resilient_call(flaky, policy)
    assert result == "ok"


def test_no_retry_on_unmatched_status():
    policy = RetryPolicy(max_attempts=3, retry_on_status_codes=[429, 500],
                         min_wait_s=0.01, max_wait_s=0.05)
    with pytest.raises(AuthError):
        resilient_call(lambda: (_ for _ in ()).throw(AuthError("401")), policy)


def test_retry_on_message_substring():
    policy = RetryPolicy(max_attempts=3, retry_on_substrings=["temporarily unavailable", "try again"],
                         min_wait_s=0.01, max_wait_s=0.05)
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise Exception("Service temporarily unavailable")
        return "ok"
    result = resilient_call(flaky, policy)
    assert result == "ok"


def test_exception_chain_traversal():
    policy = RetryPolicy(max_attempts=3, retry_on_types=["RateLimitError"],
                         min_wait_s=0.01, max_wait_s=0.05)
    call_count = {"n": 0}
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            try:
                raise RateLimitError("inner")
            except RateLimitError as inner:
                raise WrappedError("outer") from inner
        return "ok"
    result = resilient_call(flaky, policy)
    assert result == "ok"
    assert call_count["n"] == 2


def test_max_attempts_exhausted():
    policy = RetryPolicy(max_attempts=2, retry_on_types=["Exception"],
                         min_wait_s=0.01, max_wait_s=0.05)
    with pytest.raises(Exception, match="always fails"):
        resilient_call(lambda: (_ for _ in ()).throw(Exception("always fails")), policy)


def test_disabled_policy():
    policy = RetryPolicy(enabled=False)
    with pytest.raises(Exception):
        resilient_call(lambda: (_ for _ in ()).throw(Exception("fail")), policy)
