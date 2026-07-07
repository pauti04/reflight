#!/usr/bin/env python3
"""Record a fleet of flaky-agent runs and let the classifier label the wrecks.

    python fleet.py [N]      record N runs (default 10), ingest, print verdicts

Same agent code and task every time — only the seed changes. Expect roughly
1/3 clean passes, 1/3 loops, 1/3 wrong-tool-args cascades.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

from flaky_model import FlakyAnthropic
from main import run_agent  # the research agent's loop, reused verbatim
from tools import make_tools

from reflight import Recorder, store

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for seed in range(n):
        run_dir = RUNS_DIR / f"flaky-{seed:02d}"
        session = Recorder(
            run_dir, FlakyAnthropic(seed), make_tools(run_dir / "notes"), db_path=DB
        )
        run_agent(session, TASK)

    print(f"{'run':12} {'verdict':8} labels")
    for run in store.list_runs(DB):
        if not run["run_id"].startswith("flaky-"):
            continue
        print(f"{run['run_id']:12} {run['verdict']:8} {run['labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
