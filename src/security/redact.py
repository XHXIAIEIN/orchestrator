"""Comprehensive secret redaction module — R59 steal from hermes-agent `agent/redact.py`.

Provides 30+ compiled patterns covering API keys, cloud credentials, database
connection strings, JWTs, and generic secret assignments.  Exposes a drop-in
``RedactingFormatter`` for stdlib logging and a one-call ``install()`` helper.

Design decisions:
- ``_REDACT_ENABLED`` is captured at import time from the environment variable
  ``ORCHESTRATOR_REDACT_SECRETS`` (default: enabled).  Runtime env tampering
  cannot flip the flag after the module is loaded.
- All patterns are compiled eagerly at import; zero per-call overhead.
- Connection strings mask only the password segment — the rest of the URL
  (host, port, db name) remains visible for debugging.
"""

from __future__ import annotations

import logging
import os
import re

# ── Runtime toggle (snapshot at import — cannot be changed after load) ────────

_REDACT_ENABLED: bool = os.environ.get(
    "ORCHESTRATOR_REDACT_SECRETS", "true"
).lower() not in ("false", "0", "no", "off")

# ── Pattern library ───────────────────────────────────────────────────────────
# Each entry: (compiled_pattern, description)
# For two-group patterns the first group is a non-secret prefix that is kept
# in the output; the second group is the secret that gets masked.
# Single-group patterns replace the entire match.

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ── API Keys by provider ─────────────────────────────────────────────────

    # OpenAI / Anthropic generic secret key (sk- prefix, not caught by more
    # specific patterns below)
    (
        re.compile(r'\bsk-(?!ant-|proj-)([a-zA-Z0-9]{20,})\b'),
        "openai-api-key",
    ),
    # Anthropic specific key
    (
        re.compile(r'\b(sk-ant-)([a-zA-Z0-9\-]{20,})\b'),
        "anthropic-api-key",
    ),
    # OpenAI project key
    (
        re.compile(r'\b(sk-proj-)([a-zA-Z0-9\-]{20,})\b'),
        "openai-project-key",
    ),
    # GitHub PAT (classic)
    (
        re.compile(r'\b(ghp_)([a-zA-Z0-9]{36,})\b'),
        "github-pat",
    ),
    # GitHub OAuth token
    (
        re.compile(r'\b(gho_)([a-zA-Z0-9]{36,})\b'),
        "github-oauth-token",
    ),
    # GitHub App installation token
    (
        re.compile(r'\b(ghs_)([a-zA-Z0-9]{36,})\b'),
        "github-app-token",
    ),
    # GitHub fine-grained PAT
    (
        re.compile(r'\b(github_pat_)([a-zA-Z0-9_]{20,})\b'),
        "github-fine-grained-pat",
    ),
    # Slack token (xoxb / xoxp / xoxa / xoxr / xoxs)
    (
        re.compile(r'\b(xox[bpars]-)([a-zA-Z0-9\-]+)\b'),
        "slack-token",
    ),
    # Google API key
    (
        re.compile(r'\b(AIza)([a-zA-Z0-9\-_]{35})\b'),
        "google-api-key",
    ),
    # AWS access key ID
    (
        re.compile(r'\b(AKIA)([A-Z0-9]{16})\b'),
        "aws-access-key-id",
    ),
    # Google OAuth 2.0 access token
    (
        re.compile(r'\b(ya29\.)([a-zA-Z0-9_\-]+)\b'),
        "google-oauth-token",
    ),

    # ── Cloud & Infrastructure ───────────────────────────────────────────────

    # Google OAuth2 client ID
    (
        re.compile(r'\b([a-zA-Z0-9]{32})(\.apps\.googleusercontent\.com)\b'),
        "google-client-id",
    ),
    # JWT — header.payload.signature  (mask payload + signature)
    (
        re.compile(r'\b(eyJ[a-zA-Z0-9\-_]+\.)([a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]*)\b'),
        "jwt-token",
    ),
    # SendGrid API key
    (
        re.compile(r'\b(SG\.)([a-zA-Z0-9\-_]{22,})\b'),
        "sendgrid-api-key",
    ),
    # Brevo / Sendinblue API key
    (
        re.compile(r'\b(xkeysib-)([a-zA-Z0-9]{50,})\b'),
        "brevo-api-key",
    ),
    # Stripe restricted key
    (
        re.compile(r'\b(rk_live_)([a-zA-Z0-9]{20,})\b'),
        "stripe-restricted-key",
    ),
    # Stripe secret key
    (
        re.compile(r'\b(sk_live_)([a-zA-Z0-9]{20,})\b'),
        "stripe-secret-key",
    ),
    # Stripe publishable key
    (
        re.compile(r'\b(pk_live_)([a-zA-Z0-9]{20,})\b'),
        "stripe-publishable-key",
    ),
    # Stripe webhook secret
    (
        re.compile(r'\b(whsec_)([a-zA-Z0-9]{20,})\b'),
        "stripe-webhook-secret",
    ),
    # Square API key
    (
        re.compile(r'\b(sq0[a-z]{3}-)([a-zA-Z0-9\-_]{22,})\b'),
        "square-api-key",
    ),

    # ── Messaging & Social ───────────────────────────────────────────────────

    # Telegram bot token  (digits:base62)
    (
        re.compile(r'\b(\d{8,}:)([A-Za-z0-9_\-]{30,})\b'),
        "telegram-bot-token",
    ),
    # Facebook / Meta access token
    (
        re.compile(r'\b(EAA)([a-zA-Z0-9]+)\b'),
        "facebook-access-token",
    ),

    # ── Database & Storage connection strings ────────────────────────────────
    # Mask only the password portion of the URI, keep the rest visible.

    # MongoDB  mongodb[+srv]://user:PASS@host/db
    (
        re.compile(
            r'(mongodb(?:\+srv)?://[^:@/\s]+:)([^@\s]+)(@[^\s]*)',
            re.IGNORECASE,
        ),
        "mongodb-connection-password",
    ),
    # PostgreSQL  postgres[ql]://user:PASS@host/db
    (
        re.compile(
            r'(postgres(?:ql)?://[^:@/\s]+:)([^@\s]+)(@[^\s]*)',
            re.IGNORECASE,
        ),
        "postgresql-connection-password",
    ),
    # MySQL  mysql://user:PASS@host/db
    (
        re.compile(
            r'(mysql://[^:@/\s]+:)([^@\s]+)(@[^\s]*)',
            re.IGNORECASE,
        ),
        "mysql-connection-password",
    ),
    # Redis  redis://[:PASS@]host
    (
        re.compile(
            r'(redis://(?:[^:@/\s]+:)?)([^@\s]+)(@[^\s]+)',
            re.IGNORECASE,
        ),
        "redis-connection-password",
    ),

    # ── Generic secrets ──────────────────────────────────────────────────────

    # PEM private key block (single-line match for the header; presence alone
    # is flagged — actual key bytes often span many lines)
    (
        re.compile(
            r'(-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----)'
            r'([A-Za-z0-9+/=\s]*?)'
            r'(-----END\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----)',
            re.DOTALL,
        ),
        "pem-private-key",
    ),
    # Bearer token
    (
        re.compile(r'(Bearer\s+)([A-Za-z0-9\-_.~+/]{20,})', re.IGNORECASE),
        "bearer-token",
    ),
    # HTTP Basic auth
    (
        re.compile(r'(Basic\s+)([A-Za-z0-9+/=]{20,})', re.IGNORECASE),
        "basic-auth",
    ),
    # password = / password: assignments (8+ char value)
    (
        re.compile(
            r'(?i)(password\s*[=:]\s*["\']?)([^\s"\']{8,})',
        ),
        "password-assignment",
    ),
    # secret = / secret: assignments (8+ char value)
    (
        re.compile(
            r'(?i)((?:api_?)?secret\s*[=:]\s*["\']?)([^\s"\']{8,})',
        ),
        "secret-assignment",
    ),
    # AWS secret access key (value in env/config, not the key ID)
    (
        re.compile(
            r'(?i)(AWS_SECRET_ACCESS_KEY\s*[=:]\s*["\']?)([A-Za-z0-9/+]{40})',
        ),
        "aws-secret-access-key-value",
    ),
]


