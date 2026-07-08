"""Recurring-failure fingerprinting and reliability trends."""

from fastapi.testclient import TestClient

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight import read_events, store
from reflight.classify import classify
from reflight.server import create_app

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _record(tmp_path, seed, run_id, db):
    run_dir = tmp_path / run_id
    session = reflight.record(run_dir, task=TASK, db_path=db)
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    return run_dir


def _fleet(tmp_path, db, n=6):
    for seed in range(n):
        _record(tmp_path, seed, f"flaky-{seed:02d}", db)


# -- signatures ------------------------------------------------------------------


def test_same_bug_same_signature_across_runs(tmp_path):
    db = tmp_path / "db"
    loop_a = classify(read_events(_record(tmp_path, 1, "a", db)))
    loop_b = classify(read_events(_record(tmp_path, 4, "b", db)))
    assert loop_a[0].signature == loop_b[0].signature
    assert loop_a[0].signature.startswith("loop:calculator:")

    wrong_a = classify(read_events(_record(tmp_path, 2, "c", db)))
    wrong_sigs = {f.signature for f in wrong_a if f.label == "wrong_tool_args"}
    assert wrong_sigs == {"wrong_tool_args:web_search:missing:query+unknown:q"}
    # different bugs never share a fingerprint
    assert not wrong_sigs & {loop_a[0].signature}


def test_volatile_details_do_not_change_the_signature():
    def loop_events(repeats):
        events = [{"seq": 0, "type": "run_start", "task": "t", "ts": 0, "schema": 1}]
        for i in range(repeats):
            events.append(
                {
                    "seq": i + 1,
                    "type": "tool_call",
                    "name": "calculator",
                    "input": {"expression": "1/1"},
                    "input_hash": "abc123",
                    "tool_use_id": f"t{i}",
                    "result": "1",
                    "is_error": False,
                    "ts": 0,
                    "schema": 1,
                }
            )
        return events

    five = next(f for f in classify(loop_events(5)) if f.label == "loop")
    nine = next(f for f in classify(loop_events(9)) if f.label == "loop")
    assert five.detail != nine.detail  # counts differ...
    assert five.signature == nine.signature  # ...but it's the same bug


# -- store queries -----------------------------------------------------------------


def test_recurring_failures_groups_across_runs(tmp_path):
    db = tmp_path / "db"
    _fleet(tmp_path, db)  # seeds 0-5: pass/loop/wrong ×2

    recurring = store.recurring_failures(db)
    by_label = {g["label"]: g for g in recurring}
    assert by_label["loop"]["count"] == 2
    assert by_label["loop"]["run_ids"] == ["flaky-01", "flaky-04"]
    assert by_label["wrong_tool_args"]["count"] == 2
    assert by_label["tool_error_cascade"]["run_ids"] == ["flaky-02", "flaky-05"]
    assert all(g["first_seen"] <= g["last_seen"] for g in recurring)


def test_recurrences_for_one_run(tmp_path):
    db = tmp_path / "db"
    _fleet(tmp_path, db)
    matches = store.recurrences(db, "flaky-01")
    (sig,) = matches.keys()
    assert sig.startswith("loop:")
    assert [m["run_id"] for m in matches[sig]] == ["flaky-04"]
    # a passing run has no recurrences
    assert store.recurrences(db, "flaky-00") == {}


def test_reliability_trend_buckets(tmp_path):
    db = tmp_path / "db"
    _fleet(tmp_path, db)
    trend = store.reliability_trend(db)
    (points,) = trend.values()
    assert len(points) == 1  # all recorded now → one day bucket
    assert points[0]["n"] == 6
    assert points[0]["passes"] == 2
    # summary carries the trend per task
    report = store.reliability_summary(db)[0]
    assert report["trend"] == points


# -- API surfaces --------------------------------------------------------------------


def test_run_endpoint_carries_seen_in_and_recurring_endpoint(tmp_path):
    db = tmp_path / "db"
    _fleet(tmp_path, db)
    client = TestClient(create_app(db))

    run = client.get("/api/runs/flaky-04").json()
    loop_finding = next(f for f in run["findings"] if f["label"] == "loop")
    assert loop_finding["seen_in"] == ["flaky-01"]

    recurring = client.get("/api/recurring").json()
    assert {g["label"] for g in recurring} >= {"loop", "wrong_tool_args"}
