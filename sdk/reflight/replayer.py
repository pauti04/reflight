"""Replay mode: serve every LLM response and tool result from a recording.

No network, no API key, no side effects. The replayer verifies at each step
that the agent is making the *same* requests it made during recording — if the
code or prompt changed, it raises ReplayDivergence instead of lying.
"""

from __future__ import annotations

import builtins
import functools
import inspect
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from anthropic.types import Message

from .events import hash_payload, read_events, to_jsonable


class ReplayDivergence(Exception):
    """The agent's behavior during replay no longer matches the recording."""


class ReplayedToolError(Exception):
    """A tool failure from the recording, re-raised during replay when the
    original exception type couldn't be reconstructed."""


def _reconstruct_error(recorded: str) -> BaseException:
    """Recorded tool errors look like 'ZeroDivisionError: division by zero'.
    Re-raise the real builtin exception type when possible so agent code that
    formats errors as f'{type(e).__name__}: {e}' reproduces the recording."""
    error_type, _, message = recorded.partition(": ")
    exc_class = getattr(builtins, error_type, None)
    if isinstance(exc_class, type) and issubclass(exc_class, BaseException):
        try:
            return exc_class(message)
        except Exception:
            pass
    return ReplayedToolError(recorded)


class _ReplayMessages:
    def __init__(self, session: "Replayer"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)

    def stream(self, **kwargs: Any):
        return self._session._llm_stream(**kwargs)


class _WrappedClient:
    def __init__(self, session: Any):
        self.messages = session.messages


class AttrView:
    """Read-only attribute view over recorded JSON, so replayed OpenAI-style
    responses support the same access patterns (resp.choices[0].message.content)
    without requiring the openai package."""

    def __init__(self, data: Any):
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if isinstance(data, dict) and name in data:
            return _view(data[name])
        raise AttributeError(name)

    def __getitem__(self, key: Any) -> Any:
        return _view(object.__getattribute__(self, "_data")[key])

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_data"))

    def __iter__(self):
        return (_view(item) for item in object.__getattribute__(self, "_data"))

    def __eq__(self, other: Any) -> bool:
        return object.__getattribute__(self, "_data") == (
            object.__getattribute__(other, "_data") if isinstance(other, AttrView) else other
        )

    def __repr__(self) -> str:
        return f"AttrView({object.__getattribute__(self, '_data')!r})"

    def model_dump(self, **_: Any) -> Any:
        return object.__getattribute__(self, "_data")


def _view(value: Any) -> Any:
    return AttrView(value) if isinstance(value, (dict, list)) else value


