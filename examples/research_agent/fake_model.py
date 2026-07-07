"""A scripted stand-in for the Anthropic API so the spike runs without an API key.

It returns real `anthropic.types.Message` objects, so the recorder and the agent
loop cannot tell the difference from the live client. Behavior is a deterministic
state machine over the conversation: same task in, same responses out.

This is a dev convenience only — Sprint 0's success criteria must also be
verified against at least one run recorded from the real API.
"""

from __future__ import annotations

from typing import Any

from anthropic.types import Message


def _tool_use(name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "name": name, "input": tool_input}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _script_for(task: str) -> list[dict]:
    t = task.lower()
    if "0" in t and ("divide" in t or "/" in t or "divided" in t):
        # The seeded failure: the model dutifully asks the calculator to divide by zero.
        return [
            _tool_use("calculator", {"expression": "12 / 0"}),
            _text(
                "The calculator returned an error: dividing by zero is undefined, "
                "so 12 / 0 has no numeric answer."
            ),
        ]
    return [
        _tool_use("web_search", {"query": "population of Tokyo"}),
        _tool_use("calculator", {"expression": "37400068 / 2"}),
        _tool_use(
            "save_note",
            {
                "title": "Tokyo population halved",
                "content": "Tokyo metro population is ~37,400,068 (2025 est.); half is 18,700,034.",
            },
        ),
        _text(
            "Tokyo's metropolitan population is about 37,400,068 (2025 estimate). "
            "Divided by 2, that is 18,700,034."
        ),
    ]


class _FakeStream:
    """Mimics anthropic's message stream: word-by-word text chunks."""

    def __init__(self, final: Message):
        self._final = final

    @property
    def text_stream(self):
        for block in self._final.content:
            if block.type == "text":
                words = block.text.split(" ")
                for i, word in enumerate(words):
                    yield word if i == len(words) - 1 else word + " "

    def get_final_message(self) -> Message:
        return self._final


class _FakeStreamManager:
    def __init__(self, final: Message):
        self._stream = _FakeStream(final)

    def __enter__(self) -> _FakeStream:
        return self._stream

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeMessages:
    def stream(self, **kwargs: Any) -> _FakeStreamManager:
        return _FakeStreamManager(self.create(**kwargs))

    def create(self, **kwargs: Any) -> Message:
        messages = kwargs["messages"]
        first_user = messages[0]["content"]
        task = first_user if isinstance(first_user, str) else ""
        n_assistant = sum(1 for m in messages if m["role"] == "assistant")

        script = _script_for(task)
        step = script[min(n_assistant, len(script) - 1)]

        if step["type"] == "tool_use":
            content = [{**step, "id": f"toolu_fake_{n_assistant:03d}"}]
            stop_reason = "tool_use"
        else:
            content = [step]
            stop_reason = "end_turn"

        return Message.model_validate(
            {
                "id": f"msg_fake_{n_assistant:03d}",
                "type": "message",
                "role": "assistant",
                "model": kwargs.get("model", "claude-sonnet-5"),
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 120 + 15 * n_assistant, "output_tokens": 42},
            }
        )


class FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()
