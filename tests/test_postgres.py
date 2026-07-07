"""Postgres mode: the same store API against a real PostgreSQL.

Runs when a Postgres is reachable (dockerized locally, service container in
CI); skips otherwise. URL override: REFLIGHT_PG_URL.
"""

import os

import pytest

pytest.importorskip("psycopg")

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight import store

PG_URL = os.environ.get(
    "REFLIGHT_PG_URL", "postgresql://postgres:reflight@127.0.0.1:55432/reflight"
)
TASK = "What is the population of Tokyo, and what is that number divided by 2?"


@pytest.fixture
def pg_db():
    import psycopg

    try:
        con = psycopg.connect(PG_URL, connect_timeout=3)
    except Exception:
        pytest.skip(f"no Postgres reachable at {PG_URL}")
    with con:
        con.execute("DROP TABLE IF EXISTS runs, events, findings CASCADE")
    con.close()
    return PG_URL


def _record(tmp_path, seed, run_id, db):
    run_dir = tmp_path / run_id
    session = reflight.record(run_dir, task=TASK, db_path=db, agent_name="pg-test")
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    return run_dir


def test_ingest_and_query_roundtrip(tmp_path, pg_db):
    _record(tmp_path, 0, "pg-good", pg_db)
    _record(tmp_path, 1, "pg-loop", pg_db)

    runs = {r["run_id"]: r for r in store.list_runs(pg_db)}
    assert set(runs) == {"pg-good", "pg-loop"}
    assert runs["pg-good"]["verdict"] == "pass"
    assert runs["pg-loop"]["verdict"] == "fail"
    assert runs["pg-loop"]["agent"] == "pg-test"
    assert runs["pg-good"]["cost_usd"] > 0

    events = store.get_events(pg_db, "pg-loop")
    assert events[0][0]["type"] == "run_start"
    assert any(e["type"] == "tool_call" for e, _ in events)

    findings = store.get_findings(pg_db, "pg-loop")
    assert any(f["label"] == "loop" for f in findings)


def test_ingest_is_idempotent_on_postgres(tmp_path, pg_db):
    run_dir = _record(tmp_path, 1, "pg-loop", pg_db)
    store.ingest_run(pg_db, run_dir)
    store.ingest_run(pg_db, run_dir)
    assert len(store.list_runs(pg_db)) == 1


def test_add_finding_and_costs_on_postgres(tmp_path, pg_db):
    _record(tmp_path, 0, "pg-good", pg_db)

    store.add_finding(pg_db, "pg-good", 6, "judge_wrong_answer", "fail", 0.9, "judge says no")
    run = store.list_runs(pg_db)[0]
    assert run["verdict"] == "fail"
    assert "judge_wrong_answer" in run["labels"]

    summary = store.costs_summary(pg_db)
    assert summary["runs"] == 1
    assert summary["per_agent"][0]["key"] == "pg-test"
