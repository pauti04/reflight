"""Launch-hardening features: ensemble judge, redaction defaults,
flight check, async sessions."""

from __future__ import annotations

import asyncio
import json
import socket
import socketserver
import threading
from typing import Any

import pytest
from anthropic.types import Message

import reflight
from reflight.events import read_events
from reflight.classify import classify
from reflight.judge import judge_ensemble
from reflight.schema import validate_run


def _judge_message(verdict: dict) -> Message:
    return Message.model_validate(
        {
            "id": "msg_judge",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": json.dumps(verdict)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 40},
        }
    )


class FlakyJudge:
    """Deterministic stand-in for the case study's real observation: the
    same judge, same recording, different verdicts across passes."""

    def __init__(self, verdicts: list[bool]):
        self._verdicts = list(verdicts)
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        del kwargs
        caught = self._verdicts.pop(0)
        if caught:
            return _judge_message(
                {
                    "task_completed": True,
                    "answer_correct": False,
                    "label": "wrong_answer",
                    "confidence": 0.9,
                    "reasoning": "booked a Sunday",
                }
            )
        return _judge_message(
            {
                "task_completed": True,
                "answer_correct": True,
                "label": "ok",
                "confidence": 1.0,
                "reasoning": "looks fine",
            }
        )


EVENTS = [{"seq": 0, "type": "run_start", "task": "book a meeting"}]


def test_ensemble_majority_catches_what_one_pass_misses():
    result = judge_ensemble(EVENTS, FlakyJudge([True, False, True]), votes=3)
    assert result["ok"] is False
    assert result["label"] == "wrong_answer"
    assert result["agreement"] == pytest.approx(2 / 3)
    assert result["confidence"] == pytest.approx(0.9 * 2 / 3)
    assert len(result["votes"]) == 3


def test_ensemble_tie_breaks_toward_not_ok():
    result = judge_ensemble(EVENTS, FlakyJudge([True, False]), votes=2)
    assert result["ok"] is False


def test_ensemble_unanimous_ok():
    result = judge_ensemble(EVENTS, FlakyJudge([False, False, False]), votes=3)
    assert result["ok"] is True
    assert result["agreement"] == 1.0


# -- redaction defaults ---------------------------------------------------------


def test_redact_common_masks_the_usual_leaks(tmp_path):
    transform = reflight.redact_common(r"CUST-\d+")
    event = transform(
        {
            "type": "tool_call",
            "input_hash": "deadbeef00000000",
            "result": "email jane@example.com · key sk-abcdefghijklmnopqrstu · "
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 · customer CUST-4816",
        }
    )
    assert "jane@example.com" not in event["result"]
    assert "sk-abcdefghijklmnop" not in event["result"]
    assert "eyJhbGciOiJIUzI1Ni" not in event["result"]
    assert "CUST-4816" not in event["result"]
    assert event["input_hash"] == "deadbeef00000000"  # replay integrity survives


def test_redact_common_leaves_normal_text_alone():
    transform = reflight.redact_common()
    event = transform({"type": "run_start", "task": "refund order ORD-7351 for $49.99"})
    assert event["task"] == "refund order ORD-7351 for $49.99"


# -- flight check ---------------------------------------------------------------


class _Sink(socketserver.BaseRequestHandler):
    def handle(self):
        pass


def _local_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Sink)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _touch(port: int) -> None:
    with socket.socket() as sock:
        sock.connect(("127.0.0.1", port))


def test_flight_check_flags_unsanctioned_io_once(tmp_path):
    server = _local_server()
    port = server.server_address[1]
    try:
        session = reflight.record(tmp_path / "run", task="leaky", flight_check=True)
        with pytest.warns(UserWarning, match="outside the session"):
            _touch(port)  # agent-loop network call: flagged
        _touch(port)  # same host again: deduped, no second event
        session.end(status="completed", final_text="done")
    finally:
        server.shutdown()

    events = read_events(tmp_path / "run")
    assert validate_run(events) == []
    warnings_ = [e for e in events if e["type"] == "warning"]
    assert len(warnings_) == 1 and warnings_[0]["kind"] == "unrecorded_io"

    findings = classify(events)
    assert any(f.label == "unrecorded_io" and f.severity == "warn" for f in findings)


