"""Diff normalization, secret redaction, and MCP record/replay."""

import asyncio
import json

import pytest

import reflight
from reflight import read_events, redact_patterns
from reflight.diff import diff_runs, event_signature

TASK = "test task"


# -- diff normalization: identifiers are not behavior --------------------------------


def _llm_event(msg_id: str, created: int, text: str, tool_id: str) -> dict:
    return {
        "seq": 1,
        "type": "llm_call",
        "request": {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "tool", "tool_use_id": tool_id, "content": "42"},
            ],
        },
        "request_hash": "differs-per-run",
        "response": {
            "id": msg_id,
            "created": created,
            "system_fingerprint": f"fp_{msg_id}",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": text}}],
        },
    }


def test_volatile_ids_do_not_cause_divergence():
    a = _llm_event("msg_aaa", 1751900000, "same answer", "toolu_aaa")
    b = _llm_event("msg_bbb", 1751900099, "same answer", "toolu_bbb")
    assert event_signature(a) == event_signature(b)

    c = _llm_event("msg_ccc", 1751900000, "DIFFERENT answer", "toolu_aaa")
    assert event_signature(a) != event_signature(c)


def test_diff_runs_identical_for_behaviorally_equal_live_runs():
    start = {"seq": 0, "type": "run_start", "task": TASK}
    end = {"seq": 2, "type": "run_end", "status": "completed", "final_text": "42"}
    run_a = [start, _llm_event("msg_1", 100, "42", "t1"), end]
    run_b = [start, _llm_event("msg_2", 200, "42", "t2"), end]
    assert diff_runs(run_a, run_b)["identical"] is True


# -- redaction ------------------------------------------------------------------------


def test_redact_patterns_scrubs_recordings_but_keeps_them_replayable(tmp_path):
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir, task=TASK, redact=redact_patterns(r"sk-[A-Za-z0-9]+")
    )

    @session.tool
    def fetch_config() -> str:
        return "api_key=sk-VERYSECRET123 region=us-east-1"

    secret_result = fetch_config()
    assert "sk-VERYSECRET123" in secret_result  # the agent saw the real value
    session.end(final_text="done")

    raw = (run_dir / "events.jsonl").read_text()
    assert "sk-VERYSECRET123" not in raw  # ...but the disk never did
    assert "▮▮▮redacted▮▮▮" in raw

    # hash fields survived redaction → the recording still replays
    replay = reflight.replay(run_dir)
    replayed = replay.tool(fetch_config)()
    assert "▮▮▮redacted▮▮▮" in replayed


# -- MCP record/replay -----------------------------------------------------------------


class _TextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text

    def model_dump(self, **_):
        return {"type": "text", "text": self.text}


class _FakeToolResult:
    """Shaped like mcp.types.CallToolResult: attribute access + model_dump."""

    def __init__(self, text: str, is_error: bool = False):
        self.content = [_TextBlock(text)]
        self.isError = is_error

    def model_dump(self, **_):
        return {
            "content": [block.model_dump() for block in self.content],
            "isError": self.isError,
        }


class FakeMCPSession:
    """Duck-typed MCP ClientSession: async call_tool()."""

    def __init__(self):
        self.calls = 0

    async def call_tool(self, name: str, arguments: dict):
        self.calls += 1
        if name == "divide" and arguments.get("b") == 0:
            return _FakeToolResult("division by zero", is_error=True)
        return _FakeToolResult(str(arguments["a"] + arguments["b"]))


async def _mcp_agent(mcp) -> tuple[str, str]:
    ok = await mcp.call_tool("add", {"a": 2, "b": 3})
    bad = await mcp.call_tool("divide", {"a": 1, "b": 0})
    return ok.content[0].text, bad.content[0].text


def test_mcp_calls_record_and_replay(tmp_path):
    run_dir = tmp_path / "run"
    fake = FakeMCPSession()

    session = reflight.record(run_dir, task=TASK)
    mcp = session.wrap_mcp(fake)
    recorded = asyncio.run(_mcp_agent(mcp))
    session.end(final_text=recorded[0])

    assert fake.calls == 2
    events = read_events(run_dir)
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert [e["provider"] for e in tool_events] == ["mcp", "mcp"]
    assert tool_events[0]["is_error"] is False
    assert tool_events[1]["is_error"] is True  # isError result recorded as data
    assert tool_events[1]["result"]["content"][0]["text"] == "division by zero"

    # replay: no MCP session, no calls, same values through the same agent code
    replay = reflight.replay(run_dir)
    replayed = asyncio.run(_mcp_agent(replay.wrap_mcp()))
    assert replayed == recorded
    assert fake.calls == 2  # untouched


def test_mcp_transport_failure_records_and_reraises(tmp_path):
    class ExplodingMCP:
        async def call_tool(self, name, arguments):
            raise ConnectionError("server went away")

    run_dir = tmp_path / "run"
    session = reflight.record(run_dir, task=TASK)
    mcp = session.wrap_mcp(ExplodingMCP())
    with pytest.raises(ConnectionError):
        asyncio.run(mcp.call_tool("add", {"a": 1, "b": 2}))
    session.end(status="error", final_text=None)

    event = next(e for e in read_events(run_dir) if e["type"] == "tool_call")
    assert event["is_error"] is True
    assert "ConnectionError" in event["result"]

    # replay reconstructs the failure for the same agent code path
    replay = reflight.replay(run_dir)
    with pytest.raises(ConnectionError):
        asyncio.run(replay.wrap_mcp().call_tool("add", {"a": 1, "b": 2}))


def test_mcp_result_dict_survives_json_round_trip(tmp_path):
    run_dir = tmp_path / "run"
    session = reflight.record(run_dir, task=TASK)
    asyncio.run(session.wrap_mcp(FakeMCPSession()).call_tool("add", {"a": 1, "b": 1}))
    session.end()
    # events.jsonl is valid JSON line by line even with dict results
    for line in (run_dir / "events.jsonl").read_text().splitlines():
        json.loads(line)
