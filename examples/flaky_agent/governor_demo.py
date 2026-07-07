#!/usr/bin/env python3
"""Milestone demo #4: the runaway agent and the $0.50 save.

RunawayAnthropic never stops — it issues the same tool call forever. Two
governor configurations stop it:

    run A: loop circuit breaker (3 identical calls allowed, 4th is killed)
    run B: breaker off, hard $0.50 budget — the kill lands on the timeline

Both kills are recorded IN the run: error event with the reason, status
"killed", classified as governor_kill. The dashboard shows the save.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

from anthropic.types import Message
from tools import TOOL_SPECS, make_tools

import reflight
from reflight import Governor, GovernorKill, store

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"


class RunawayAnthropic:
    """A model stuck in a groove: the identical tool call, forever."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        n = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        return Message.model_validate(
            {
                "id": f"msg_runaway_{n:05d}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"toolu_runaway_{n:05d}",
                        "name": "calculator",
                        "input": {"expression": "37400068 / 2"},
                    }
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 900 + 210 * n, "output_tokens": 45},
            }
        )


def runaway_agent(session, task: str) -> None:
    """No turn limit — only the governor stands between this and bankruptcy."""
    messages: list[dict] = [{"role": "user", "content": task}]
    while True:
        response = session.messages.create(
            model="claude-sonnet-5", max_tokens=1024, tools=TOOL_SPECS, messages=messages
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result, is_error = session.execute(block.name, dict(block.input), block.id)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
        messages.append({"role": "user", "content": results})


def _run(run_id: str, governor: Governor) -> None:
    run_dir = RUNS_DIR / run_id
    session = reflight.record(
        run_dir,
        task=TASK,
        client=RunawayAnthropic(),
        tools=make_tools(run_dir / "notes"),
        db_path=DB,
        governor=governor,
        agent_name="runaway-demo",
    )
    try:
        runaway_agent(session, TASK)
    except GovernorKill as kill:
        print(f"   ⛔ killed: {kill}")
    print(
        f"   spent ${session.total_cost_usd:.4f} over {governor.llm_calls} llm calls"
        f"  (cache: {governor.stats()['cache_hits']} hits)"
    )


def main() -> int:
    print("── run A: loop circuit breaker (ChainCheck v2) ──────────")
    _run("runaway-breaker", Governor(loop_breaker=3, cache_tool_calls=True))

    print("\n── run B: no breaker, hard $0.50 budget ─────────────────")
    _run("runaway-budget", Governor(max_cost_usd=0.50, cache_tool_calls=True))

    print("\n── the dashboard shows the save ──────────────────────────")
    for run in store.list_runs(DB):
        if run["run_id"].startswith("runaway-"):
            print(
                f"   {run['run_id']:18} [{run['status']}] {run['labels']}  "
                f"cost ${run['cost_usd']:.4f}  ({run['event_count']} events)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
