"""Replay mode: serve every LLM response and tool result from a recording.

No network, no API key, no side effects. The replayer verifies at each step
that the agent is making the *same* requests it made during recording — if the
code or prompt changed, it raises ReplayDivergence instead of lying.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from anthropic.types import Message

from .events import hash_payload, read_events, to_jsonable


class ReplayDivergence(Exception):
    """The agent's behavior during replay no longer matches the recording."""


class _ReplayMessages:
    def __init__(self, session: "Replayer"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)


class Replayer:
    mode = "replay"

    def __init__(self, run_dir: Path | str, step: bool = False):
        self.run_dir = Path(run_dir)
        self._events = read_events(self.run_dir)
        self._cursor = 0
        self.step = step
        self.messages = _ReplayMessages(self)
        self.replay_log: list[tuple[str, str]] = []

        start = next((e for e in self._events if e["type"] == "run_start"), None)
        end = next((e for e in self._events if e["type"] == "run_end"), None)
        self.task: str | None = start["task"] if start else None
        self.recorded_status: str | None = end["status"] if end else None
        self.recorded_final_text: str | None = end["final_text"] if end else None
        self.replayed_status: str | None = None
        self.replayed_final_text: str | None = None

    # -- session facade ------------------------------------------------------

    def start(self, task: str) -> None:
        pass  # nothing to record during replay

    def end(self, status: str, final_text: str | None) -> None:
        self.replayed_status = status
        self.replayed_final_text = final_text

    def _llm_create(self, **kwargs: Any) -> Message:
        event = self._next("llm_call")
        request_hash = hash_payload(to_jsonable(kwargs))
        if request_hash != event["request_hash"]:
            raise ReplayDivergence(
                f"LLM request at seq {event['seq']} differs from the recording "
                f"(hash {request_hash} != {event['request_hash']}). The prompt, tools, "
                f"or params changed since this run was recorded."
            )
        if self.step:
            self._pause(event)
        self.replay_log.append(("llm_call", request_hash))
        return Message.model_validate(event["response"])

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        event = self._next("tool_call")
        input_hash = hash_payload(to_jsonable(tool_input))
        if name != event["name"] or input_hash != event["input_hash"]:
            raise ReplayDivergence(
                f"tool call at seq {event['seq']} diverged: agent called "
                f"{name}({tool_input!r}), recording has {event['name']}({event['input']!r})"
            )
        if self.step:
            self._pause(event)
        self.replay_log.append(("tool_call", input_hash))
        return event["result"], event["is_error"]

    # -- internals -----------------------------------------------------------

    def _next(self, expected_type: str) -> dict:
        while self._cursor < len(self._events):
            event = self._events[self._cursor]
            self._cursor += 1
            if event["type"] in ("run_start", "run_end"):
                continue
            if event["type"] != expected_type:
                raise ReplayDivergence(
                    f"agent asked for a {expected_type} but the recording has a "
                    f"{event['type']} at seq {event['seq']}"
                )
            return event
        raise ReplayDivergence(
            f"agent asked for a {expected_type} but the recording is exhausted"
        )

    def _pause(self, event: dict) -> None:
        print(f"\n─── seq {event['seq']} · {event['type']} " + "─" * 40)
        if event["type"] == "llm_call":
            response = event["response"]
            print(f"  model: {response.get('model')}   stop_reason: {response.get('stop_reason')}")
            for block in response.get("content", []):
                if block.get("type") == "text":
                    preview = block["text"][:200].replace("\n", " ")
                    print(f"  text: {preview}{'…' if len(block['text']) > 200 else ''}")
                elif block.get("type") == "tool_use":
                    print(f"  tool_use: {block['name']}({block['input']})")
        elif event["type"] == "tool_call":
            marker = " ⚠ ERROR" if event["is_error"] else ""
            preview = str(event["result"])[:200].replace("\n", " ")
            print(f"  {event['name']}({event['input']}){marker}")
            print(f"  → {preview}")
        if sys.stdin.isatty():
            input("  [Enter] next step ")
