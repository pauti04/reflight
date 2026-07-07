"""Sprint 1: schema, pricing, store, and 3-line auto-instrumentation."""

import socket

import pytest

import main as example
from fake_model import FakeAnthropic
from tools import TOOL_SPECS, make_tools

import reflight
from reflight import Recorder, read_events
from reflight import pricing, schema, store

RESEARCH_TASK = "What is the population of Tokyo, and what is that number divided by 2?"
FAILURE_TASK = "What is 12 divided by 0? Use the calculator."


# -- pricing -------------------------------------------------------------------


def test_pricing_known_model():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    assert pricing.cost_usd("claude-sonnet-5", usage) == pytest.approx(3.0 + 1.5)


def test_pricing_date_suffix_and_cache_fields():
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000}
    assert pricing.cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(0.1)


def test_pricing_unknown_model_is_none():
    assert pricing.cost_usd("gpt-things", {"input_tokens": 5}) is None


# -- schema --------------------------------------------------------------------


def _record_example(tmp_path, task, db_path=None):
    run_dir = tmp_path / "run"
    session = Recorder(run_dir, FakeAnthropic(), make_tools(run_dir / "notes"), db_path=db_path)
    final_text, status = example.run_agent(session, task)
    return run_dir, final_text, status


def test_schema_valid_run_has_no_problems(tmp_path):
    run_dir, _, _ = _record_example(tmp_path, RESEARCH_TASK)
    assert schema.validate_run(read_events(run_dir)) == []


def test_schema_flags_tampering(tmp_path):
    run_dir, _, _ = _record_example(tmp_path, RESEARCH_TASK)
    events = read_events(run_dir)
    del events[1]["request_hash"]
    events[2]["seq"] = 99
    problems = schema.validate_run(events)
    assert any("request_hash" in p for p in problems)
    assert any("contiguous" in p for p in problems)


# -- store ---------------------------------------------------------------------


def test_ingest_and_query(tmp_path):
    db = tmp_path / "test.db"
    run_dir, final_text, _ = _record_example(tmp_path, RESEARCH_TASK, db_path=db)

    runs = store.list_runs(db)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["model"] == "claude-sonnet-5"
    assert run["final_text"] == final_text
    assert run["cost_usd"] > 0
    assert run["tool_errors"] == 0

    events = store.get_events(db, run["run_id"])
    assert len(events) == run["event_count"]
    llm_costs = [c for e, c in events if e["type"] == "llm_call"]
    assert all(c is not None and c > 0 for c in llm_costs)


def test_ingest_is_idempotent(tmp_path):
    db = tmp_path / "test.db"
    run_dir, _, _ = _record_example(tmp_path, FAILURE_TASK)
    store.ingest_run(db, run_dir)
    store.ingest_run(db, run_dir)
    runs = store.list_runs(db)
    assert len(runs) == 1
    assert runs[0]["tool_errors"] == 1


# -- 3-line auto-instrumentation ------------------------------------------------


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _plain_agent(client, tools, task):
    """An agent that owns its loop and calls tools as plain functions."""
    messages = [{"role": "user", "content": task}]
    for _ in range(8):
        response = client.messages.create(
            model="claude-sonnet-5", max_tokens=1024, tools=TOOL_SPECS, messages=messages
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    output = tools[block.name](**block.input)
                    entry = {"type": "tool_result", "tool_use_id": block.id, "content": output}
                except Exception as exc:
                    entry = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"{type(exc).__name__}: {exc}",
                        "is_error": True,
                    }
                results.append(entry)
        messages.append({"role": "user", "content": results})
    return None


@pytest.mark.parametrize("task", [RESEARCH_TASK, FAILURE_TASK])
def test_wrapped_agent_records_and_replays(tmp_path, task, no_network):
    run_dir = tmp_path / "run"

    session = reflight.record(run_dir, task=task)
    client = session.wrap(FakeAnthropic())
    tools = {n: session.tool(f) for n, f in make_tools(run_dir / "notes").items()}
    recorded = _plain_agent(client, tools, task)
    session.end(final_text=recorded)
    assert recorded

    session = reflight.replay(run_dir)
    client = session.wrap()
    tools = {n: session.tool(f) for n, f in make_tools(run_dir / "notes").items()}
    replayed = _plain_agent(client, tools, task)
    assert replayed == recorded


def test_recording_context_manager_captures_crash(tmp_path):
    db = tmp_path / "test.db"
    run_dir = tmp_path / "run"
    with pytest.raises(RuntimeError, match="agent exploded"):
        with reflight.recording(run_dir, task="doomed", db_path=db):
            raise RuntimeError("agent exploded")

    events = read_events(run_dir)
    error = next(e for e in events if e["type"] == "error")
    assert error["error_type"] == "RuntimeError"
    assert store.list_runs(db)[0]["status"] == "error"
