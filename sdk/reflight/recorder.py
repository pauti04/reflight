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


class _OpenAICompletions:
    def __init__(self, session: Any):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._openai_create(**kwargs)


class _WrappedOpenAIClient:
    """OpenAI-shaped facade: client.chat.completions.create(...)."""

    def __init__(self, session: Any):
        from types import SimpleNamespace

        self.chat = SimpleNamespace(completions=_OpenAICompletions(session))


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
        governor: Any = None,
        agent_name: str | None = None,
    ):
        self.log = RunLog(run_dir)
        self._live = live_client
        self._openai: Any = None
        self._tools = dict(tools or {})
        self._db_path = db_path
        self._governor = governor
        self.agent_name = agent_name
        self.messages = _SessionMessages(self)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
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

    def wrap_openai(self, client: Any) -> _WrappedOpenAIClient:
        """Wrap an OpenAI-compatible client so chat.completions.create is recorded."""
        if callable(client) and not hasattr(client, "chat"):
            client = client()
        self._openai = client
        return _WrappedOpenAIClient(self)

    def _openai_create(self, **kwargs: Any):
        if self._governor is not None:
            from .governor import GovernorKill

            try:
                self._governor.before_llm(self)
            except GovernorKill as kill:
                self._kill(kill)
                raise
        if self._openai is None:
            raise RuntimeError("no OpenAI client: call session.wrap_openai(client) first")
        request = to_jsonable(kwargs)
        response = self._openai.chat.completions.create(**kwargs)
        data = response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)
        usage = data.get("usage") or {}
        self.total_input_tokens += usage.get("prompt_tokens") or 0
        self.total_output_tokens += usage.get("completion_tokens") or 0
        self.log.emit(
            "llm_call",
            provider="openai",
            request=request,
            request_hash=hash_payload(request),
            response=data,
        )
        return response

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
            if self.agent_name:
                self.log.emit("run_start", task=task, agent=self.agent_name)
            else:
                self.log.emit("run_start", task=task)

    def _kill(self, kill: BaseException) -> None:
        """Record the governor's intervention, close the run, let the kill propagate."""
        self.record_error(kill)
        self.end(status="killed", final_text=None)

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
        if self._governor is not None:
            from .governor import GovernorKill

            try:
                self._governor.before_llm(self)
            except GovernorKill as kill:
                self._kill(kill)
                raise
        request = to_jsonable(kwargs)
        response = self._live.messages.create(**kwargs)
        data = response.model_dump(mode="json")
        usage = data.get("usage") or {}
        self.total_input_tokens += usage.get("input_tokens") or 0
        self.total_output_tokens += usage.get("output_tokens") or 0
        from .pricing import cost_usd

        call_cost = cost_usd(data.get("model"), usage)
        if call_cost is not None:
            self.total_cost_usd += call_cost
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
        input_hash = hash_payload(tool_input)
        cached = None
        if self._governor is not None:
            from .governor import GovernorKill

            try:
                cached = self._governor.before_tool(name, input_hash)
            except GovernorKill as kill:
                self._kill(kill)
                raise
        exc: BaseException | None = None
        from_cache = cached is not None
        if from_cache:
            result, is_error = cached
        else:
            fn = self._tools.get(name)
            if fn is None:
                result, is_error = f"UnknownTool: no tool named {name!r}", True
            else:
                try:
                    result, is_error = fn(**tool_input), False
                except Exception as e:  # tool failures are data to record, not crashes
                    exc, result, is_error = e, f"{type(e).__name__}: {e}", True
            if self._governor is not None:
                self._governor.after_tool(name, input_hash, result, is_error)
        self.log.emit(
            "tool_call",
            name=name,
            input=to_jsonable(tool_input),
            input_hash=input_hash,
            tool_use_id=tool_use_id,
            result=result,
            is_error=is_error,
            **({"cached": True} if from_cache else {}),
        )
        return result, is_error, exc

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        """Dispatcher-style tool execution: errors come back as (message, True)."""
        result, is_error, _ = self._run_tool(name, tool_input, tool_use_id)
        return result, is_error
