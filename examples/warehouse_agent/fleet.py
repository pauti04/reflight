#!/usr/bin/env python3
"""Warehouse-ops agent fleet: diagnose a failed nightly rollup and backfill.

Behaviors:

    recovers    first SQL references the misspelled table `ordres`, errors once,
                the agent corrects itself, backfills, and finishes — a run that
                PASSES with a warning-level tool_error finding
    stuck       the agent never notices the typo and retries the same broken
                SQL until it gives up
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from anthropic.types import Message

import reflight
from reflight import store

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"

DATES = ["2026-07-05", "2026-07-06", "2026-07-07", "2026-07-08"]
MODES = ["recovers", "stuck", "recovers", "stuck"]

SYSTEM = (
    "You are the on-call data-platform agent. Diagnose failed warehouse jobs, "
    "verify queries before rerunning, and backfill once the cause is fixed."
)

TOOL_SPECS = [
    {
        "name": "get_job_status",
        "description": "Status and last error of a scheduled warehouse job.",
        "input_schema": {
            "type": "object",
            "properties": {"job": {"type": "string"}},
            "required": ["job"],
        },
    },
    {
        "name": "run_sql",
        "description": "Run a read-only SQL query against the warehouse.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "backfill",
        "description": "Re-run a job for one date after the cause is fixed.",
        "input_schema": {
            "type": "object",
            "properties": {"job": {"type": "string"}, "date": {"type": "string"}},
            "required": ["job", "date"],
        },
    },
]


def make_tools() -> dict:
    def get_job_status(job: str) -> str:
        return json.dumps(
            {
                "job": job,
                "status": "failed",
                "last_error": 'psycopg.errors.UndefinedTable: relation "ordres" does not exist',
            }
        )

    def run_sql(query: str) -> str:
        if "ordres" in query:
            raise RuntimeError('UndefinedTable: relation "ordres" does not exist')
        return json.dumps({"rows": 1, "sample": {"revenue_usd": 184203.55}})

    def backfill(job: str, date: str) -> str:
        return json.dumps({"job": job, "date": date, "status": "succeeded", "rows": 48211})

    return {"get_job_status": get_job_status, "run_sql": run_sql, "backfill": backfill}


def _bad_sql(date: str) -> str:
    return f"SELECT SUM(total_usd) AS revenue_usd FROM ordres WHERE shipped_on = '{date}'"


def _good_sql(date: str) -> str:
    return f"SELECT SUM(total_usd) AS revenue_usd FROM orders WHERE shipped_on = '{date}'"


def _script(seed: int) -> list[dict]:
    mode = MODES[seed % len(MODES)]
    date = DATES[seed % len(DATES)]
    status = {
        "kind": "tool",
        "name": "get_job_status",
        "input": {"job": "nightly_revenue_rollup"},
        "lead": f"Rollup for {date} is down. Checking the job first.",
    }
    bad = {"kind": "tool", "name": "run_sql", "input": {"query": _bad_sql(date)}}
    if mode == "stuck":
        return [
            status,
            {
                **bad,
                "lead": "The job's own query failed — reproducing it to see the error.",
            },
            bad,
            bad,
            {
                "kind": "final",
                "text": f"The rollup query for {date} keeps failing with an "
                "UndefinedTable error and I could not resolve it. Escalating "
                "to the data platform team.",
            },
        ]
    return [
        status,
        {
            **bad,
            "lead": "The job's own query failed — reproducing it to see the error.",
        },
        {
            "kind": "tool",
            "name": "run_sql",
            "input": {"query": _good_sql(date)},
            "lead": 'The table is "orders", not "ordres" — a typo in the job SQL. Verifying the fix.',
        },
        {
            "kind": "tool",
            "name": "backfill",
            "input": {"job": "nightly_revenue_rollup", "date": date},
            "lead": "Corrected query returns data. Backfilling the job.",
        },
        {
            "kind": "final",
            "text": f"Root cause: the rollup SQL referenced 'ordres' (typo) instead "
            f"of 'orders'. Verified the corrected query and backfilled {date} "
            "successfully (48,211 rows).",
        },
    ]


class WarehouseAnthropic:
    def __init__(self, seed: int):
        self._seed = seed
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        n = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        script = _script(self._seed)
        step = script[min(n, len(script) - 1)]
        if step["kind"] == "tool":
            content: list[dict] = []
            if step.get("lead"):
                content.append({"type": "text", "text": step["lead"]})
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_wh_{self._seed}_{n:04d}",
                    "name": step["name"],
                    "input": step["input"],
                }
            )
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": step["text"]}]
            stop = "end_turn"
        return Message.model_validate(
            {
                "id": f"msg_wh_{self._seed}_{n:04d}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 280 + 35 * n, "output_tokens": 60},
            }
        )


def run_agent(session, task: str) -> None:
    messages: list[dict] = [{"role": "user", "content": task}]
    for _ in range(12):
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
            return
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


def main() -> int:
    for seed in range(len(MODES)):
        date = DATES[seed % len(DATES)]
        task = (
            f"The nightly revenue rollup for {date} failed overnight. Diagnose "
            "the failure and backfill the job."
        )
        session = reflight.record(
            RUNS_DIR / f"rollup-{date}",
            task=task,
            client=WarehouseAnthropic(seed),
            tools=make_tools(),
            db_path=DB,
            agent_name="warehouse-agent",
        )
        run_agent(session, task)

    for run in store.list_runs(DB):
        if run["run_id"].startswith("rollup-"):
            print(f"{run['run_id']:20} {run['verdict']:6} {run['labels']}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
