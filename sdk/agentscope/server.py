"""FastAPI query server for the timeline UI: `agentscope serve`.

Read-only REST over the SQLite store. The Next.js dev UI (ui/) talks to this
on localhost; in a later phase the built UI gets served from here too.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import store

DEFAULT_PORT = 8724  # "ASCP" on a phone keypad, near enough


def create_app(db_path: str | Path = "runs/agentscope.db") -> FastAPI:
    app = FastAPI(title="AgentScope", version="0.1")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return store.list_runs(db_path)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = next((r for r in store.list_runs(db_path) if r["run_id"] == run_id), None)
        if run is None:
            raise HTTPException(404, f"no run {run_id!r}")
        run["findings"] = store.get_findings(db_path, run_id)
        return run

    @app.get("/api/costs")
    def get_costs() -> dict:
        return store.costs_summary(db_path)

    @app.get("/api/diff")
    def get_diff(a: str, b: str) -> dict:
        from .diff import diff_runs

        events_a = [e for e, _ in store.get_events(db_path, a)]
        events_b = [e for e, _ in store.get_events(db_path, b)]
        if not events_a or not events_b:
            raise HTTPException(404, "both runs must exist")
        return {**diff_runs(events_a, events_b), "a": events_a, "b": events_b}

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str) -> list[dict]:
        events = store.get_events(db_path, run_id)
        if not events:
            raise HTTPException(404, f"no run {run_id!r}")
        return [{"event": event, "cost_usd": cost} for event, cost in events]

    return app


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    import uvicorn

    uvicorn.run(create_app(db_path), host=host, port=port)
