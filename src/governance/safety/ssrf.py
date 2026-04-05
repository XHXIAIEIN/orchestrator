# src/governance/safety/ssrf.py
"""
SSRF Protection — URL safety validation before external fetches.

Stolen from Firecrawl assertSafeTargetUrl() (R5) + standard SSRF best practices.
Prevents server-side request forgery by validating URLs before fetch:
  1. Protocol whitelist (http/https only)
  2. DNS resolution → IP check (blocks private/internal/reserved ranges)
  3. Domain allowlist for known-safe service endpoints

Usage:
    from src.governance.safety.ssrf import assert_safe_url, SSRFError
    assert_safe_url(url)  # raises SSRFError if unsafe

Integration points:
    - channels/media.py::download_url()        — user-adjacent media fetch
    - collectors/yaml_runner.py::_read_http()   — config-driven HTTP (optional)
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Domains that bypass private-IP checks (known safe service endpoints).
# Only add domains whose IPs we trust unconditionally.
DOMAIN_ALLOWLIST = frozenset({
    # Telegram Bot API (file downloads)
    "api.telegram.org",
    # WeChat CDN
    "novac2c.cdn.weixin.qq.com",
    # YouTube oEmbed (collector)
    "www.youtube.com",
})

# Hostnames that are always blocked regardless of allowlist.
# Catches common cloud metadata endpoints.
HOSTNAME_BLOCKLIST = frozenset({
    "metadata.google.internal",
    "metadata.google.com",
})

# ── Exceptions ────────────────────────────────────────────────────


class SSRFError(ValueError):
    """URL failed SSRF safety check."""


# ── Core ──────────────────────────────────────────────────────────


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, internal, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → block
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_host(hostname: str, port: int | None) -> list[str]:
    """Resolve hostname to IP addresses via DNS."""
    try:
        infos = socket.getaddrinfo(
            hostname,
            port or 443,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as e:
        raise SSRFError(f"DNS resolution failed for '{hostname}': {e}")
    if not infos:
        raise SSRFError(f"No DNS results for '{hostname}'")
    return [sockaddr[0] for _, _, _, _, sockaddr in infos]


def assert_safe_url(url: str, *, allow_internal: bool = False) -> None:
    """
    Validate that a URL is safe to fetch (no SSRF risk).

    Checks (in order):
      1. Scheme in {http, https}
      2. Hostname present and not in blocklist
      3. If hostname in domain allowlist → pass (skip IP check)
      4. DNS-resolve hostname → every resolved IP must be public

    Args:
        url: The URL to validate.
        allow_internal: If True, skip private-IP checks.
            Use for known-safe internal calls (TTS, LLM, browser debug).

    Raises:
        SSRFError: URL is unsafe.
    """
    parsed = urlparse(url)

    # 1. Protocol
    if parsed.scheme not in ALLOWED_SCHEMES:
        _block(url, f"blocked scheme '{parsed.scheme}' (allowed: {', '.join(ALLOWED_SCHEMES)})")

    # 2. Hostname
    hostname = parsed.hostname
    if not hostname:
        _block(url, "no hostname")

    if hostname in HOSTNAME_BLOCKLIST:
        _block(url, f"blocked hostname '{hostname}' (cloud metadata endpoint)")

    # 3. Allowlisted domain — trusted, skip IP resolution
    if hostname in DOMAIN_ALLOWLIST:
        return

    # 4. Skip IP checks for known-internal calls
    if allow_internal:
        return

    # 5. Resolve and check every IP
    ips = _resolve_host(hostname, parsed.port)
    for ip_str in ips:
        if _is_private_ip(ip_str):
            _block(url, f"resolved to private/internal IP {ip_str}")


def is_safe_url(url: str, *, allow_internal: bool = False) -> bool:
    """Non-raising variant — returns True if URL passes SSRF checks."""
    try:
        assert_safe_url(url, allow_internal=allow_internal)
        return True
    except SSRFError:
        return False


def _block(url: str, reason: str) -> None:
    """Log and raise SSRFError."""
    # Truncate URL for logging (avoid leaking full tokens/params)
    display_url = url[:120] + ("..." if len(url) > 120 else "")
    log.warning(f"SSRF blocked: {reason} — url={display_url}")
    raise SSRFError(f"SSRF blocked: {reason}")
