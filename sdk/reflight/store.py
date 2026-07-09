"""Queryable index over recorded runs: SQLite by default, Postgres by URL.

events.jsonl in each run directory stays the source of truth (replay reads it
directly); the database is the query layer for the CLI and UI. Cost and
failure classification are computed at ingest.

Pass a path for SQLite (zero setup), or a postgresql:// URL for teams:

    reflight --db postgresql://user:pass@host/reflight runs

Postgres needs the extra: pip install 'reflight[postgres]'.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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
    detail     TEXT,
    signature  TEXT
);
"""


def _is_postgres(db_path: Path | str) -> bool:
    return str(db_path).startswith(("postgres://", "postgresql://"))


class _PgAdapter:
    """psycopg connection with the store's sqlite3 semantics: `with con:` is a
    transaction (psycopg's own context manager would close the connection),
    ?-placeholders, dict-like rows."""

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(sql.replace("?", "%s"), rows)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._conn.execute(statement)
        self._conn.commit()

    def __enter__(self) -> "_PgAdapter":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False

    def close(self) -> None:
        self._conn.close()


def _connect_postgres(url: str) -> _PgAdapter:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "Postgres support needs psycopg — install with: pip install 'reflight[postgres]'"
        ) from exc
    adapter = _PgAdapter(psycopg.connect(url, row_factory=dict_row))
    adapter.executescript(_TABLES)
    adapter.executescript("ALTER TABLE findings ADD COLUMN IF NOT EXISTS signature TEXT")
    return adapter


