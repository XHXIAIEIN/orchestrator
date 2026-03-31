"""重试策略。灵感：OpenCLI 的 daemon-client 3 次重试。"""
import logging
import random
import time

from src.collectors.errors import TransientError, PermanentError

log = logging.getLogger(__name__)


def with_retry(fn, max_retries=3, base_delay=0.5, max_delay=10.0):
    """指数退避重试。仅对 TransientError 重试。"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except TransientError as e:
            last_error = e
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay *= 0.8 + random.random() * 0.4
            log.warning(f"retry: attempt {attempt+1}/{max_retries}, "
                        f"retrying in {delay:.1f}s: {e.code}")
            time.sleep(delay)
        except PermanentError:
            raise
    raise last_error
