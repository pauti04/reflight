"""Diff two recorded runs of the same task: where did they first diverge?

Replay compares exact hashes; diffing compares *behavior*. Live-API responses
carry volatile identifiers (message ids, tool_use ids, created timestamps)
that differ between two behaviorally identical runs — and those ids flow back
into subsequent request messages. So diff signatures are computed over
recordings with identifier fields stripped: two runs that did the same thing
diff as identical even though no two live runs share an id.
"""

from __future__ import annotations

from typing import Any

from .events import hash_payload

# identifiers, not behavior — excluded from cross-run comparison
VOLATILE_KEYS = frozenset({"id", "created", "system_fingerprint", "tool_use_id"})


def normalize(obj: Any) -> Any:
    """Recursively drop volatile identifier fields for behavioral comparison."""
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def event_signature(event: dict) -> tuple:
    """What counts as 'the same thing happened' for diffing purposes."""
    event_type = event["type"]
    if event_type == "llm_call":
        return (
            event_type,
            hash_payload(normalize(event["request"])),
            hash_payload(normalize(event["response"])),
        )
    if event_type == "tool_call":
        return (
            event_type,
            event["name"],
            event["input_hash"],
            hash_payload(normalize(event["result"])),
            event["is_error"],
        )
    if event_type == "run_start":
        return (event_type, event["task"])
    if event_type == "run_end":
        return (event_type, event["status"], event["final_text"])
    if event_type == "state_snapshot":
        return (event_type, event["label"], event["state_hash"])
    return (event_type,)


def diff_runs(events_a: list[dict], events_b: list[dict]) -> dict:
    """Returns the index of the first differing event, or None if one run is a
    prefix of the other (divergence None + equal lengths == identical runs)."""
    divergence = None
    for i, (a, b) in enumerate(zip(events_a, events_b)):
        if event_signature(a) != event_signature(b):
            divergence = i
            break
    identical = divergence is None and len(events_a) == len(events_b)
    return {
        "divergence_seq": divergence,
        "identical": identical,
        "a_len": len(events_a),
        "b_len": len(events_b),
    }
