#!/usr/bin/env python3
"""Milestone demo #2: failure labeled → forked → fixed.

flaky-02 failed with wrong_tool_args (sent {"q": ...} to web_search). We "fix
the model" (seed 0 behaves correctly), fork the failed run at the moment of
the bad call, and let the fixed agent take over. The fork is a complete new
recording — diffed against the original to show exactly what changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

from flaky_model import FlakyAnthropic
from main import run_agent
from tools import make_tools

import agentscope
from agentscope import store
from agentscope.diff import diff_runs

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "agentscope.db"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"

SOURCE = RUNS_DIR / "flaky-02"
FORK_AT = 1  # the seq of the llm_call that chose the wrong arguments


def main() -> int:
    if not (SOURCE / "events.jsonl").exists():
        session = agentscope.record(SOURCE, task=TASK, db_path=DB)
        session.wrap(FlakyAnthropic(2))
        run_agent(session, TASK)

    fork_dir = RUNS_DIR / "flaky-02-fixed"
    session = agentscope.fork(
        SOURCE,
        FORK_AT,
        client=FlakyAnthropic(0),  # the "fixed" model
        tools=make_tools(fork_dir / "notes"),
        out_dir=fork_dir,
        db_path=DB,
    )
    final_text, status = run_agent(session, session.task)

    print(f"fork:   replayed to seq {FORK_AT}, went live, finished [{status}]")
    print(f"answer: {final_text}\n")

    original = [e for e, _ in store.get_events(DB, "flaky-02")]
    fixed = [e for e, _ in store.get_events(DB, "flaky-02-fixed")]
    d = diff_runs(original, fixed)
    print(f"diff vs original: first divergence at seq {d['divergence_seq']}")

    for run in store.list_runs(DB):
        if run["run_id"] in ("flaky-02", "flaky-02-fixed"):
            print(f"  {run['run_id']:16} verdict={run['verdict']}  labels={run['labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
