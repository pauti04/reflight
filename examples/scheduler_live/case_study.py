#!/usr/bin/env python3
"""Live case study: the same scheduling request, N times, against a real model.

    OPENAI_API_KEY=... uv run --with openai python examples/scheduler_live/case_study.py [N]

Nothing here is scripted: a real model plans against a real (fixture) calendar
through Reflight's recorder, using the N-run executor and a hard budget cap.
The task is honest work for a small model — anchor "next Wednesday" from a
known today, then find a conflict-free 45-minute slot on a busy afternoon:

    busy on 2026-07-15:  15:00–16:00  and  16:30–17:15
    requested            15:30  (conflicts)
    only correct answer  17:15–18:00

Whatever the model actually does — books the right slot, books over a
meeting and gets rejected, picks the wrong Wednesday — is recorded, scored,
and written up verbatim in docs/case-study.md.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from reflight import store
from reflight.events import read_events
from reflight.executor import run_repeated

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"

MODEL = "gpt-4o-mini"
TODAY = {"date": "2026-07-10", "weekday": "Friday"}
TARGET_DATE = "2026-07-15"  # next Wednesday from the anchor Friday
BUSY = [("15:00", "16:00"), ("16:30", "17:15")]
WINDOW = ("13:00", "18:00")
CORRECT_SLOT = "17:15"

SYSTEM = (
    "You are a scheduling assistant with calendar tools. Anchor every "
    "relative date with get_today before reasoning about it. Times are "
    "24-hour HH:MM strings; durations are integer minutes. Check "
    "availability before booking. Book exactly one meeting, then confirm "
    "to the user in one sentence stating the date and start time."
)

TASK = (
    "Book a 45-minute design sync next Wednesday at 3:30pm. If that slot "
    "conflicts with an existing meeting, book the next conflict-free "
    "45-minute slot that same afternoon (between 13:00 and 18:00)."
)

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_today",
            "description": "Today's date and weekday.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Busy blocks overlapping a proposed slot, plus the day's full busy list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "start_24h": {"type": "string", "description": "HH:MM"},
                    "duration_minutes": {"type": "integer"},
                },
                "required": ["date", "start_24h", "duration_minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_meeting",
            "description": "Book the meeting. Rejects slots that overlap a busy block.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "start_24h": {"type": "string", "description": "HH:MM"},
                    "duration_minutes": {"type": "integer"},
                    "title": {"type": "string"},
                },
                "required": ["date", "start_24h", "duration_minutes", "title"],
            },
        },
    },
]


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _validate(date: str, start_24h: str, duration_minutes: int) -> None:
    if not isinstance(duration_minutes, int):
        raise TypeError(
            f"duration_minutes must be an integer, got "
            f"{type(duration_minutes).__name__} {duration_minutes!r}"
        )
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    if len(start_24h) != 5 or start_24h[2] != ":":
        raise ValueError(f"start_24h must be HH:MM, got {start_24h!r}")


def _conflicts(date: str, start_24h: str, duration_minutes: int) -> list[dict]:
    if date != TARGET_DATE:
        return []
    start = _minutes(start_24h)
    end = start + duration_minutes
    return [
        {"busy_from": b0, "busy_to": b1}
        for b0, b1 in BUSY
        if start < _minutes(b1) and end > _minutes(b0)
    ]


def make_tools(run_dir: Path) -> dict:
    del run_dir

    def get_today() -> str:
        return json.dumps(TODAY)

    def check_availability(date: str, start_24h: str, duration_minutes: int) -> str:
        _validate(date, start_24h, duration_minutes)
        overlapping = _conflicts(date, start_24h, duration_minutes)
        busy = (
            [{"busy_from": b0, "busy_to": b1} for b0, b1 in BUSY]
            if date == TARGET_DATE
            else []
        )
        return json.dumps(
            {"available": not overlapping, "conflicts": overlapping, "busy_that_day": busy}
        )

    def book_meeting(date: str, start_24h: str, duration_minutes: int, title: str) -> str:
        del title
        _validate(date, start_24h, duration_minutes)
        overlapping = _conflicts(date, start_24h, duration_minutes)
        if overlapping:
            raise ValueError(f"slot {start_24h} conflicts with {overlapping}")
        return json.dumps(
            {"event_id": f"EVT-{date}-{start_24h.replace(':', '')}", "status": "booked"}
        )

    return {
        "get_today": get_today,
        "check_availability": check_availability,
        "book_meeting": book_meeting,
    }


def _load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    env_file = Path.home() / "chaincheck" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("OPENAI_API_KEY not set")


def agent(session, task: str) -> None:
    from openai import OpenAI

    client = session.wrap_openai(OpenAI(api_key=_load_key()))
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task},
    ]
    for _ in range(10):
        response = client.chat.completions.create(
            model=MODEL, max_tokens=400, messages=messages, tools=TOOL_SPECS
        )
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        assistant: dict = {"role": "assistant", "content": msg.content}
        if tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant)
        if not tool_calls:
            session.end(status="completed", final_text=msg.content)
            return
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                content = f"JSONDecodeError: tool arguments were not valid JSON ({exc})"
            else:
                content, _ = session.execute(tc.function.name, args, tc.id)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    session.end(status="max_turns_exceeded", final_text=None)


def booked_slot(run_dir: Path) -> str | None:
    """The slot of the last successful book_meeting call, if any."""
    slot = None
    for event in read_events(run_dir):
        if (
            event["type"] == "tool_call"
            and event["name"] == "book_meeting"
            and not event["is_error"]
        ):
            slot = f"{event['input'].get('date')} {event['input'].get('start_24h')}"
    return slot


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    report = run_repeated(
        agent,
        TASK,
        n,
        client_factory=lambda i: None,  # the agent wraps its own OpenAI client
        tools_factory=make_tools,
        runs_root=RUNS_DIR,
        prefix="sched",
        concurrency=3,
        budget_usd=0.50,
        db_path=DB,
        agent_name="scheduler-agent",
    )

    correct = f"{TARGET_DATE} {CORRECT_SLOT}"
    completed = [r for r in report["runs"] if not r.get("skipped")]
    slots: dict[str, str] = {}
    for result in completed:
        slot = booked_slot(RUNS_DIR / result["run_id"]) or "—"
        slots[result["run_id"]] = slot
        if slot != correct:
            # ground truth, encoded once: the deterministic check no judge
            # can miss. The shared signature groups the recurrence.
            events = read_events(RUNS_DIR / result["run_id"])
            end_seq = next(
                e["seq"] for e in reversed(events) if e["type"] == "run_end"
            )
            store.add_finding(
                DB,
                result["run_id"],
                seq=end_seq,
                label="wrong_slot",
                severity="fail",
                confidence=1.0,
                detail=f"booked {slot}; the only conflict-free 45-minute slot "
                f"for the task is {correct}",
                signature="assert:booked_slot",
            )

    print(f"\n{'run':12} {'verdict':8} {'booked':18} {'right?':6} labels")
    rows = {r["run_id"]: r for r in store.list_runs(DB)}
    for result in completed:
        row = rows.get(result["run_id"], {})
        slot = slots[result["run_id"]]
        mark = "yes" if slot == correct else "NO"
        print(
            f"{result['run_id']:12} {row.get('verdict') or '?':8} {slot:18} "
            f"{mark:6} {row.get('labels') or ''}"
        )
    print(f"\ntotal cost ${report['total_cost_usd']:.4f} across {report['completed']} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
