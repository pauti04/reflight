"""Entropy pinning: make time, randomness, and UUIDs part of the recording.

Replay serves LLM responses and tool results from the recording, but agent
code that consults ``time.time()``, ``random``, or ``uuid.uuid4()`` between
calls is still nondeterministic — a request that embeds a timestamp or a
generated id will hash differently on replay and diverge. ``session.pin()``
closes that gap:

    with session.pin():
        run_agent(session)

In record mode the pin captures every ``time.time()`` / ``time.time_ns()`` /
``uuid.uuid4()`` value the agent-loop code draws and seeds the global PRNG
with a recorded seed; the captured values land in a single ``entropy`` event.
In replay mode the same ``pin()`` serves those recorded values back in order
and re-seeds the PRNG identically, so entropy-dependent code takes the exact
path it took live. If replayed code draws *more* values than were recorded,
the pin raises ReplayDivergence instead of inventing data.

Tool bodies are deliberately not pinned — their results are already recorded
verbatim and tools never execute during replay — so capture is suspended
while a tool runs (see ``tool_scope``).

Known limits (see docs/limits.md): ``datetime.datetime.now`` is a C-level
attribute and cannot be patched — use ``time.time()`` in pinned code; the
PRNG seed pins the *global* ``random`` instance, so a tool that consumes it
during record can shift later draws — give tools their own ``random.Random``.
"""

from __future__ import annotations

import os
import random
import threading
import time
import uuid
from typing import Any

_REAL_TIME = time.time
_REAL_TIME_NS = time.time_ns
_REAL_UUID4 = uuid.uuid4

_tool_ctx = threading.local()


def _in_tool() -> bool:
    return getattr(_tool_ctx, "active", False)


class tool_scope:
    """The recorder wraps tool execution in this so in-tool entropy stays
    real and uncaptured (tool results are recorded whole; capturing their
    internal clock reads would desync the replay stream)."""

    def __enter__(self) -> "tool_scope":
        self._prev = _in_tool()
        _tool_ctx.active = True
        return self

    def __exit__(self, *exc: Any) -> None:
        _tool_ctx.active = self._prev


def _empty() -> dict:
    return {"seeds": [], "time": [], "time_ns": [], "uuid": []}


class _BasePin:
    def _install(self, on_time, on_time_ns, on_uuid4) -> None:
        time.time = on_time
        time.time_ns = on_time_ns
        uuid.uuid4 = on_uuid4

    def __exit__(self, *exc: Any) -> bool:
        time.time = _REAL_TIME
        time.time_ns = _REAL_TIME_NS
        uuid.uuid4 = _REAL_UUID4
        return False


class RecordPin(_BasePin):
    """Capture entropy during a recorded run (attaches to a Recorder)."""

    def __init__(self, session: Any):
        if getattr(session, "_entropy", None) is None:
            session._entropy = _empty()
        self._data = session._entropy

    def __enter__(self) -> "RecordPin":
        seed = os.urandom(8).hex()
        self._data["seeds"].append(seed)
        random.seed(seed)
        data = self._data

        def pinned_time() -> float:
            value = _REAL_TIME()
            if not _in_tool():
                data["time"].append(value)
            return value

        def pinned_time_ns() -> int:
            value = _REAL_TIME_NS()
            if not _in_tool():
                data["time_ns"].append(value)
            return value

        def pinned_uuid4() -> uuid.UUID:
            value = _REAL_UUID4()
            if not _in_tool():
                data["uuid"].append(str(value))
            return value

        self._install(pinned_time, pinned_time_ns, pinned_uuid4)
        return self


class ReplayPin(_BasePin):
    """Serve recorded entropy during replay (attaches to a Replayer)."""

    def __init__(self, session: Any):
        from .replayer import ReplayDivergence

        entropy = getattr(session, "_entropy_event", None)
        if entropy is None:
            raise ReplayDivergence(
                "this recording has no entropy event — it was recorded without "
                "session.pin(); record with the pin to replay entropy-dependent code"
            )
        self._entropy = entropy
        if getattr(session, "_entropy_cursors", None) is None:
            session._entropy_cursors = {"seeds": 0, "time": 0, "time_ns": 0, "uuid": 0}
        self._cursors = session._entropy_cursors

    def _draw(self, stream: str) -> Any:
        from .replayer import ReplayDivergence

        values = self._entropy.get(stream) or []
        index = self._cursors[stream]
        if index >= len(values):
            raise ReplayDivergence(
                f"agent drew more {stream} values than the recording holds "
                f"({len(values)}) — entropy-consuming code changed since this "
                "run was recorded"
            )
        self._cursors[stream] = index + 1
        return values[index]

    def __enter__(self) -> "ReplayPin":
        random.seed(self._draw("seeds"))
        self._install(
            lambda: self._draw("time"),
            lambda: self._draw("time_ns"),
            lambda: uuid.UUID(self._draw("uuid")),
        )
        return self


class ForkPin(_BasePin):
    """Serve the source recording's entropy while the fork replays its
    prefix; capture live entropy once past the fork point. Every value —
    served or live — is captured into the fork's own recording, so a fork
    remains a complete, replayable run."""

    def __init__(self, fork: Any):
        self._fork = fork
        recorder = fork._rec
        if getattr(recorder, "_entropy", None) is None:
            recorder._entropy = _empty()
        self._data = recorder._entropy
        source = next(
            (e for e in fork._events if e.get("type") == "entropy"), None
        )
        self._source = source or _empty()
        self._cursors = {"time": 0, "time_ns": 0, "uuid": 0}

    def _next(self, stream: str, real: Any) -> Any:
        values = self._source.get(stream) or []
        index = self._cursors[stream]
        if not self._fork.live and index < len(values):
            self._cursors[stream] = index + 1
            value = values[index]
        else:
            value = real()
            if stream == "uuid":
                value = str(value)
        self._data[stream].append(value)
        return value

    def __enter__(self) -> "ForkPin":
        seeds = self._source.get("seeds") or []
        seed = seeds[0] if seeds else os.urandom(8).hex()
        self._data["seeds"].append(seed)
        random.seed(seed)

        def pinned_time() -> float:
            if _in_tool():
                return _REAL_TIME()
            return self._next("time", _REAL_TIME)

        def pinned_time_ns() -> int:
            if _in_tool():
                return _REAL_TIME_NS()
            return self._next("time_ns", _REAL_TIME_NS)

        def pinned_uuid4() -> uuid.UUID:
            if _in_tool():
                return _REAL_UUID4()
            return uuid.UUID(self._next("uuid", _REAL_UUID4))

        self._install(pinned_time, pinned_time_ns, pinned_uuid4)
        return self
