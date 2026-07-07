"""Sprint 7: the cost governor and the cost dashboard."""

import pytest

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight import Governor, GovernorKill, read_events, store
from reflight.classify import classify

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _session(tmp_path, seed, governor, db=None, agent_name=None):
    run_dir = tmp_path / "run"
    return reflight.record(
        run_dir,
        task=TASK,
        client=FlakyAnthropic(seed),
        tools=make_tools(run_dir / "notes"),
        db_path=db,
        governor=governor,
        agent_name=agent_name,
    ), run_dir


def test_loop_breaker_kills_and_records(tmp_path):
    db = tmp_path / "db"
    session, run_dir = _session(tmp_path, 1, Governor(loop_breaker=3), db=db)
    with pytest.raises(GovernorKill, match="loop circuit breaker"):
        example.run_agent(session, TASK)

    events = read_events(run_dir)
    error = next(e for e in events if e["type"] == "error")
    assert error["error_type"] == "GovernorKill"
    end = next(e for e in events if e["type"] == "run_end")
    assert end["status"] == "killed"
    # exactly 3 identical calls were allowed through
    assert sum(1 for e in events if e["type"] == "tool_call") == 3
    labels = {f.label for f in classify(events)}
    assert "governor_kill" in labels
    assert "crash" not in labels

    run = store.list_runs(db)[0]
    assert run["status"] == "killed"
    assert run["verdict"] == "fail"


def test_cost_budget_kills(tmp_path):
    # seed-1 flaky loop costs ~$0.006; a $0.002 cap must kill it mid-run
    session, run_dir = _session(tmp_path, 1, Governor(max_cost_usd=0.002))
    with pytest.raises(GovernorKill, match="budget exceeded"):
        example.run_agent(session, TASK)
    assert session.total_cost_usd >= 0.002
    end = next(e for e in read_events(run_dir) if e["type"] == "run_end")
    assert end["status"] == "killed"


def test_token_and_call_budgets(tmp_path):
    session, _ = _session(tmp_path, 1, Governor(max_total_tokens=300))
    with pytest.raises(GovernorKill, match="token budget"):
        example.run_agent(session, TASK)

    session, _ = _session(tmp_path, 1, Governor(max_llm_calls=2))
    with pytest.raises(GovernorKill, match="llm-call limit"):
        example.run_agent(session, TASK)


def test_tool_cache_serves_repeats_without_execution(tmp_path):
    calls = {"n": 0}

    def counting_calculator(expression: str) -> str:
        calls["n"] += 1
        return "18700034"

    governor = Governor(cache_tool_calls=True)
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir,
        task=TASK,
        client=FlakyAnthropic(1),  # loop: same calculator call 5×
        tools={"calculator": counting_calculator},
        governor=governor,
    )
    example.run_agent(session, TASK)

    assert calls["n"] == 1  # executed once, served from cache 4×
    tool_events = [e for e in read_events(run_dir) if e["type"] == "tool_call"]
    assert len(tool_events) == 5  # every call still recorded
    assert sum(1 for e in tool_events if e.get("cached")) == 4
    assert governor.stats()["cache_hits"] == 4


def test_governed_run_replays_deterministically(tmp_path):
    session, run_dir = _session(tmp_path, 1, Governor(loop_breaker=3))
    with pytest.raises(GovernorKill):
        example.run_agent(session, TASK)

    # the killed run replays: same prefix, and the replayer stops where the
    # recording stops (exhausted = divergence, which is honest)
    replay = reflight.replay(run_dir)
    with pytest.raises(reflight.ReplayDivergence, match="exhausted"):
        example.run_agent(replay, replay.task)
    # 4 llm calls + 3 tool calls replayed — the kill landed on the 4th tool attempt
    assert len(replay.replay_log) == 7


def test_costs_summary_and_anomalies(tmp_path):
    db = tmp_path / "db"
    for seed in range(4):  # seeds 0,3 pass (~$0.0042); 1 loop ($0.0063); 2 errors
        run_dir = tmp_path / f"r{seed}"
        session = reflight.record(
            run_dir,
            task=TASK,
            client=FlakyAnthropic(seed),
            tools=make_tools(run_dir / "notes"),
            db_path=db,
            agent_name="fleet-a" if seed % 2 == 0 else "fleet-b",
        )
        example.run_agent(session, TASK)

    summary = store.costs_summary(db, anomaly_factor=1.4)
    assert summary["runs"] == 4
    assert summary["total_usd"] > 0
    assert len(summary["per_task"]) == 1
    agents = {g["key"] for g in summary["per_agent"]}
    assert agents == {"fleet-a", "fleet-b"}
    assert len(summary["per_day"]) == 1
    # the loop run costs ~1.5× the median — flagged at factor 1.4
    assert any(a["run_id"] == "r1" for a in summary["anomalies"])
