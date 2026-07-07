"""Fork mode: replay a recording up to a chosen event, then go live.

The use case is testing a fix mid-run: replay the cheap, deterministic prefix,
then let the (fixed) agent take over from the exact moment things went wrong.

A fork writes a complete new recording — the replayed prefix is re-emitted
into it, the live suffix is recorded as usual. So a fork is itself a run:
ingestable, replayable, and diffable against the original to show exactly
what the fix changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from anthropic.types import Message

from .events import hash_payload, read_events, to_jsonable
from .recorder import Recorder, _WrappedClient
from .replayer import ReplayDivergence


class _ForkMessages:
    def __init__(self, session: "ForkSession"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)

    def stream(self, **kwargs: Any):
        return self._session._llm_stream(**kwargs)


class ForkSession:
    """Session facade: recorded events with seq < at_seq are served from the
    source recording; everything from at_seq onward runs live."""

    mode = "fork"

    def __init__(
        self,
        source_dir: Path | str,
        at_seq: int,
        live_client: Any = None,
        tools: dict[str, Callable[..., str]] | None = None,
        out_dir: Path | str | None = None,
        db_path: Path | str | None = None,
    ):
        self.source_dir = Path(source_dir)
        self.at_seq = at_seq
        self._events = read_events(self.source_dir)
        self._cursor = 0
        self.live = False

        if out_dir is None:
            out_dir = self.source_dir.parent / f"{self.source_dir.name}-fork{at_seq}"
        self.run_dir = Path(out_dir)
        self._rec = Recorder(self.run_dir, live_client, tools, db_path=db_path)
        self.messages = _ForkMessages(self)

        start = next((e for e in self._events if e["type"] == "run_start"), None)
        self.task: str | None = start["task"] if start else None

    # -- auto-instrumentation (mirror of Recorder/Replayer) ---------------------

    def wrap(self, client: Any) -> _WrappedClient:
        if callable(client) and not hasattr(client, "messages"):
            client = client()
        self._rec._live = client
        return _WrappedClient(self)

    def tool(self, fn: Callable[..., str]) -> Callable[..., str]:
        import functools
        import inspect

        name = fn.__name__
        self._rec._tools[name] = fn
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result, is_error = self.execute(name, dict(bound.arguments), "direct")
            if is_error:
                from .replayer import _reconstruct_error

                raise _reconstruct_error(result)
            return result

        return wrapper

    # -- session lifecycle --------------------------------------------------------

    def start(self, task: str) -> None:
        self._rec.start(task)

    def snapshot(self, label: str, state: Any) -> None:
        self._rec.snapshot(label, state)

    def record_error(self, exc: BaseException) -> None:
        self._rec.record_error(exc)

    def end(self, status: str = "completed", final_text: str | None = None) -> None:
        self._rec.end(status=status, final_text=final_text)

    # -- calls ---------------------------------------------------------------------

    def _peek(self, expected_type: str) -> dict | None:
        """Next recorded event of interest, or None once past the fork point."""
        cursor = self._cursor
        while cursor < len(self._events):
            event = self._events[cursor]
            if event["type"] in ("run_start", "run_end", "error"):
                cursor += 1
                continue
            if event["seq"] >= self.at_seq:
                return None  # reached the fork point
            if event["type"] != expected_type:
                raise ReplayDivergence(
                    f"agent asked for a {expected_type} but the recording has a "
                    f"{event['type']} at seq {event['seq']} (before the fork point)"
                )
            self._cursor = cursor + 1
            return event
        return None  # recording exhausted — continue live

    def _match_prefix_llm(self, kwargs: dict) -> dict | None:
        """Verify + re-emit the next recorded llm_call; None once past the fork."""
        event = self._peek("llm_call")
        if event is None:
            self.live = True
            return None
        request_hash = hash_payload(to_jsonable(kwargs))
        if request_hash != event["request_hash"]:
            raise ReplayDivergence(
                f"LLM request at seq {event['seq']} differs from the recording, "
                f"which is before the fork point (seq {self.at_seq}) — the fix "
                "changed behavior earlier than expected; fork at an earlier seq"
            )
        # re-emit the recorded exchange into the fork's own log
        response_data = event["response"]
        usage = response_data.get("usage") or {}
        self._rec.total_input_tokens += usage.get("input_tokens") or 0
        self._rec.total_output_tokens += usage.get("output_tokens") or 0
        extra = {"stream": event["stream"]} if "stream" in event else {}
        self._rec.log.emit(
            "llm_call",
            request=event["request"],
            request_hash=event["request_hash"],
            response=response_data,
            **extra,
        )
        return event

    def _llm_create(self, **kwargs: Any):
        if not self.live:
            event = self._match_prefix_llm(kwargs)
            if event is not None:
                return Message.model_validate(event["response"])
        return self._rec._llm_create(**kwargs)

    def _llm_stream(self, **kwargs: Any):
        if not self.live:
            event = self._match_prefix_llm(kwargs)
            if event is not None:
                from .streaming import ReplayStream

                return ReplayStream(event)
        return self._rec._llm_stream(**kwargs)

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        if not self.live:
            event = self._peek("tool_call")
            if event is None:
                self.live = True
            else:
                input_hash = hash_payload(to_jsonable(tool_input))
                if name != event["name"] or input_hash != event["input_hash"]:
                    raise ReplayDivergence(
                        f"tool call at seq {event['seq']} diverged before the fork "
                        f"point (seq {self.at_seq}) — fork at an earlier seq"
                    )
                self._rec.log.emit(
                    "tool_call",
                    name=event["name"],
                    input=event["input"],
                    input_hash=event["input_hash"],
                    tool_use_id=event["tool_use_id"],
                    result=event["result"],
                    is_error=event["is_error"],
                )
                return event["result"], event["is_error"]
        return self._rec.execute(name, tool_input, tool_use_id)
