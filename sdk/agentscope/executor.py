"""N-run live executor: run the same task repeatedly, concurrently, under a
hard cost cap. The raw material for consistency scoring — one run tells you
whether the agent CAN do the task; N runs tell you whether it reliably DOES.

The budget is enforced at launch: once cumulative recorded cost reaches the
cap, remaining runs are skipped (in-flight runs finish). Crashes become
recorded error events, not lost runs.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import store
from .events import read_events
from .pricing import cost_usd
from .recorder import Recorder

Agent = Callable[[Any, str], Any]


def _run_cost(events: list[dict]) -> float:
    total = 0.0
    for event in events:
        if event["type"] == "llm_call":
            c = cost_usd(event["response"].get("model"), event["response"].get("usage") or {})
            total += c or 0.0
    return total


def run_repeated(
    agent: Agent,
    task: str,
    n: int,
    client_factory: Callable[[int], Any],
    tools_factory: Callable[[Path], dict],
    runs_root: Path | str,
    prefix: str = "rep",
    concurrency: int = 4,
    budget_usd: float | None = None,
    db_path: Path | str | None = None,
) -> dict:
    runs_root = Path(runs_root)
    lock = threading.Lock()
    spent = 0.0

    def one(i: int) -> dict:
        nonlocal spent
        with lock:
            if budget_usd is not None and spent >= budget_usd:
                return {"run_id": f"{prefix}-{i:03d}", "skipped": True}
        run_dir = runs_root / f"{prefix}-{i:03d}"
        session = Recorder(run_dir, client_factory(i), tools_factory(run_dir))
        try:
            agent(session, task)
        except Exception as exc:  # a crashed run is still a recorded run
            session.record_error(exc)
            session.end(status="error", final_text=None)
        cost = _run_cost(read_events(run_dir))
        with lock:
            spent += cost
        return {"run_id": run_dir.name, "run_dir": run_dir, "cost_usd": cost, "skipped": False}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, range(n)))

    completed = [r for r in results if not r["skipped"]]
    if db_path is not None:
        for r in completed:  # sequential ingest — sqlite and threads don't mix
            r.update(store.ingest_run(db_path, r["run_dir"]))

    return {
        "runs": results,
        "completed": len(completed),
        "skipped": len(results) - len(completed),
        "total_cost_usd": spent,
    }