# ── Core helpers ──────────────────────────────────────────────────────────────

def _mask_token(token: str) -> str:
    """Keep first 6 + last 4 chars for debugging. Short tokens → '***'."""
    if len(token) < 18:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _apply_pattern(text: str, pattern: re.Pattern, description: str) -> str:
    """Apply a single compiled pattern, masking the secret capture group."""

    def _replacer(m: re.Match) -> str:
        groups = m.groups()
        if len(groups) == 0:
            # Whole-match redaction (should not happen with current patterns)
            return _mask_token(m.group(0))
        if len(groups) == 1:
            # Single-group: entire match is the secret
            return _mask_token(groups[0])
        if len(groups) == 2:
            # Two-group: prefix + secret
            return groups[0] + _mask_token(groups[1])
        if len(groups) == 3:
            # Three-group: prefix + secret + suffix (connection strings, PEM)
            if description == "pem-private-key":
                return groups[0] + "[REDACTED]" + groups[2]
            return groups[0] + _mask_token(groups[1]) + groups[2]
        # Fallback for unexpected group counts
        return m.group(0)

    return pattern.sub(_replacer, text)


def redact(text: str) -> str:
    """Apply all redaction patterns to *text*.

    Returns the redacted string.  No-op (returns *text* unchanged) when
    ``ORCHESTRATOR_REDACT_SECRETS=false`` was set before module import.
    """
    if not _REDACT_ENABLED:
        return text
    for pattern, description in _PATTERNS:
        text = _apply_pattern(text, pattern, description)
    return text


