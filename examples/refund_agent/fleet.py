#!/usr/bin/env python3
"""Record the refund-agent demo fleet.

    python fleet.py [N]     record N seeded runs + the governor-killed runaway

The support-automation story: same customer complaint every time, three
behaviors — clean refunds, a malformed-amount retry bug, and a gateway that
never settles. Plus one runaway with no turn limit that only the governor's
budget stops.
"""

from __future__ import annotations

import sys
from pathlib import Path

from refund_model import TASK, RefundAnthropic
from tools import TOOL_SPECS, make_tools

import reflight
from reflight import Governor, GovernorKill, store

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"

SYSTEM = (
    "You are a support agent for a home-goods store. Verify claims against "
    "order records and policy before refunding. Never guess amounts."
)
MAX_TURNS = 12


def run_agent(session, task: str) -> tuple[str | None, str]:
    messages: list[dict] = [{"role": "user", "content": task}]
    for _ in range(MAX_TURNS):
        response = session.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOL_SPECS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            final = "".join(b.text for b in response.content if b.type == "text")
            session.end(status="completed", final_text=final)
            return final, "completed"
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result, is_error = session.execute(block.name, dict(block.input), block.id)
                entry = {"type": "tool_result", "tool_use_id": block.id, "content": result}
                if is_error:
                    entry["is_error"] = True
                results.append(entry)
        messages.append({"role": "user", "content": results})
    session.end(status="max_turns_exceeded", final_text=None)
    return None, "max_turns_exceeded"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    for seed in range(n):
        run_dir = RUNS_DIR / f"refund-{seed:02d}"
        session = reflight.record(
            run_dir,
            task=TASK,
            client=RefundAnthropic(seed),
            tools=make_tools(pending=seed % 3 == 2),
            db_path=DB,
            agent_name="refund-agent",
        )
        run_agent(session, TASK)

    # the runaway: gateway stuck on PENDING, no turn limit, $2 budget
    run_dir = RUNS_DIR / "refund-runaway"
    session = reflight.record(
        run_dir,
        task=TASK,
        client=RefundAnthropic(2, endless=True),
        tools=make_tools(pending=True),
        db_path=DB,
        governor=Governor(max_cost_usd=2.00, cache_tool_calls=True),
        agent_name="refund-agent",
    )
    try:
        messages: list[dict] = [{"role": "user", "content": TASK}]
        while True:  # no turn limit — only the governor stands in the way
            response = session.messages.create(
                model="claude-sonnet-5",
                max_tokens=1024,
                system=SYSTEM,
                tools=TOOL_SPECS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": list(response.content)})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    result, _ = session.execute(block.name, dict(block.input), block.id)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            messages.append({"role": "user", "content": results})
    except GovernorKill as kill:
        print(f"refund-runaway killed: {kill}")

    print(f"\n{'run':16} {'verdict':8} labels")
    for run in store.list_runs(DB):
        if run["run_id"].startswith("refund-"):
            print(f"{run['run_id']:16} {run['verdict']:8} {run['labels']}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
