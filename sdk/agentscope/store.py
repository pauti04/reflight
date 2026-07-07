"""SQLite index over recorded runs.

events.jsonl in each run directory stays the source of truth (replay reads it
directly); the database is the query layer for the CLI and, later, the UI.
Cost is computed at ingest from each llm_call's usage block.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import schema
from .events import read_events
from .pricing import cost_usd

_TABLES = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    task          TEXT,
    status        TEXT,
    started_at    REAL,
    ended_at      REAL,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    final_text    TEXT,
    event_count   INTEGER,
    tool_errors   INTEGER,
    run_dir       TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id   TEXT,
    seq      INTEGER,
    ts       REAL,
    type     TEXT,
    payload  TEXT,
    cost_usd REAL,
    PRIMARY KEY (run_id, seq)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(_TABLES)
    return con


def ingest_run(db_path: Path | str, run_dir: Path | str) -> dict:
    """Load one run directory into the database (idempotent upsert)."""
    run_dir = Path(run_dir)
    events = read_events(run_dir)
    problems = schema.validate_run(events)
    run_id = run_dir.name

    start = next((e for e in events if e["type"] == "run_start"), {})
    end = next((e for e in events if e["type"] == "run_end"), {})
    model = next(
        (e["response"].get("model") for e in events if e["type"] == "llm_call"), None
    )

    total_cost = 0.0
    priced = False
    rows = []
    for event in events:
        cost = None
        if event["type"] == "llm_call":
            usage = event["response"].get("usage") or {}
            cost = cost_usd(event["response"].get("model"), usage)
            if cost is not None:
                total_cost += cost
                priced = True
        rows.append(
            (run_id, event["seq"], event.get("ts"), event["type"], json.dumps(event), cost)
        )

    tool_errors = sum(1 for e in events if e["type"] == "tool_call" and e.get("is_error"))

    con = connect(db_path)
    with con:
        con.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", rows)
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                start.get("task"),
                end.get("status"),
                start.get("ts"),
                end.get("ts"),
                model,
                end.get("input_tokens"),
                end.get("output_tokens"),
                total_cost if priced else None,
                end.get("final_text"),
                len(events),
                tool_errors,
                str(run_dir),
            ),
        )
    con.close()
    return {"run_id": run_id, "cost_usd": total_cost if priced else None, "problems": problems}


def list_runs(db_path: Path | str) -> list[dict]:
    con = connect(db_path)
    rows = [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY started_at")]
    con.close()
    return rows


def get_events(db_path: Path | str, run_id: str) -> list[tuple[dict, float | None]]:
    con = connect(db_path)
    rows = [
        (json.loads(r["payload"]), r["cost_usd"])
        for r in con.execute(
            "SELECT payload, cost_usd FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
        )
    ]
    con.close()
    return rows
