"""Diff two recorded runs of the same task: where did they first diverge?"""

from __future__ import annotations

from .events import hash_payload


def event_signature(event: dict) -> tuple:
    """What counts as 'the same thing happened' for diffing purposes."""
    event_type = event["type"]
    if event_type == "llm_call":
        return (event_type, event["request_hash"], hash_payload(event["response"]))
    if event_type == "tool_call":
        return (event_type, event["name"], event["input_hash"], event["result"], event["is_error"])
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