def connect(db_path: Path | str):
    if _is_postgres(db_path):
        return _connect_postgres(str(db_path))
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
    finding_cols = {row["name"] for row in con.execute("PRAGMA table_info(findings)")}
    if "signature" not in finding_cols:
        con.execute("ALTER TABLE findings ADD COLUMN signature TEXT")
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
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, f.seq, f.label, f.severity, f.confidence, f.detail, f.signature)
                for f in findings
            ],
        )
        con.execute(
            "DELETE FROM runs WHERE run_id = ?", (run_id,)
        )
        con.execute(
            """INSERT INTO runs
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
    signature: str = "",
) -> None:
    """Append a finding (e.g. from the LLM judge) and fold it into the verdict."""
    con = connect(db_path)
    with con:
        con.execute(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, seq, label, severity, confidence, detail, signature or label),
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


def reliability_summary(db_path: Path | str) -> list[dict]:
    """Per-task consistency scoreboard: pass rate, verdict mix, failure-mode
    histogram, answer stability, cost — the reliability.py report shape, but
    over everything already in the db, grouped by task."""
    runs = list_runs(db_path)
    trends = reliability_trend(db_path)

    con = connect(db_path)
    label_rows = list(
        con.execute(
            "SELECT r.task AS task, r.agent AS agent, f.label AS label FROM findings f "
            "JOIN runs r ON r.run_id = f.run_id"
        )
    )
    con.close()
    histograms: dict[str, dict[str, int]] = {}
    for row in label_rows:
        key = row["agent"] or row["task"] or "—"
        task_hist = histograms.setdefault(key, {})
        task_hist[row["label"]] = task_hist.get(row["label"], 0) + 1

    # group by agent when set (a fleet runs many task variants of one agent),
    # else by task — keeps single-agent and legacy data grouping unchanged
    groups: dict[str, list[dict]] = {}
    for run in runs:
        groups.setdefault(run.get("agent") or run["task"] or "—", []).append(run)

    summary = []
    for task, group in groups.items():
        verdicts: dict[str, int] = {}
        answers = set()
        costs = [r["cost_usd"] for r in group if r["cost_usd"] is not None]
        for run in group:
            verdicts[run["verdict"] or "?"] = verdicts.get(run["verdict"] or "?", 0) + 1
            if run["final_text"]:
                answers.add(run["final_text"])
        passes = verdicts.get("pass", 0)
        summary.append(
            {
                "task": task,
                "runs": len(group),
                "passes": passes,
                "pass_rate": passes / len(group) if group else 0.0,
                "verdicts": verdicts,
                "failure_histogram": dict(
                    sorted(histograms.get(task, {}).items(), key=lambda kv: -kv[1])
                ),
                "distinct_answers": len(answers),
                "cost_mean": sum(costs) / len(costs) if costs else None,
                "total_cost": sum(costs) if costs else 0.0,
                "trend": trends.get(task, []),
            }
        )
    return sorted(summary, key=lambda s: -s["runs"])


def recurrences(db_path: Path | str, run_id: str) -> dict[str, list[dict]]:
    """For each fail-severity fingerprint in this run: the OTHER runs where the
    same bug appears. {signature: [{run_id, started_at, verdict}, ...]}"""
    con = connect(db_path)
    rows = list(
        con.execute(
            """SELECT DISTINCT f1.signature AS signature, f2.run_id AS run_id,
                      r.started_at AS started_at, r.verdict AS verdict
               FROM findings f1
               JOIN findings f2 ON f2.signature = f1.signature
               JOIN runs r ON r.run_id = f2.run_id
               WHERE f1.run_id = ? AND f2.run_id != ?
                 AND f1.severity = 'fail' AND f1.signature != ''""",
            (run_id, run_id),
        )
    )
    con.close()
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(row["signature"], []).append(
            {"run_id": row["run_id"], "started_at": row["started_at"], "verdict": row["verdict"]}
        )
    for matches in result.values():
        matches.sort(key=lambda m: m["started_at"] or 0)
    return result


def recurring_failures(db_path: Path | str, min_count: int = 2) -> list[dict]:
    """Bugs that keep coming back: fail-severity fingerprints seen in >= min_count
    runs, most recurrent first."""
    con = connect(db_path)
    rows = list(
        con.execute(
            """SELECT f.signature AS signature, f.label AS label, f.detail AS detail,
                      f.run_id AS run_id, r.started_at AS started_at
               FROM findings f JOIN runs r ON r.run_id = f.run_id
               WHERE f.severity = 'fail' AND f.signature != ''"""
        )
    )
    con.close()
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(
            row["signature"],
            {"signature": row["signature"], "label": row["label"], "detail": row["detail"],
             "runs": {}},
        )
        group["runs"][row["run_id"]] = row["started_at"] or 0
    result = []
    for group in groups.values():
        if len(group["runs"]) < min_count:
            continue
        ordered = sorted(group["runs"].items(), key=lambda kv: kv[1])
        result.append(
            {
                "signature": group["signature"],
                "label": group["label"],
                "detail": group["detail"],
                "count": len(ordered),
                "run_ids": [run_id for run_id, _ in ordered],
                "first_seen": ordered[0][1],
                "last_seen": ordered[-1][1],
            }
        )
    return sorted(result, key=lambda g: (-g["count"], -(g["last_seen"] or 0)))


def reliability_trend(db_path: Path | str, bucket: str = "day") -> dict[str, list[dict]]:
    """Per-task pass rate over time. {task: [{bucket, n, passes, pass_rate}, ...]}"""
    from datetime import datetime, timezone

    fmt = "%Y-%m-%d %H:00" if bucket == "hour" else "%Y-%m-%d"
    counts: dict[str, dict[str, list[int]]] = {}
    for run in list_runs(db_path):
        ts = run["started_at"]
        if ts is None:
            continue
        key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(fmt)
        group = run.get("agent") or run["task"] or "—"
        slot = counts.setdefault(group, {}).setdefault(key, [0, 0])
        slot[0] += 1
        if run["verdict"] == "pass":
            slot[1] += 1
    return {
        task: [
            {"bucket": key, "n": n, "passes": passes, "pass_rate": passes / n}
            for key, (n, passes) in sorted(buckets.items())
        ]
        for task, buckets in counts.items()
    }


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
            "SELECT seq, label, severity, confidence, detail, signature FROM findings "
            "WHERE run_id = ? ORDER BY seq",
            (run_id,),
        )
    ]
    con.close()
    return rows
