"""Async sessions: the same record/replay facades for asyncio agents.

    session = reflight.record_async(run_dir, task=task)
    client = session.wrap(anthropic.AsyncAnthropic())
    response = await client.messages.create(...)
    result, is_error = await session.execute(name, args, tool_use_id)

The recording format is identical to sync sessions — a run recorded async
replays sync, and vice versa; the classifier, differ, and UI don't know the
difference. Tools may be sync or async functions (async tools are awaited).
Log writes themselves are synchronous file appends — microseconds, not worth
an executor hop.

Not yet async: fork mode and the `messages.stream()` helper (track NOTES.md).
"""

from __future__ import annotations

import functools
import inspect
from types import SimpleNamespace
from typing import Any, Callable

from .events import hash_payload
from .recorder import Recorder
from .replayer import Replayer, _reconstruct_error


class _AsyncSessionMessages:
    def __init__(self, session: "AsyncRecorder"):
        self._session = session

    async def create(self, **kwargs: Any):
        return await self._session._allm_create(**kwargs)


class _AsyncWrappedClient:
    def __init__(self, session: Any):
        self.messages = session.messages


class _AsyncOpenAICompletions:
    def __init__(self, session: "AsyncRecorder"):
        self._session = session

    async def create(self, **kwargs: Any):
        return await self._session._aopenai_create(**kwargs)


class _AsyncWrappedOpenAIClient:
    def __init__(self, session: "AsyncRecorder"):
        self.chat = SimpleNamespace(completions=_AsyncOpenAICompletions(session))


class AsyncRecorder(Recorder):
    """Recorder with an async facade. Same event log, awaited world."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.messages = _AsyncSessionMessages(self)

    def wrap(self, client: Any) -> _AsyncWrappedClient:
        """Wrap a live AsyncAnthropic client (or factory) for recording."""
        if callable(client) and not hasattr(client, "messages"):
            client = client()
        self._live = client
        return _AsyncWrappedClient(self)

    def wrap_openai(self, client: Any) -> _AsyncWrappedOpenAIClient:
        """Wrap a live AsyncOpenAI-compatible client for recording."""
        if callable(client) and not hasattr(client, "chat"):
            client = client()
        self._openai = client
        return _AsyncWrappedOpenAIClient(self)

    async def _allm_create(self, **kwargs: Any):
        self._pre_llm()
        from .flightcheck import session_io

        with session_io():
            response = await self._live.messages.create(**kwargs)
        self._emit_llm_call(kwargs, response.model_dump(mode="json"))
        return response

    async def _aopenai_create(self, **kwargs: Any):
        self._openai_pre()
        from .flightcheck import session_io

        with session_io():
            response = await self._openai.chat.completions.create(**kwargs)
        self._openai_emit(kwargs, response)
        return response

    async def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        result, is_error, _ = await self._arun_tool(name, tool_input, tool_use_id)
        return result, is_error

    async def _arun_tool(
        self, name: str, tool_input: dict, tool_use_id: str
    ) -> tuple[str, bool, BaseException | None]:
        input_hash = hash_payload(tool_input)
        cached = self._tool_pre(name, input_hash)
        exc: BaseException | None = None
        from_cache = cached is not None
        if from_cache:
            result, is_error = cached
        else:
            fn = self._tools.get(name)
            if fn is None:
                result, is_error = f"UnknownTool: no tool named {name!r}", True
            else:
                from .entropy import tool_scope

                try:
                    with tool_scope():
                        result = fn(**tool_input)
                        if inspect.isawaitable(result):
                            result = await result
                    is_error = False
                except Exception as e:  # tool failures are data to record, not crashes
                    exc, result, is_error = e, f"{type(e).__name__}: {e}", True
        self._tool_post(name, tool_input, input_hash, tool_use_id, result, is_error, from_cache)
        return result, is_error, exc

    def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator for sync or async tool functions; the wrapper is async."""
        name = fn.__name__
        self._tools[name] = fn
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result, _, exc = await self._arun_tool(
                name, dict(bound.arguments), f"direct_{self.log.seq}"
            )
            if exc is not None:
                raise exc
            return result

        return wrapper


class _AsyncReplayMessages:
    def __init__(self, session: "AsyncReplayer"):
        self._session = session

    async def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)  # matching is sync and instant


class _AsyncReplayOpenAICompletions:
    def __init__(self, session: "AsyncReplayer"):
        self._session = session

    async def create(self, **kwargs: Any):
        return self._session._openai_create(**kwargs)


class _AsyncReplayOpenAIClient:
    def __init__(self, session: "AsyncReplayer"):
        self.chat = SimpleNamespace(completions=_AsyncReplayOpenAICompletions(session))


class AsyncReplayer(Replayer):
    """Replayer with an async facade — same recordings, awaited access."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.messages = _AsyncReplayMessages(self)

    def wrap(self, client: Any = None) -> _AsyncWrappedClient:
        del client  # replay never touches the network
        return _AsyncWrappedClient(self)

    def wrap_openai(self, client: Any = None) -> _AsyncReplayOpenAIClient:
        del client
        return _AsyncReplayOpenAIClient(self)

    async def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        return Replayer.execute(self, name, tool_input, tool_use_id)

    def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Serve sync or async tool calls from the recording."""
        name = fn.__name__
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result, is_error = Replayer.execute(self, name, dict(bound.arguments), "direct")
            if is_error:
                raise _reconstruct_error(result)
            return result

        return wrapper
