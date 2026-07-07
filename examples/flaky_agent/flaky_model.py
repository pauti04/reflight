"""A deliberately flaky scripted model: same task, seed-dependent behavior.

Seed % 3 picks the failure mode — deterministic per seed, so the demo fleet is
reproducible:

    0 → success:        search → calculate → correct answer
    1 → loop:           the same calculator call over and over
    2 → wrong tool args: calls web_search with {"q": ...} instead of {"query": ...}

This is the fixture every later phase demos against (classification here,
promote-to-test in Sprint 5, CI gates in Sprint 6).
"""

from __future__ import annotations

from typing import Any

from anthropic.types import Message


def _tool_use(name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "name": name, "input": tool_input}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _script_for(seed: int) -> list[dict]:
    mode = seed % 3
    if mode == 1:  # loop: stuck re-issuing the identical call
        stuck = _tool_use("calculator", {"expression": "37400068 / 2"})
        return [stuck, stuck, stuck, stuck, stuck, _text("I seem to be stuck. The answer is 42.")]
    if mode == 2:  # wrong tool args: schema says "query", model sends "q"
        bad = _tool_use("web_search", {"q": "population of Tokyo"})
        return [
            bad,
            bad,
            _text("I could not retrieve the population data, so I cannot answer."),
        ]
    return [  # success
        _tool_use("web_search", {"query": "population of Tokyo"}),
        _tool_use("calculator", {"expression": "37400068 / 2"}),
        _text(
            "Tokyo's metropolitan population is about 37,400,068 (2025 estimate). "
            "Divided by 2, that is 18,700,034."
        ),
    ]


class _FlakyMessages:
    def __init__(self, seed: int):
        self._seed = seed

    def create(self, **kwargs: Any) -> Message:
        messages = kwargs["messages"]
        n_assistant = sum(1 for m in messages if m["role"] == "assistant")
        script = _script_for(self._seed)
        step = script[min(n_assistant, len(script) - 1)]

        if step["type"] == "tool_use":
            content = [{**step, "id": f"toolu_flaky_{self._seed}_{n_assistant:03d}"}]
            stop_reason = "tool_use"
        else:
            content = [step]
            stop_reason = "end_turn"

        return Message.model_validate(
            {
                "id": f"msg_flaky_{self._seed}_{n_assistant:03d}",
                "type": "message",
                "role": "assistant",
                "model": kwargs.get("model", "claude-sonnet-5"),
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 130 + 12 * n_assistant, "output_tokens": 38},
            }
        )


class FlakyAnthropic:
    def __init__(self, seed: int):
        self.messages = _FlakyMessages(seed)
