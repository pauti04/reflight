#!/usr/bin/env python3
"""The 3-line instrumentation demo.

`run_agent()` below is written like any pre-existing agent: it owns its client
and calls its tools as plain Python functions. Making it recordable/replayable
takes the three lines marked # (1) (2) (3) — nothing else changes.

    python agent.py record    → runs live (scripted model), records everything
    python agent.py replay    → re-runs from the recording: no network, $0.00
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

import reflight
from fake_model import FakeAnthropic
from tools import TOOL_SPECS, make_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "runs" / "quickstart-demo"
DB = REPO_ROOT / "runs" / "reflight.db"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def run_agent(client, tools) -> str:
    """A plain agent loop — knows nothing about reflight."""
    messages: list[dict] = [{"role": "user", "content": TASK}]
    for _ in range(8):
        response = client.messages.create(
            model="claude-sonnet-5", max_tokens=1024, tools=TOOL_SPECS, messages=messages
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    output = tools[block.name](**block.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": output}
                    )
                except Exception as exc:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"{type(exc).__name__}: {exc}",
                            "is_error": True,
                        }
                    )
        messages.append({"role": "user", "content": results})
    return "(gave up after 8 turns)"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "record"

    if mode == "record":
        session = reflight.record(RUN_DIR, task=TASK, db_path=DB)      # (1)
        client = session.wrap(FakeAnthropic())                           # (2)
    else:
        session = reflight.replay(RUN_DIR)
        client = session.wrap()

    raw_tools = make_tools(RUN_DIR / "notes")
    tools = {name: session.tool(fn) for name, fn in raw_tools.items()}   # (3)

    answer = run_agent(client, tools)
    session.end(status="completed", final_text=answer)

    print(f"[{mode}] {answer}")
    if mode == "replay":
        match = answer == session.recorded_final_text
        print(f"[replay] identical to recording: {match} · 0 API calls · $0.00")
        return 0 if match else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
