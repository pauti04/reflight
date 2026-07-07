"""Sprint 8: OpenAI-compatible recording and replay."""

import socket

import pytest

import agentscope
from agentscope import ReplayDivergence, read_events

TASK = "Summarize the plot of Hamlet in one sentence."
ANSWER = "A Danish prince avenges his father and nearly everyone dies."


class _FakeCompletion:
    """Duck-typed OpenAI ChatCompletion (has model_dump, attribute access)."""

    def __init__(self, data: dict):
        self._data = data
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Msg", (), {"content": data["choices"][0]["message"]["content"]}
                    )(),
                    "finish_reason": "stop",
                },
            )()
        ]

    def model_dump(self, **_):
        return self._data


class FakeOpenAI:
    def __init__(self):
        from types import SimpleNamespace

        self.calls = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls += 1
        return _FakeCompletion(
            {
                "id": f"chatcmpl-fake-{self.calls}",
                "model": kwargs.get("model", "gpt-4o"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ANSWER},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 25, "completion_tokens": 15, "total_tokens": 40},
            }
        )


def _openai_agent(client, task: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": task}]
    )
    return response.choices[0].message.content


@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_openai_record_and_replay(tmp_path, no_network):
    run_dir = tmp_path / "run"

    session = agentscope.record(run_dir, task=TASK)
    client = session.wrap_openai(FakeOpenAI())
    recorded = _openai_agent(client, TASK)
    session.end(final_text=recorded)
    assert recorded == ANSWER

    events = read_events(run_dir)
    llm = next(e for e in events if e["type"] == "llm_call")
    assert llm["provider"] == "openai"
    end = next(e for e in events if e["type"] == "run_end")
    assert end["input_tokens"] == 25 and end["output_tokens"] == 15

    session = agentscope.replay(run_dir)
    client = session.wrap_openai()
    replayed = _openai_agent(client, TASK)
    assert replayed == recorded


def test_openai_replay_detects_divergence(tmp_path):
    run_dir = tmp_path / "run"
    session = agentscope.record(run_dir, task=TASK)
    client = session.wrap_openai(FakeOpenAI())
    _openai_agent(client, TASK)
    session.end()

    session = agentscope.replay(run_dir)
    client = session.wrap_openai()
    with pytest.raises(ReplayDivergence):
        _openai_agent(client, "A different prompt entirely")


def test_attrview_supports_openai_access_patterns(tmp_path):
    from agentscope.replayer import AttrView

    view = AttrView({"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})
    assert view.choices[0].message.content == "hi"
    assert len(view.choices) == 1
    assert [c.finish_reason for c in view.choices] == ["stop"]
    assert view.model_dump()["choices"][0]["message"]["content"] == "hi"