def test_flight_check_permits_tool_io_and_uninstalls(tmp_path):
    server = _local_server()
    port = server.server_address[1]
    real_connect = socket.socket.connect

    def fetch() -> str:
        _touch(port)  # tools may do I/O — their results are recorded
        return "fetched"

    try:
        session = reflight.record(
            tmp_path / "run", task="ok", tools={"fetch": fetch}, flight_check=True
        )
        result, is_error = session.execute("fetch", {}, "toolu_fc")
        assert (result, is_error) == ("fetched", False)
        session.end(status="completed", final_text="done")
    finally:
        server.shutdown()

    assert socket.socket.connect is real_connect  # end() uninstalled the patch
    assert not [e for e in read_events(tmp_path / "run") if e["type"] == "warning"]


# -- async sessions -------------------------------------------------------------


def _text_message(text: str, n: int) -> dict:
    return {
        "id": f"msg_async_{n:03d}",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 6},
    }


class FakeAsyncAnthropic:
    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **kwargs: Any) -> Message:
        del kwargs
        self.calls += 1
        return Message.model_validate(_text_message(f"answer {self.calls}", self.calls))


async def _async_agent(session) -> list:
    out = []
    doubled, _ = await session.execute("double", {"x": 21}, "toolu_a1")
    out.append(doubled)
    try:
        await session.execute("boom", {}, "toolu_a2")
    except Exception:  # never raises via execute; belt and suspenders
        pass
    fetched = await session.fetch_note("n-7")
    out.append(fetched)
    response = await session.messages.create(
        model="claude-sonnet-5",
        max_tokens=64,
        messages=[{"role": "user", "content": f"{doubled} {fetched}"}],
    )
    out.append(response.content[0].text)
    session.end(status="completed", final_text=response.content[0].text)
    return out


def _make_async_session(session):
    """Attach tools: one async, one sync-raising, one via the decorator."""

    async def double(x: int) -> str:
        await asyncio.sleep(0)
        return str(x * 2)

    def boom() -> str:
        raise ValueError("kaput")

    async def fetch_note(note_id: str) -> str:
        await asyncio.sleep(0)
        return f"note {note_id}"

    if hasattr(session, "_tools"):  # replayer serves execute() from the recording
        session._tools["double"] = double
        session._tools["boom"] = boom
    session.fetch_note = session.tool(fetch_note)
    return session


def test_async_record_then_async_replay(tmp_path):
    fake = FakeAsyncAnthropic()
    session = _make_async_session(
        reflight.record_async(tmp_path / "run", task="async demo", client=fake)
    )
    recorded = asyncio.run(_async_agent(session))

    events = read_events(tmp_path / "run")
    assert validate_run(events) == []
    boom_event = next(e for e in events if e["type"] == "tool_call" and e["name"] == "boom")
    assert boom_event["is_error"] and "ValueError" in boom_event["result"]

    replay_session = _make_async_session(reflight.replay_async(tmp_path / "run"))
    replayed = asyncio.run(_async_agent(replay_session))
    assert replayed == recorded
    assert replay_session.replayed_final_text == "answer 1"


def test_async_recording_replays_through_sync_session(tmp_path):
    """The format is facade-agnostic: async-recorded, sync-replayed."""
    session = _make_async_session(
        reflight.record_async(tmp_path / "run", task="cross", client=FakeAsyncAnthropic())
    )
    recorded = asyncio.run(_async_agent(session))

    sync_session = reflight.replay(tmp_path / "run")
    doubled, _ = sync_session.execute("double", {"x": 21}, "toolu_a1")
    assert doubled == recorded[0]


class FakeAsyncOpenAI:
    class _Resp:
        def model_dump(self, mode: str = "json") -> dict:
            return {
                "id": "chat_async",
                "model": "gpt-4o-mini",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "openai says hi"}}
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            }

    def __init__(self):
        from types import SimpleNamespace

        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs: Any) -> "FakeAsyncOpenAI._Resp":
        del kwargs
        return self._Resp()


def test_async_openai_record_and_replay(tmp_path):
    async def go_record():
        session = reflight.record_async(tmp_path / "run", task="openai async")
        client = session.wrap_openai(FakeAsyncOpenAI())
        response = await client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
        )
        session.end(status="completed", final_text="done")
        return response.model_dump()["choices"][0]["message"]["content"]

    async def go_replay():
        session = reflight.replay_async(tmp_path / "run")
        client = session.wrap_openai()
        response = await client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
        )
        return response.choices[0].message.content

    assert asyncio.run(go_record()) == "openai says hi"
    assert asyncio.run(go_replay()) == "openai says hi"