def redact_dict(d: dict) -> dict:
    """Recursively redact string values in *d* (for structured logging).

    Keys are never modified.  Non-string leaf values are left unchanged.
    Returns a new dict; the original is not mutated.
    """
    if not _REDACT_ENABLED:
        return d
    result: dict = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = redact(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [
                redact(item) if isinstance(item, str)
                else redact_dict(item) if isinstance(item, dict)
                else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# ── Logging integration ───────────────────────────────────────────────────────

class RedactingFormatter(logging.Formatter):
    """Drop-in log formatter that auto-redacts all secrets.

    Usage::

        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter(fmt="%(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)

    Or use :func:`install` for a one-liner that patches existing handlers.
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        result = super().format(record)
        return redact(result)


_installed_loggers: set[str] = set()


def install(logger_name: str = "", *, fmt: str | None = None) -> None:
    """Install :class:`RedactingFormatter` on existing handlers of *logger_name*.

    Args:
        logger_name: Logger to patch.  Empty string (default) means the root
            logger, which covers all loggers in the process.
        fmt: Optional format string passed to :class:`RedactingFormatter`.
            When *None*, the existing formatter's ``_fmt`` is preserved
            (or stdlib default is used when there is no existing formatter).

    Idempotent: calling multiple times with the same *logger_name* is safe.
    """
    if logger_name in _installed_loggers:
        return
    _installed_loggers.add(logger_name)

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()

    for handler in logger.handlers:
        existing = handler.formatter
        if isinstance(existing, RedactingFormatter):
            # Already patched — nothing to do for this handler.
            continue
        if fmt is not None:
            new_fmt = fmt
        elif existing is not None and existing._fmt:
            new_fmt = existing._fmt
        else:
            new_fmt = None  # let RedactingFormatter use its own default

        kwargs: dict = {}
        if existing is not None:
            # Preserve datefmt and style if the existing formatter has them.
            if existing.datefmt:
                kwargs["datefmt"] = existing.datefmt
            if hasattr(existing, "_style") and existing._style:
                kwargs["style"] = type(existing._style).default_format[0]  # type: ignore[attr-defined]

        rf = RedactingFormatter(fmt=new_fmt, **kwargs)
        handler.setFormatter(rf)


# ── Public API ────────────────────────────────────────────────────────────────

__all__ = [
    "redact",
    "redact_dict",
    "RedactingFormatter",
    "install",
]
