"""Event schema v1: the contract between recorder, replayer, store, and UI.

Validation is advisory — ingest warns about malformed runs instead of dropping
them, because a flight recorder that discards evidence is worse than useless.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

REQUIRED_FIELDS: dict[str, set[str]] = {
    "run_start": {"task"},
    "llm_call": {"request", "request_hash", "response"},
    "tool_call": {"name", "input", "input_hash", "tool_use_id", "result", "is_error"},
    "state_snapshot": {"label", "state", "state_hash"},
    "error": {"error_type", "message"},
    "entropy": {"seeds", "time", "time_ns", "uuid"},
    "run_end": {"status", "final_text", "input_tokens", "output_tokens"},
}

EVENT_TYPES = set(REQUIRED_FIELDS)


def validate_event(event: dict) -> list[str]:
    problems = []
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        return [f"seq {event.get('seq')}: unknown event type {event_type!r}"]
    for field in ("seq", "ts", "schema"):
        if field not in event:
            problems.append(f"seq {event.get('seq')}: missing {field!r}")
    for field in REQUIRED_FIELDS[event_type] - set(event):
        problems.append(f"seq {event.get('seq')}: {event_type} missing {field!r}")
    return problems


def validate_run(events: list[dict]) -> list[str]:
    problems = []
    for event in events:
        problems.extend(validate_event(event))
    seqs = [e.get("seq") for e in events]
    if seqs != list(range(len(events))):
        problems.append("event seqs are not contiguous from 0")
    if events and events[0].get("type") != "run_start":
        problems.append("first event is not run_start")
    end_count = sum(1 for e in events if e.get("type") == "run_end")
    if end_count > 1:
        problems.append(f"{end_count} run_end events (expected at most 1)")
    return problems
