"""Sprint 5: promote, the test runner, and the N-run executor."""

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight.executor import run_repeated
from reflight.testing import check_assertions, load_test, promote, run_suite, run_test

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _record(tmp_path, seed, run_id, db):
    run_dir = tmp_path / run_id
    session = reflight.record(run_dir, task=TASK, db_path=db)
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    return run_dir


def _agent(session, task):
    return example.run_agent(session, task)


# -- promote ---------------------------------------------------------------------


def test_promote_failed_run_generates_editable_test(tmp_path):
    db = tmp_path / "db"
    _record(tmp_path, 1, "loopy", db)
    path = promote(db, "loopy", tests_dir=tmp_path / "agent_tests")

    test = load_test(path)
    assert test["name"] == "loopy"
    assert test["task"] == TASK
    assert test["promoted_from_verdict"] == "fail"
    kinds = [a["type"] for a in test["assertions"]]
    assert kinds == ["status", "no_findings", "final_text_not_equals"]
    assert "# Promoted from run" in path.read_text()


def test_promote_passing_run_pins_the_answer(tmp_path):
    db = tmp_path / "db"
    _record(tmp_path, 0, "good", db)
    test = load_test(promote(db, "good", tests_dir=tmp_path / "agent_tests"))
    pin = next(a for a in test["assertions"] if a["type"] == "final_text_equals")
    assert "18,700,034" in pin["value"]


# -- runner: the fail → fix → pass loop -------------------------------------------


def test_promoted_failure_fails_then_passes_after_fix(tmp_path):
    db = tmp_path / "db"
    _record(tmp_path, 1, "nightly", db)
    path = promote(db, "nightly", tests_dir=tmp_path / "agent_tests")
    test = load_test(path)
    test["assertions"].append({"type": "final_text_contains", "value": "18,700,034"})

    # bug still present: replay reproduces it for free — test fails
    result = run_test(test, _agent)
    assert result.mode == "replay"
    assert not result.passed
    assert any("loop" in f for f in result.failures)

    # model-side fix: replay still reproduces the recorded bug, so the runner
    # re-verifies live against the fixed model — and passes
    result = run_test(
        test,
        _agent,
        live_client_factory=lambda: FlakyAnthropic(0),
        tools_factory=lambda d: make_tools(d / "notes"),
        live_runs_dir=tmp_path / "live",
    )
    assert result.mode == "replay→live"
    assert result.passed, result.failures

    # still-buggy model: live re-verification confirms the failure
    result = run_test(
        test,
        _agent,
        live_client_factory=lambda: FlakyAnthropic(1),
        tools_factory=lambda d: make_tools(d / "notes"),
        live_runs_dir=tmp_path / "live",
    )
    assert result.mode == "replay→live"
    assert not result.passed


def test_divergence_without_live_client_fails_honestly(tmp_path):
    db = tmp_path / "db"
    _record(tmp_path, 1, "nightly", db)
    test = load_test(promote(db, "nightly", tests_dir=tmp_path / "agent_tests"))

    fixed_agent_result = run_test(
        {**test, "source_run": test["source_run"], "task": "A different task"},
        _agent,
    )
    assert fixed_agent_result.mode == "diverged"
    assert not fixed_agent_result.passed


def test_run_suite_reports_all_tests(tmp_path, capsys):
    db = tmp_path / "db"
    _record(tmp_path, 0, "good", db)
    _record(tmp_path, 1, "bad", db)
    promote(db, "good", tests_dir=tmp_path / "agent_tests")
    promote(db, "bad", tests_dir=tmp_path / "agent_tests")

    results = run_suite(tmp_path / "agent_tests", _agent)
    by_name = {r.name: r for r in results}
    assert by_name["good"].passed  # regression pin holds via replay
    assert not by_name["bad"].passed  # loop finding still present
    assert "1/2 passed" in capsys.readouterr().out


def test_assertion_kinds():
    events = [
        {"seq": 0, "type": "run_start", "task": "t", "ts": 0, "schema": 1},
        {
            "seq": 1,
            "type": "run_end",
            "status": "completed",
            "final_text": "the answer is 7",
            "input_tokens": 10,
            "output_tokens": 5,
            "ts": 0,
            "schema": 1,
        },
    ]
    ok = {"assertions": [
        {"type": "status", "equals": "completed"},
        {"type": "no_findings"},
        {"type": "final_text_contains", "value": "7"},
        {"type": "final_text_not_contains", "value": "42"},
    ]}
    assert check_assertions(ok, events) == []
    bad = {"assertions": [
        {"type": "final_text_equals", "value": "something else"},
        {"type": "mystery_assertion"},
    ]}
    assert len(check_assertions(bad, events)) == 2


# -- N-run executor ---------------------------------------------------------------


def test_run_repeated_records_a_fleet(tmp_path):
    db = tmp_path / "db"
    summary = run_repeated(
        _agent,
        TASK,
        6,
        client_factory=FlakyAnthropic,
        tools_factory=lambda d: make_tools(d / "notes"),
        runs_root=tmp_path / "fleet",
        db_path=db,
        concurrency=3,
    )
    assert summary["completed"] == 6
    assert summary["skipped"] == 0
    assert summary["total_cost_usd"] > 0
    verdicts = sorted(r["verdict"] for r in summary["runs"])
    assert verdicts == ["fail", "fail", "fail", "fail", "pass", "pass"]


def test_run_repeated_respects_budget(tmp_path):
    tiny_budget = 0.004  # roughly one run's cost
    summary = run_repeated(
        _agent,
        TASK,
        8,
        client_factory=FlakyAnthropic,
        tools_factory=lambda d: make_tools(d / "notes"),
        runs_root=tmp_path / "fleet",
        budget_usd=tiny_budget,
        concurrency=1,  # deterministic launch order for the assertion
    )
    assert summary["skipped"] > 0
    assert summary["completed"] < 8
