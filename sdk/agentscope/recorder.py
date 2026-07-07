"""Record mode: pass every LLM call and tool call through to the real thing,
logging each request/response pair to the run's events.jsonl.

Two ways to instrument an agent:

1. Session facade (own-the-loop agents): pass a tools dict, call
   `session.messages.create(...)` and `session.execute(...)`.
2. Auto-instrumentation (existing agents, ≤3 added lines):
   `client = session.wrap(anthropic.Anthropic())` and `@session.tool` on each
   tool function. The agent code otherwise stays untouched.
"""

from __future__ import annotations

import functools
import inspect
from pathlib import Path
from typing import Any, Callable

from .events import RunLog, hash_payload, to_jsonable

ToolFn = Callable[..., str]


class _SessionMessages:
    def __init__(self, session: "Recorder"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)


class _WrappedClient:
    """Client-shaped facade so existing agent code keeps calling client.messages.create."""

    def __init__(self, session: Any):
        self.messages = session.messages


class Recorder:
    """The agent talks to this instead of the world; the world gets logged.

    The agent code is identical in record and replay mode — only the session
    object changes. That symmetry is what makes deterministic replay possible.
    """

    mode = "record"

    def __init__(
        self,
        run_dir: Path | str,
        live_client: Any = None,
        tools: dict[str, ToolFn] | None = None,
        db_path: Path | str | None = None,
    ):
        self.log = RunLog(run_dir)
        self._live = live_client
        self._tools = dict(tools or {})
        self._db_path = db_path
        self.messages = _SessionMessages(self)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._started = False
        self._ended = False

    # -- auto-instrumentation --------------------------------------------------

    def wrap(self, client: Any) -> _WrappedClient:
        """Wrap a live Anthropic client (or a zero-arg factory for one) so every
        messages.create() call is recorded. Returns a client-shaped object."""
        if callable(client) and not hasattr(client, "messages"):
            client = client()
        self._live = client
        return _WrappedClient(self)

    def tool(self, fn: ToolFn) -> ToolFn:
        """Decorator: record every call to fn — arguments, result, and errors.
        The wrapped function behaves exactly like fn (exceptions re-raise)."""
        name = fn.__name__
        self._tools[name] = fn
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result, _, exc = self._run_tool(name, dict(bound.arguments), f"direct_{self.log.seq}")
            if exc is not None:
                raise exc
            return result

        return wrapper

    # -- session lifecycle -------------------------------------------------------

    def start(self, task: str) -> None:
        if not self._started:
            self._started = True
            self.log.emit("run_start", task=task)

    def snapshot(self, label: str, state: Any) -> None:
        """Record a labeled snapshot of agent state (verified on replay)."""
        data = to_jsonable(state)
        self.log.emit("state_snapshot", label=label, state=data, state_hash=hash_payload(data))

    def record_error(self, exc: BaseException) -> None:
        self.log.emit("error", error_type=type(exc).__name__, message=str(exc))

    def end(self, status: str = "completed", final_text: str | None = None) -> None:
        if self._ended:
            return
        self._ended = True
        self.log.emit(
            "run_end",
            status=status,
            final_text=final_text,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
        )
        self.log.close()
        if self._db_path is not None:
            from .store import ingest_run

            ingest_run(self._db_path, self.log.run_dir)

    # -- calls -------------------------------------------------------------------

    def _llm_create(self, **kwargs: Any):
        if self._live is None:
            raise RuntimeError(
                "no live client: pass live_client= to Recorder or call session.wrap(...)"
            )
        request = to_jsonable(kwargs)
        response = self._live.messages.create(**kwargs)
        data = response.model_dump(mode="json")
        usage = data.get("usage") or {}
        self.total_input_tokens += usage.get("input_tokens") or 0
        self.total_output_tokens += usage.get("output_tokens") or 0
        self.log.emit(
            "llm_call",
            request=request,
            request_hash=hash_payload(request),
            response=data,
        )
        return response

    def _run_tool(
        self, name: str, tool_input: dict, tool_use_id: str
    ) -> tuple[str, bool, BaseException | None]:
        fn = self._tools.get(name)
        exc: BaseException | None = None
        if fn is None:
            result, is_error = f"UnknownTool: no tool named {name!r}", True
        else:
            try:
                result, is_error = fn(**tool_input), False
            except Exception as e:  # tool failures are data to record, not crashes
                exc, result, is_error = e, f"{type(e).__name__}: {e}", True
        self.log.emit(
            "tool_call",
            name=name,
            input=to_jsonable(tool_input),
            input_hash=hash_payload(tool_input),
            tool_use_id=tool_use_id,
            result=result,
            is_error=is_error,
        )
        return result, is_error, exc

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        """Dispatcher-style tool execution: errors come back as (message, True)."""
        result, is_error, _ = self._run_tool(name, tool_input, tool_use_id)
        return result, is_error
