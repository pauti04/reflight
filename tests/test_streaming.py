"""Sprint 10: streaming record/replay (the messages.stream() helper pattern)."""

import socket

import pytest

from fake_model import FakeAnthropic
from tools import TOOL_SPECS, make_tools

import reflight
from reflight import Governor, GovernorKill, ReplayDivergence, read_events

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def streaming_agent(session, task):
    """An agent that streams every model turn — chunks are part of its behavior."""
    messages = [{"role": "user", "content": task}]
    seen_chunks: list[str] = []
    for _ in range(8):
        with session.messages.stream(
            model="claude-sonnet-5", max_tokens=1024, tools=TOOL_SPECS, messages=messages
        ) as stream:
            for chunk in stream.text_stream:
                seen_chunks.append(chunk)
            final = stream.get_final_message()
        messages.append({"role": "assistant", "content": list(final.content)})
        if final.stop_reason != "tool_use":
            text = "".join(b.text for b in final.content if b.type == "text")
            return seen_chunks, text
        results = []
        for block in final.content:
            if block.type == "tool_use":
                result, is_error = session.execute(block.name, dict(block.input), block.id)
                entry = {"type": "tool_result", "tool_use_id": block.id, "content": result}
                if is_error:
                    entry["is_error"] = True
                results.append(entry)
        messages.append({"role": "user", "content": results})
    return seen_chunks, None


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _record_streaming(tmp_path, task=TASK):
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir, task=task, client=FakeAnthropic(), tools=make_tools(run_dir / "notes")
    )
    chunks, text = streaming_agent(session, task)
    session.end(final_text=text)
    return run_dir, chunks, text


def test_stream_chunks_are_recorded(tmp_path):
    run_dir, chunks, text = _record_streaming(tmp_path)
    assert text and "18,700,034" in text
    assert len(chunks) > 5  # word-by-word, not one blob

    llm_events = [e for e in read_events(run_dir) if e["type"] == "llm_call"]
    assert all("stream" in e for e in llm_events)
    recorded_chunks = [c for e in llm_events for c in e["stream"]["text_chunks"]]
    assert recorded_chunks == chunks


def test_streaming_replay_is_chunk_identical(tmp_path, no_network):
    run_dir, live_chunks, live_text = _record_streaming(tmp_path)

    session = reflight.replay(run_dir)
    replay_chunks, replay_text = streaming_agent(session, session.task)
    assert replay_text == live_text
    assert replay_chunks == live_chunks  # same chunk boundaries, not just same text


def test_streaming_replay_detects_divergence(tmp_path, no_network):
    run_dir, _, _ = _record_streaming(tmp_path)
    session = reflight.replay(run_dir)
    with pytest.raises(ReplayDivergence, match="differs from the recording"):
        streaming_agent(session, "A completely different task")


def create_agent(session, task):
    """streaming_agent's non-streaming twin: identical requests via create()."""
    messages = [{"role": "user", "content": task}]
    for _ in range(8):
        final = session.messages.create(
            model="claude-sonnet-5", max_tokens=1024, tools=TOOL_SPECS, messages=messages
        )
        messages.append({"role": "assistant", "content": list(final.content)})
        if final.stop_reason != "tool_use":
            return "".join(b.text for b in final.content if b.type == "text")
        results = []
        for block in final.content:
            if block.type == "tool_use":
                result, is_error = session.execute(block.name, dict(block.input), block.id)
                entry = {"type": "tool_result", "tool_use_id": block.id, "content": result}
                if is_error:
                    entry["is_error"] = True
                results.append(entry)
        messages.append({"role": "user", "content": results})
    return None


def test_non_streamed_recording_replays_through_a_streaming_agent(tmp_path, no_network):
    # recorded with create(); the agent later switched to stream() with the
    # same request kwargs — replay works; chunks fall back to one-per-text-block
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir, task=TASK, client=FakeAnthropic(), tools=make_tools(run_dir / "notes")
    )
    text = create_agent(session, TASK)
    session.end(final_text=text)

    replay = reflight.replay(run_dir)
    chunks, replay_text = streaming_agent(replay, replay.task)
    assert replay_text == text
    assert chunks == [text]  # coarse boundary, correct text


def test_governor_kills_at_stream_start(tmp_path):
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir,
        task=TASK,
        client=FakeAnthropic(),
        tools=make_tools(run_dir / "notes"),
        governor=Governor(max_llm_calls=2),
    )
    with pytest.raises(GovernorKill, match="llm-call limit"):
        streaming_agent(session, TASK)
    end = next(e for e in read_events(run_dir) if e["type"] == "run_end")
    assert end["status"] == "killed"


def test_fork_preserves_stream_prefix_and_streams_live(tmp_path):
    source, live_chunks, live_text = _record_streaming(tmp_path)

    fork_dir = tmp_path / "fork"
    session = reflight.fork(
        source,
        3,  # after the first tool call
        client=FakeAnthropic(),
        tools=make_tools(fork_dir / "notes"),
        out_dir=fork_dir,
    )
    chunks, text = streaming_agent(session, session.task)
    session.end(final_text=text)
    assert text == live_text
    assert chunks == live_chunks

    fork_events = [e for e in read_events(fork_dir) if e["type"] == "llm_call"]
    assert all("stream" in e for e in fork_events)  # prefix re-emit kept chunk data