class _ReplayOpenAICompletions:
    def __init__(self, session: "Replayer"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._openai_create(**kwargs)

    @property
    def with_raw_response(self):
        from .recorder import _RawResponseShim

        return _RawResponseShim(self)


class _WrappedOpenAIClient:
    def __init__(self, session: "Replayer"):
        from types import SimpleNamespace

        self.chat = SimpleNamespace(completions=_ReplayOpenAICompletions(session))


class Replayer:
    mode = "replay"

    def __init__(self, run_dir: Path | str, step: bool = False):
        self.run_dir = Path(run_dir)
        self._events = read_events(self.run_dir)
        self._cursor = 0
        self._consumed: set[int] = set()
        self._match_lock = threading.Lock()
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

    # -- auto-instrumentation (mirror of Recorder) -----------------------------

    def wrap(self, client: Any = None) -> _WrappedClient:
        """Accepts and ignores a client/factory: replay never touches the network."""
        del client
        return _WrappedClient(self)

    def wrap_mcp(self, mcp_session: Any = None) -> "_ReplayMCP":
        """MCP facade served entirely from the recording (async, no server)."""
        del mcp_session
        return _ReplayMCP(self)

    def wrap_openai(self, client: Any = None) -> _WrappedOpenAIClient:
        """Accepts and ignores a client: replay never touches the network."""
        del client
        return _WrappedOpenAIClient(self)

    def _openai_create(self, **kwargs: Any) -> AttrView:
        event = self._next("llm_call")
        request_hash = hash_payload(to_jsonable(kwargs))
        if request_hash != event["request_hash"]:
            raise ReplayDivergence(
                f"LLM request at seq {event['seq']} differs from the recording "
                f"(hash {request_hash} != {event['request_hash']})."
            )
        if self.step:
            self._pause(event)
        self.replay_log.append(("llm_call", request_hash))
        return AttrView(event["response"])

    def tool(self, fn: Callable[..., str]) -> Callable[..., str]:
        """Decorator: serve fn's calls from the recording instead of running it."""
        name = fn.__name__
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result, is_error = self.execute(name, dict(bound.arguments), "direct")
            if is_error:
                raise _reconstruct_error(result)
            return result

        return wrapper

    # -- session facade -----------------------------------------------------------

    def start(self, task: str) -> None:
        pass  # nothing to record during replay

    def snapshot(self, label: str, state: Any) -> None:
        event = self._next("state_snapshot")
        state_hash = hash_payload(to_jsonable(state))
        if label != event["label"] or state_hash != event["state_hash"]:
            raise ReplayDivergence(
                f"state snapshot {label!r} at seq {event['seq']} diverged from the "
                f"recording (agent state changed since this run was recorded)"
            )
        self.replay_log.append(("state_snapshot", state_hash))

    def record_error(self, exc: BaseException) -> None:
        pass

    def end(self, status: str = "completed", final_text: str | None = None) -> None:
        self.replayed_status = status
        self.replayed_final_text = final_text

    def _match_llm(self, kwargs: dict) -> dict:
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
        return event

    def _llm_create(self, **kwargs: Any) -> Message:
        return Message.model_validate(self._match_llm(kwargs)["response"])

    def _llm_stream(self, **kwargs: Any):
        from .streaming import ReplayStream

        return ReplayStream(self._match_llm(kwargs))

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        """Tool calls match by tool_use_id within the current turn's tool block,
        so agents that execute a turn's tool calls concurrently replay correctly
        regardless of completion order. Falls back to (name, input) matching for
        synthesized ids (the @session.tool decorator path)."""
        input_hash = hash_payload(to_jsonable(tool_input))
        with self._match_lock:
            block = self._tool_block()
            if not block:
                event = self._next("tool_call")  # raises the right divergence message
                raise ReplayDivergence(  # pragma: no cover — _next always raises here
                    f"unexpected event at seq {event['seq']}"
                )
            event = None
            for idx in block:  # 1) exact id match (ids come from replayed responses)
                candidate = self._events[idx]
                if candidate["tool_use_id"] == tool_use_id:
                    if candidate["name"] != name or candidate["input_hash"] != input_hash:
                        raise ReplayDivergence(
                            f"tool call {tool_use_id} at seq {candidate['seq']} diverged: "
                            f"agent called {name}({tool_input!r}), recording has "
                            f"{candidate['name']}({candidate['input']!r})"
                        )
                    event = candidate
                    break
            if event is None:  # 2) fallback: same name + same arguments
                for idx in block:
                    candidate = self._events[idx]
                    if candidate["name"] == name and candidate["input_hash"] == input_hash:
                        event = candidate
                        idx_found = idx
                        break
                else:
                    first = self._events[block[0]]
                    recorded = [
                        (self._events[i]["name"], self._events[i]["tool_use_id"]) for i in block
                    ]
                    raise ReplayDivergence(
                        f"tool call at seq {first['seq']} diverged: agent called "
                        f"{name}({tool_input!r}), recording's pending tool calls are {recorded}"
                    )
                idx = idx_found
            self._consumed.add(idx)
            self.replay_log.append(("tool_call", input_hash))
        if self.step:
            self._pause(event)
        return event["result"], event["is_error"]

    # -- internals ------------------------------------------------------------------

    def _tool_block(self) -> list[int]:
        """Indices of the contiguous unconsumed tool_call events at the cursor —
        the current turn's parallel window. Stops at the next llm/snapshot event
        so ids can never match across turns."""
        block = []
        cursor = self._cursor
        while cursor < len(self._events):
            event = self._events[cursor]
            if cursor in self._consumed or event["type"] in ("run_start", "run_end", "error"):
                cursor += 1
                continue
            if event["type"] != "tool_call":
                break
            block.append(cursor)
            cursor += 1
        return block

    def _next(self, expected_type: str) -> dict:
        while self._cursor < len(self._events):
            index = self._cursor
            self._cursor += 1
            if index in self._consumed:
                continue
            event = self._events[index]
            if event["type"] in ("run_start", "run_end", "error"):
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


class _ReplayMCP:
    def __init__(self, session: "Replayer"):
        self._session = session

    async def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        result, is_error = self._session.execute(name, dict(arguments or {}), "mcp")
        if is_error and isinstance(result, str):
            raise _reconstruct_error(result)  # recorded transport failure
        return _view(result)  # isError results are data the agent saw, not exceptions
