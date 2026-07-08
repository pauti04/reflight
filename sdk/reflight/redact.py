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
