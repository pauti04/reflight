"""SQLite index over recorded runs.

events.jsonl in each run directory stays the source of truth (replay reads it
directly); the database is the query layer for the CLI and UI. Cost and
failure classification are computed at ingest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import classify as classify_mod
from . import schema
from .events import read_events
from .pricing import cost_usd

_TABLES = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    task          TEXT,
    status        TEXT,
    verdict       TEXT,
    labels        TEXT,
    started_at    REAL,
    ended_at      REAL,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    final_text    TEXT,
    event_count   INTEGER,
    tool_errors   INTEGER,
    run_dir       TEXT,
    agent         TEXT
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
CREATE TABLE IF NOT EXISTS findings (
    run_id     TEXT,
    seq        INTEGER,
    label      TEXT,
    severity   TEXT,
    confidence REAL,
    detail     TEXT
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(_TABLES)
    # dev-stage migration: add columns introduced after a db was created
    existing = {row["name"] for row in con.execute("PRAGMA table_info(runs)")}
    for column in ("verdict", "labels", "agent"):
        if column not in existing:
            con.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")
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
    event_rows = []
    for event in events:
        cost = None
        if event["type"] == "llm_call":
            usage = event["response"].get("usage") or {}
            cost = cost_usd(event["response"].get("model"), usage)
            if cost is not None:
                total_cost += cost
                priced = True
        event_rows.append(
            (run_id, event["seq"], event.get("ts"), event["type"], json.dumps(event), cost)
        )

    findings = classify_mod.classify(events)
    verdict = classify_mod.verdict(findings)
    labels = sorted({f.label for f in findings})
    tool_errors = sum(1 for e in events if e["type"] == "tool_call" and e.get("is_error"))

    con = connect(db_path)
    with con:
        con.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        con.execute("DELETE FROM findings WHERE run_id = ?", (run_id,))
        con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", event_rows)
        con.executemany(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?)",
            [(run_id, f.seq, f.label, f.severity, f.confidence, f.detail) for f in findings],
        )
        con.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, task, status, verdict, labels, started_at, ended_at, model,
                input_tokens, output_tokens, cost_usd, final_text, event_count,
                tool_errors, run_dir, agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                start.get("task"),
                end.get("status"),
                verdict,
                json.dumps(labels),
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
                start.get("agent"),
            ),
        )
    con.close()
    return {
        "run_id": run_id,
        "cost_usd": total_cost if priced else None,
        "verdict": verdict,
        "labels": labels,
        "problems": problems,
    }


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


def add_finding(
    db_path: Path | str,
    run_id: str,
    seq: int,
    label: str,
    severity: str,
    confidence: float,
    detail: str,
) -> None:
    """Append a finding (e.g. from the LLM judge) and fold it into the verdict."""
    con = connect(db_path)
    with con:
        con.execute(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, seq, label, severity, confidence, detail),
        )
        row = con.execute("SELECT verdict, labels FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row:
            verdict = "fail" if severity == "fail" else (row["verdict"] or "warn")
            if verdict == "pass":
                verdict = "warn"
            labels = sorted(set(json.loads(row["labels"] or "[]")) | {label})
            con.execute(
                "UPDATE runs SET verdict = ?, labels = ? WHERE run_id = ?",
                (verdict, json.dumps(labels), run_id),
            )
    con.close()


def costs_summary(db_path: Path | str, anomaly_factor: float = 2.0) -> dict:
    """Cost aggregates per task, per agent, and per day, with anomaly flags
    (runs costing more than anomaly_factor × their task's median)."""
    import statistics
    from datetime import datetime, timezone

    runs = [r for r in list_runs(db_path) if r["cost_usd"] is not None]

    def _group(key_fn):
        groups: dict[str, list[dict]] = {}
        for run in runs:
            groups.setdefault(key_fn(run) or "—", []).append(run)
        return [
            {
                "key": key,
                "runs": len(group),
                "total_usd": sum(r["cost_usd"] for r in group),
                "mean_usd": sum(r["cost_usd"] for r in group) / len(group),
            }
            for key, group in sorted(groups.items())
        ]

    def _day(run):
        ts = run["started_at"]
        return (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
        )

    anomalies = []
    by_task: dict[str, list[dict]] = {}
    for run in runs:
        by_task.setdefault(run["task"] or "—", []).append(run)
    for task, group in by_task.items():
        median = statistics.median(r["cost_usd"] for r in group)
        for run in group:
            if median > 0 and run["cost_usd"] > anomaly_factor * median:
                anomalies.append(
                    {
                        "run_id": run["run_id"],
                        "task": task,
                        "cost_usd": run["cost_usd"],
                        "median_usd": median,
                        "factor": run["cost_usd"] / median,
                    }
                )

    return {
        "total_usd": sum(r["cost_usd"] for r in runs),
        "runs": len(runs),
        "per_task": _group(lambda r: r["task"]),
        "per_agent": _group(lambda r: r.get("agent")),
        "per_day": _group(_day),
        "anomalies": sorted(anomalies, key=lambda a: -a["factor"]),
    }


def get_findings(db_path: Path | str, run_id: str) -> list[dict]:
    con = connect(db_path)
    rows = [
        dict(r)
        for r in con.execute(
            "SELECT seq, label, severity, confidence, detail FROM findings "
            "WHERE run_id = ? ORDER BY seq",
            (run_id,),
        )
    ]
    con.close()
    return rows
