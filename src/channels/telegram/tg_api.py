"""Telegram Bot API low-level helpers (mixin)."""
import json
import logging
import urllib.request

from src.channels import config as ch_cfg
from src.core.circuit_breaker import get_breaker, CircuitBreakerError

log = logging.getLogger(__name__)


class TelegramAPI:
    """Mixin: raw Telegram Bot API calls."""

    def _tg_api(self, method: str, params: dict) -> dict:
        """Call Telegram Bot API."""
        payload = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            breaker = get_breaker("telegram-api")
            resp = breaker.call(
                lambda: urllib.request.urlopen(req, timeout=ch_cfg.SEND_TIMEOUT)
            )
            return json.loads(resp.read())
        except CircuitBreakerError as e:
            log.warning("telegram: circuit open, retry in %.0fs", e.time_until_probe)
            return {}
        except Exception as e:
            log.warning(f"telegram: {method} failed: {e}")
            return {}

    def _tg_get_file_url(self, file_id: str) -> str:
        """Get download URL for a Telegram file."""
        resp = self._tg_api("getFile", {"file_id": file_id})
        if resp and resp.get("ok"):
            path = resp["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{self.token}/{path}"
        return ""
