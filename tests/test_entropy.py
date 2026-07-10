"""Entropy pinning: time/random/uuid recorded once, replayed identically."""

from __future__ import annotations

import random
import time
import uuid
from typing import Any

import pytest
from anthropic.types import Message

import reflight
from reflight import ReplayDivergence
from reflight.events import read_events
from reflight.schema import validate_run


def text_message(text: str) -> dict:
    return {
        "id": "msg_entropy_000",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class FakeAnthropic:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        del kwargs
        return Message.model_validate(self._responses.pop(0))


def entropy_agent(session) -> dict:
    """Agent-loop code that consults the clock, PRNG, and uuid between calls."""
    out: dict = {}
    with session.pin():
        out["t0"] = time.time()
        out["request_id"] = str(uuid.uuid4())
        out["jitter"] = random.random()
        response = session.messages.create(
            model="claude-sonnet-5",
            max_tokens=64,
            messages=[{"role": "user", "content": f"req {out['request_id']}"}],
        )
        result, _ = session.execute("clocked_tool", {"x": 1}, "toolu_01")
        out["tool_result"] = result
        out["t1"] = time.time()
        out["retry_delay"] = random.uniform(0.1, 2.0)
        del response
    session.end(status="completed", final_text="done")
    return out


def make_tools() -> dict:
    def clocked_tool(x: int) -> str:
        # in-tool entropy must stay real and uncaptured
        time.time()
        uuid.uuid4()
        return f"ok {x}"

    return {"clocked_tool": clocked_tool}


def record_run(tmp_path):
    fake = FakeAnthropic([text_message("hello")])
    session = reflight.record(
        tmp_path / "run", task="entropy demo", client=fake, tools=make_tools()
    )
    return entropy_agent(session)


def test_record_then_replay_pins_entropy(tmp_path):
    recorded = record_run(tmp_path)

    replayed = entropy_agent(reflight.replay(tmp_path / "run"))

    assert replayed == recorded  # every entropy draw identical


def test_entropy_event_shape(tmp_path):
    record_run(tmp_path)
    events = read_events(tmp_path / "run")

    assert validate_run(events) == []
    entropy = next(e for e in events if e["type"] == "entropy")
    assert len(entropy["seeds"]) == 1
    assert len(entropy["time"]) == 2  # t0, t1 — not the tool's internal call
    assert len(entropy["uuid"]) == 1  # request_id — not the tool's internal call
    assert events[-1]["type"] == "run_end"  # entropy lands before run_end


def test_pin_restores_globals(tmp_path):
    real_time, real_uuid4 = time.time, uuid.uuid4
    record_run(tmp_path)
    assert time.time is real_time and uuid.uuid4 is real_uuid4

    entropy_agent(reflight.replay(tmp_path / "run"))
    assert time.time is real_time and uuid.uuid4 is real_uuid4


def test_replay_overdraw_diverges(tmp_path):
    record_run(tmp_path)
    session = reflight.replay(tmp_path / "run")

    with session.pin():
        time.time()
        time.time()
        with pytest.raises(ReplayDivergence, match="more time values"):
            time.time()  # recording only holds two


def test_pin_without_entropy_event_diverges(tmp_path):
    fake = FakeAnthropic([text_message("hi")])
    session = reflight.record(tmp_path / "plain", task="no pin", client=fake)
    session.messages.create(
        model="claude-sonnet-5", max_tokens=64, messages=[{"role": "user", "content": "hi"}]
    )
    session.end()

    replay = reflight.replay(tmp_path / "plain")
    with pytest.raises(ReplayDivergence, match="no entropy event"):
        replay.pin().__enter__()


def test_fork_pin_serves_prefix_then_captures(tmp_path):
    recorded = record_run(tmp_path)
    events = read_events(tmp_path / "run")
    fork_at = next(e["seq"] for e in events if e["type"] == "run_end")

    # fork past the whole recording: prefix fully replayed, then (no live calls)
    session = reflight.fork(
        tmp_path / "run",
        fork_at,
        client=FakeAnthropic([text_message("unused")]),
        tools=make_tools(),
        out_dir=tmp_path / "fork",
    )
    forked = entropy_agent(session)

    assert forked == recorded  # prefix entropy served from the source
    fork_entropy = next(
        e for e in read_events(tmp_path / "fork") if e["type"] == "entropy"
    )
    assert len(fork_entropy["time"]) == 2  # fork recording is self-contained
