"""Rule-based failure classification over a run's events.

Each rule targets one of the known agent failure modes; findings carry a
confidence so a downstream filter (or the eventual LLM judge) can rank them.
Rules are deliberately conservative — a flight recorder that cries wolf gets
ignored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

FAIL = "fail"
WARN = "warn"


@dataclass
class Finding:
    label: str  # loop | wrong_tool_args | tool_error_cascade | tool_error | runaway | crash | cost_blowout
    severity: str  # fail | warn
    confidence: float
    seq: int  # anchoring event
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def verdict(findings: list[Finding]) -> str:
    if any(f.severity == FAIL for f in findings):
        return "fail"
    if findings:
        return "warn"
    return "pass"


def classify(events: list[dict], max_output_tokens: int = 20_000) -> list[Finding]:
    findings: list[Finding] = []
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    end = next((e for e in events if e["type"] == "run_end"), None)

    # crash: the agent process raised; governor kills get their own label so
    # the dashboard shows the save, not a generic crash
    for event in events:
        if event["type"] == "error":
            label = "governor_kill" if event["error_type"] == "GovernorKill" else "crash"
            findings.append(
                Finding(
                    label, FAIL, 1.0, event["seq"], f"{event['error_type']}: {event['message']}"
                )
            )

    # runaway: never reached a final answer
    if end and end["status"] == "max_turns_exceeded":
        findings.append(
            Finding("runaway", FAIL, 0.9, end["seq"], "hit the turn limit without finishing")
        )

    findings.extend(_loops(tool_calls))
    findings.extend(_wrong_tool_args(events, tool_calls))
    findings.extend(_error_cascades(tool_calls, findings))

    # cost blowout: output token spend beyond any sane single-task budget
    if end and (end.get("output_tokens") or 0) > max_output_tokens:
        findings.append(
            Finding(
                "cost_blowout",
                WARN,
                0.7,
                end["seq"],
                f"{end['output_tokens']} output tokens (threshold {max_output_tokens})",
            )
        )

    return sorted(findings, key=lambda f: f.seq)


def _loops(tool_calls: list[dict], threshold: int = 3) -> list[Finding]:
    """N consecutive tool calls with identical name AND identical arguments."""
    findings = []
    streak: list[dict] = []
    for call in tool_calls + [None]:  # sentinel flushes the last streak
        key = (call["name"], call["input_hash"]) if call else None
        if streak and key == (streak[0]["name"], streak[0]["input_hash"]):
            streak.append(call)
            continue
        if len(streak) >= threshold:
            first = streak[0]
            findings.append(
                Finding(
                    "loop",
                    FAIL,
                    min(0.5 + 0.15 * len(streak), 0.95),
                    streak[-1]["seq"],
                    f"{first['name']}({first['input']}) repeated {len(streak)}× "
                    "with identical arguments",
                )
            )
        streak = [call] if call else []
    return findings


def _tool_schemas(events: list[dict]) -> dict[str, dict]:
    """Tool input schemas as the model saw them, from recorded llm_call requests."""
    schemas: dict[str, dict] = {}
    for event in events:
        if event["type"] != "llm_call":
            continue
        for tool in event["request"].get("tools") or []:
            if isinstance(tool, dict) and "input_schema" in tool:
                schemas[tool["name"]] = tool["input_schema"]
    return schemas


_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_problems(schema: dict | None, tool_input: dict) -> list[str]:
    if not schema:
        return []
    problems = []
    properties = schema.get("properties") or {}
    for field in schema.get("required") or []:
        if field not in tool_input:
            problems.append(f"missing required argument {field!r}")
    for key, value in tool_input.items():
        if properties and key not in properties:
            problems.append(f"unknown argument {key!r}")
            continue
        expected = _JSON_TYPES.get((properties.get(key) or {}).get("type", ""))
        if expected and not isinstance(value, expected):
            problems.append(f"{key!r} should be {properties[key]['type']}")
    return problems


def _wrong_tool_args(events: list[dict], tool_calls: list[dict]) -> list[Finding]:
    schemas = _tool_schemas(events)
    findings = []
    for call in tool_calls:
        problems = _schema_problems(schemas.get(call["name"]), call["input"])
        if problems:
            findings.append(
                Finding("wrong_tool_args", FAIL, 0.85, call["seq"], "; ".join(problems))
            )
        elif call["is_error"] and str(call["result"]).startswith("TypeError"):
            findings.append(Finding("wrong_tool_args", FAIL, 0.7, call["seq"], call["result"]))
    return findings


def _error_cascades(tool_calls: list[dict], existing: list[Finding]) -> list[Finding]:
    findings = []
    errors = [c for c in tool_calls if c["is_error"]]
    consecutive = 0
    worst = 0
    anchor = None
    for call in tool_calls:
        consecutive = consecutive + 1 if call["is_error"] else 0
        if consecutive > worst:
            worst, anchor = consecutive, call["seq"]
    if worst >= 2:
        findings.append(
            Finding(
                "tool_error_cascade", FAIL, 0.8, anchor, f"{worst} consecutive tool errors"
            )
        )
    elif errors and not any(f.label == "wrong_tool_args" for f in existing):
        first = errors[0]
        findings.append(
            Finding(
                "tool_error",
                WARN,
                0.9,
                first["seq"],
                f"{first['name']} errored: {str(first['result'])[:80]}",
            )
        )
    return findings
