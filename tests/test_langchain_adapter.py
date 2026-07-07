"""Sprint 10: the LangChain/LangGraph adapter — record + replay a real
create_react_agent graph against a scripted OpenAI-shaped model."""

import json
import socket

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langchain_openai")

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

import reflight
from reflight import ReplayDivergence, read_events
from reflight.adapters.langchain import instrument

TASK = "What is 17 + 25?"


class FakeOpenAI:
    """OpenAI-shaped scripted model: one tool call, then a final answer."""

    def __init__(self):
        from types import SimpleNamespace

        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        n_assistant = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        if n_assistant == 0:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_add_001",
                        "type": "function",
                        "function": {"name": "add", "arguments": json.dumps({"a": 17, "b": 25})},
                    }
                ],
            }
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": "17 + 25 = 42."}
            finish = "stop"
        return {
            "id": f"chatcmpl-fake-{n_assistant}",
            "object": "chat.completion",
            "created": 0,
            "model": kwargs.get("model", "gpt-4o-mini"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 25, "total_tokens": 105},
        }


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _build_agent(session, openai_client=None):
    model = ChatOpenAI(model="gpt-4o-mini", api_key="test-key", temperature=0)
    model, tools = instrument(session, model, [add], openai_client=openai_client)
    return create_react_agent(model, tools)


def _final_text(result) -> str:
    return result["messages"][-1].content


def test_langgraph_agent_records_and_replays(tmp_path, no_network):
    run_dir = tmp_path / "lg-run"

    session = reflight.record(run_dir, task=TASK)
    agent = _build_agent(session, openai_client=FakeOpenAI())
    live = _final_text(agent.invoke({"messages": [("user", TASK)]}))
    session.end(final_text=live)
    assert live == "17 + 25 = 42."

    events = read_events(run_dir)
    llm_events = [e for e in events if e["type"] == "llm_call"]
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert len(llm_events) == 2
    assert all(e.get("provider") == "openai" for e in llm_events)
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "add"
    assert tool_events[0]["result"] == 42

    # replay: fresh graph, same code, zero network
    session = reflight.replay(run_dir)
    agent = _build_agent(session)
    replayed = _final_text(agent.invoke({"messages": [("user", TASK)]}))
    assert replayed == live


def test_langgraph_replay_detects_divergence(tmp_path, no_network):
    run_dir = tmp_path / "lg-run"
    session = reflight.record(run_dir, task=TASK)
    agent = _build_agent(session, openai_client=FakeOpenAI())
    agent.invoke({"messages": [("user", TASK)]})
    session.end()

    session = reflight.replay(run_dir)
    agent = _build_agent(session)
    with pytest.raises(ReplayDivergence, match="differs from the recording"):
        agent.invoke({"messages": [("user", "A different question entirely?")]})


def test_coroutine_only_tool_is_rejected_loudly(tmp_path):
    from langchain_core.tools import StructuredTool

    async def async_add(a: int, b: int) -> int:
        return a + b

    async_tool = StructuredTool.from_function(
        coroutine=async_add, name="async_add", description="adds"
    )
    session = reflight.record(tmp_path / "run", task="t")
    with pytest.raises(ValueError, match="coroutine-only"):
        instrument(session, ChatOpenAI(model="gpt-4o-mini", api_key="k"), [async_tool],
                   openai_client=FakeOpenAI())