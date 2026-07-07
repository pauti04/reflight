"""Sprint 10: OpenTelemetry export — recorded runs as GenAI-convention spans."""

import pytest

pytest.importorskip("opentelemetry.sdk")

import main as example
from flaky_model import FlakyAnthropic
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from tools import make_tools

import reflight
from reflight import read_events
from reflight.otel import export_run

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _record(tmp_path, seed):
    run_dir = tmp_path / "run"
    session = reflight.record(run_dir, task=TASK, agent_name="otel-test")
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    return read_events(run_dir)


def _export(events):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    count = export_run("test-run", events, provider.get_tracer("reflight"))
    return count, exporter.get_finished_spans()


def test_span_tree_and_genai_attributes(tmp_path):
    events = _record(tmp_path, 0)  # clean run: 3 llm calls, 2 tool calls
    count, spans = _export(events)

    llm_count = sum(1 for e in events if e["type"] == "llm_call")
    tool_count = sum(1 for e in events if e["type"] == "tool_call")
    assert count == len(spans) == 1 + llm_count + tool_count

    root = next(s for s in spans if s.name == "agent_run test-run")
    assert root.attributes["reflight.task"] == TASK
    assert root.attributes["reflight.agent"] == "otel-test"
    assert root.attributes["reflight.status"] == "completed"

    chats = [s for s in spans if s.name.startswith("chat ")]
    assert len(chats) == llm_count
    for span in chats:
        assert span.parent.span_id == root.context.span_id
        assert span.attributes["gen_ai.operation.name"] == "chat"
        assert span.attributes["gen_ai.system"] == "anthropic"
        assert span.attributes["gen_ai.request.model"] == "claude-sonnet-5"
        assert span.attributes["gen_ai.usage.input_tokens"] > 0
        assert span.attributes["reflight.cost_usd"] > 0

    tools = [s for s in spans if s.name.startswith("execute_tool ")]
    assert {s.attributes["gen_ai.tool.name"] for s in tools} == {"web_search", "calculator"}

    # spans are ordered and non-overlapping: each starts at the previous end
    children = sorted(chats + tools, key=lambda s: s.start_time)
    for earlier, later in zip(children, children[1:]):
        assert earlier.end_time == later.start_time


def test_failed_tool_call_marks_span_error(tmp_path):
    events = _record(tmp_path, 2)  # wrong_tool_args: web_search errors twice
    _, spans = _export(events)
    error_spans = [s for s in spans if s.status.status_code == StatusCode.ERROR]
    assert len(error_spans) == 2
    assert all(s.name == "execute_tool web_search" for s in error_spans)
    assert "TypeError" in error_spans[0].status.description


def test_governor_kill_shows_as_root_error_and_event(tmp_path):
    from reflight import Governor, GovernorKill

    run_dir = tmp_path / "killed"
    session = reflight.record(
        run_dir,
        task=TASK,
        client=FlakyAnthropic(1),
        tools=make_tools(run_dir / "notes"),
        governor=Governor(loop_breaker=2),
    )
    with pytest.raises(GovernorKill):
        example.run_agent(session, TASK)

    _, spans = _export(read_events(run_dir))
    root = next(s for s in spans if s.name.startswith("agent_run"))
    assert root.status.status_code == StatusCode.ERROR
    assert root.attributes["reflight.status"] == "killed"
    error_events = [e for e in root.events if e.name == "error"]
    assert error_events and error_events[0].attributes["error.type"] == "GovernorKill"
