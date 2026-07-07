"""Sprint 3: failure classification, verdicts, and run diffing."""

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

from agentscope import Recorder, read_events, store
from agentscope.classify import classify, verdict
from agentscope.diff import diff_runs

TASK = "What is the population of Tokyo, and what is that number divided by 2?"

SEED_SUCCESS, SEED_LOOP, SEED_WRONG_ARGS = 0, 1, 2


def _record_flaky(tmp_path, seed, db_path=None):
    run_dir = tmp_path / f"flaky-{seed:02d}"
    session = Recorder(run_dir, FlakyAnthropic(seed), make_tools(run_dir / "notes"), db_path=db_path)
    example.run_agent(session, TASK)
    return run_dir


def test_clean_run_classifies_as_pass(tmp_path):
    events = read_events(_record_flaky(tmp_path, SEED_SUCCESS))
    findings = classify(events)
    assert findings == []
    assert verdict(findings) == "pass"


def test_loop_is_detected(tmp_path):
    events = read_events(_record_flaky(tmp_path, SEED_LOOP))
    findings = classify(events)
    labels = {f.label for f in findings}
    assert "loop" in labels
    loop = next(f for f in findings if f.label == "loop")
    assert "repeated 5×" in loop.detail
    assert verdict(findings) == "fail"


def test_wrong_tool_args_and_cascade_are_detected(tmp_path):
    events = read_events(_record_flaky(tmp_path, SEED_WRONG_ARGS))
    findings = classify(events)
    labels = {f.label for f in findings}
    assert "wrong_tool_args" in labels
    assert "tool_error_cascade" in labels
    wrong = next(f for f in findings if f.label == "wrong_tool_args")
    assert "query" in wrong.detail or "q" in wrong.detail
    assert verdict(findings) == "fail"


def test_crash_and_runaway_classification():
    crash_events = [
        {"seq": 0, "type": "run_start", "task": "t"},
        {"seq": 1, "type": "error", "error_type": "RuntimeError", "message": "boom"},
        {
            "seq": 2,
            "type": "run_end",
            "status": "error",
            "final_text": None,
            "input_tokens": 0,
            "output_tokens": 0,
        },
    ]
    labels = {f.label for f in classify(crash_events)}
    assert "crash" in labels

    runaway_events = crash_events[:1] + [
        {
            "seq": 1,
            "type": "run_end",
            "status": "max_turns_exceeded",
            "final_text": None,
            "input_tokens": 0,
            "output_tokens": 50_000,
        }
    ]
    labels = {f.label for f in classify(runaway_events)}
    assert "runaway" in labels
    assert "cost_blowout" in labels


def test_fleet_verdicts_land_in_store(tmp_path):
    db = tmp_path / "test.db"
    for seed in range(10):
        _record_flaky(tmp_path, seed, db_path=db)
    runs = {r["run_id"]: r for r in store.list_runs(db)}
    assert len(runs) == 10
    verdicts = [runs[f"flaky-{s:02d}"]["verdict"] for s in range(10)]
    assert verdicts == ["pass", "fail", "fail"] * 3 + ["pass"]
    assert '"loop"' in runs["flaky-01"]["labels"]
    assert store.get_findings(db, "flaky-02")


def test_diff_finds_first_divergence(tmp_path):
    events_success = read_events(_record_flaky(tmp_path, SEED_SUCCESS))
    events_loop = read_events(_record_flaky(tmp_path, SEED_LOOP))

    same = diff_runs(events_success, events_success)
    assert same["identical"] is True

    result = diff_runs(events_success, events_loop)
    assert result["identical"] is False
    assert result["divergence_seq"] == 1  # first llm response differs
