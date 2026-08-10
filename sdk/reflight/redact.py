"""Scrub secrets from recordings before they touch disk.

Recordings never contain API keys by construction — Reflight records the
*arguments* your agent passes (messages, tools), not HTTP headers. But tool
inputs and results can contain anything your tools touch. The redact hook
runs over every event before it's written:

    session = reflight.record(..., redact=reflight.redact_patterns(r"sk-\\w+"))

Hash fields are never rewritten — replay compares live-computed hashes against
them, so redaction keeps recordings replayable. The tradeoff is honest: if
your agent's *behavior* depended on a redacted value, replay serves the mask.
"""

from __future__ import annotations

import re
from typing import Any, Callable

MASK = "▮▮▮redacted▮▮▮"

# replay integrity: these carry hashes of the *live* values and must survive
_PROTECTED = ("request_hash", "input_hash", "state_hash")


def redact_patterns(*patterns: str, mask: str = MASK) -> Callable[[dict], dict]:
    """An event transform masking every regex match in string values."""
    compiled = [re.compile(pattern) for pattern in patterns]

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for regex in compiled:
                value = regex.sub(mask, value)
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    def transform(event: dict) -> dict:
        protected = {key: event[key] for key in _PROTECTED if key in event}
        scrubbed = scrub(event)
        scrubbed.update(protected)
        return scrubbed

    return transform


# The shapes that actually leak through tool results in practice. Deliberately
# conservative: matching too much silently corrupts recordings, and a missed
# secret is visible in review while an over-eager mask is not.
COMMON_PATTERNS: dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "us_phone": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
    "us_ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]?){13,15}\d\b",
    "bearer_token": r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}",
    "openai_key": r"\bsk-[A-Za-z0-9_-]{20,}\b",
    "anthropic_key": r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
}


def redact_common(*extra: str, mask: str = MASK) -> Callable[[dict], dict]:
    """redact_patterns preloaded with COMMON_PATTERNS (emails, phones, SSNs,
    card numbers, bearer tokens, well-known API-key shapes, private-key
    blocks). Pass extra patterns for anything domain-specific:

        session = reflight.record(..., redact=reflight.redact_common(r"CUST-\\d+"))
    """
    return redact_patterns(*COMMON_PATTERNS.values(), *extra, mask=mask)
