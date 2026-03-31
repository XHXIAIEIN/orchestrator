import pytest
from src.collectors.errors import TransientError, PermanentError
from src.collectors.retry import with_retry


class TestErrors:
    def test_transient_is_retryable(self):
        e = TransientError("TIMEOUT", "网络超时")
        assert e.retryable is True

    def test_permanent_not_retryable(self):
        e = PermanentError("NOT_FOUND", "路径不存在")
        assert e.retryable is False


class TestRetry:
    def test_success_no_retry(self):
        calls = []
        def fn():
            calls.append(1)
            return "ok"
        result = with_retry(fn, max_retries=3)
        assert result == "ok"
        assert len(calls) == 1

    def test_transient_retry_then_success(self):
        attempts = []
        def fn():
            attempts.append(1)
            if len(attempts) < 3:
                raise TransientError("TIMEOUT", "timeout")
            return "ok"
        result = with_retry(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert len(attempts) == 3

    def test_permanent_no_retry(self):
        def fn():
            raise PermanentError("NOT_FOUND", "/bad/path")
        with pytest.raises(PermanentError):
            with_retry(fn, max_retries=3, base_delay=0.01)

    def test_transient_exhausted(self):
        def fn():
            raise TransientError("LOCK", "file locked")
        with pytest.raises(TransientError):
            with_retry(fn, max_retries=2, base_delay=0.01)
