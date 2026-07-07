"""Sprint 6: consistency scoring, baselines, regression comparison."""

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

from reflight.reliability import (
    ConsistencyReport,
    compare,
    load_baseline,
    measure,
    render,
    save_baseline,
)

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _agent(session, task):
    return example.run_agent(session, task)


def _measure(tmp_path, offset=0, n=10):
    return measure(
        _agent,
        TASK,
        n,
        client_factory=lambda i: FlakyAnthropic(i + offset),
        tools_factory=lambda d: make_tools(d / "notes"),
        runs_root=tmp_path / f"fleet-{offset}",
        concurrency=3,
    )


def test_consistency_report_numbers(tmp_path):
    report = _measure(tmp_path)
    assert report.n == report.completed == 10
    assert report.passes == 4
    assert report.pass_rate == 0.4
    assert report.failure_histogram["loop"] == 3
    assert report.failure_histogram["wrong_tool_args"] == 6  # 2 bad calls × 3 runs
    assert report.distinct_answers == 3  # correct, "42", and "could not retrieve"
    assert report.cost_mean > 0
    assert report.total_cost > report.cost_mean


def test_render_is_readable(tmp_path):
    text = render(_measure(tmp_path))
    assert "pass rate:     40%" in text
    assert "loop" in text and "█" in text


def test_baseline_roundtrip_and_no_self_regression(tmp_path):
    report = _measure(tmp_path)
    path = tmp_path / "baseline.json"
    save_baseline(report, path)
    baseline = load_baseline(path)
    assert isinstance(baseline, ConsistencyReport)
    assert compare(report, baseline) == []


def test_degraded_agent_regresses_against_baseline(tmp_path):
    baseline = _measure(tmp_path, offset=0)
    degraded = _measure(tmp_path, offset=1)
    regressions = compare(degraded, baseline)
    assert any("pass rate dropped" in r for r in regressions)


def test_compare_tolerances_and_new_modes():
    base = ConsistencyReport(
        task="t", n=10, completed=10, passes=8, pass_rate=0.8,
        failure_histogram={"loop": 2}, cost_mean=0.01,
    )
    # within tolerance: small drop allowed
    wobble = ConsistencyReport(
        task="t", n=10, completed=10, passes=7, pass_rate=0.7,
        failure_histogram={"loop": 3}, cost_mean=0.011,
    )
    assert compare(wobble, base, max_pass_rate_drop=0.15) == []

    # new failure mode + cost blowup both flagged
    worse = ConsistencyReport(
        task="t", n=10, completed=10, passes=8, pass_rate=0.8,
        failure_histogram={"loop": 1, "crash": 2}, cost_mean=0.05,
    )
    regressions = compare(worse, base)
    assert any("new failure mode" in r and "crash" in r for r in regressions)
    assert any("cost" in r for r in regressions)
