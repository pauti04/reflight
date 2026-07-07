"""Sprint 0 success criteria, as executable tests.

1. A recorded run replays byte-identical with the network hard-blocked.
2. A run containing a tool failure replays identically (failures are reproducible).
3. If the agent code changes, replay raises ReplayDivergence instead of lying.
"""

import socket
import time

import pytest

import main as example
from fake_model import FakeAnthropic
from tools import make_tools

from agentscope import Recorder, Replayer, ReplayDivergence

RESEARCH_TASK = "What is the population of Tokyo, and what is that number divided by 2?"
FAILURE_TASK = "What is 12 divided by 0? Use the calculator."


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _record(tmp_path, task):
    run_dir = tmp_path / "run"
    session = Recorder(run_dir, FakeAnthropic(), make_tools(run_dir / "notes"))
    final_text, status = example.run_agent(session, task)
    return run_dir, final_text, status


@pytest.mark.parametrize("task", [RESEARCH_TASK, FAILURE_TASK])
def test_replay_is_deterministic_with_network_blocked(tmp_path, task, no_network):
    run_dir, recorded_text, recorded_status = _record(tmp_path, task)

    session = Replayer(run_dir)
    t0 = time.perf_counter()
    replayed_text, replayed_status = example.run_agent(session, session.task)
    elapsed = time.perf_counter() - t0

    assert replayed_text == recorded_text
    assert replayed_status == recorded_status
    assert elapsed < 2.0


def test_failure_run_records_the_tool_error(tmp_path):
    run_dir, _, _ = _record(tmp_path, FAILURE_TASK)
    from agentscope import read_events

    errors = [e for e in read_events(run_dir) if e["type"] == "tool_call" and e["is_error"]]
    assert len(errors) == 1
    assert "ZeroDivisionError" in errors[0]["result"]


def test_changed_prompt_raises_divergence_not_silence(tmp_path, monkeypatch):
    run_dir, _, _ = _record(tmp_path, RESEARCH_TASK)

    monkeypatch.setattr(example, "SYSTEM", example.SYSTEM + " Always answer in French.")
    session = Replayer(run_dir)
    with pytest.raises(ReplayDivergence):
        example.run_agent(session, session.task)
