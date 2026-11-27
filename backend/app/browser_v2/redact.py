"""Pattern-based secret scrubbing for free text that leaves the process (worker last_error,
Telegram messages, API responses). Exception text from httpx/Playwright/asyncpg can carry URLs with
tokens, DSNs with passwords, bearer headers or API keys; this keeps the message useful while
removing anything that looks like a credential. Pure, no settings access (safe in any process)."""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot[REDACTED]"),  # Telegram Bot API URL
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED_TOKEN]"),  # bare Telegram token
    (re.compile(r"(?i)\b(postgres(?:ql)?|mysql|redis|amqp)(\+\w+)?://[^:\s/]+:[^@\s]+@"),
     r"\1\2://[REDACTED]@"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED_JWT]"),
    (re.compile(r"\b(?:sk|pk|rk)-(?:lf-|proj-|ant-)?[A-Za-z0-9_-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:gsk|ghp|gho|ghs|github_pat|xox[abpr])_[A-Za-z0-9_]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)([?&](?:token|access_token|refresh_token|api_key|apikey|key|secret|password|"
                r"passwd|sig|signature|code|otp|session|auth)=)[^&#\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b((?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*)[^\s,;'\"]{6,}"),
     r"\1[REDACTED]"),
)


def redact_secrets(text: object, limit: int | None = 500) -> str:
    value = "" if text is None else str(text)
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value if limit is None else value[:limit]


def describe_exception(exc: BaseException, limit: int = 300) -> str:
    """`Type: message` with secrets scrubbed and the length bounded."""
    return redact_secrets(f"{type(exc).__name__}: {exc}", limit)
