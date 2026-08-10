"""Flight check: catch the I/O your recording won't contain.

Replay's guarantee covers exchanges that went *through the session* — a
`requests.get()` or DB call made directly from agent-loop code is invisible
to the recording and silently re-executes live on replay (docs/limits.md).
Documentation is passive; this is the active version:

    session = reflight.record(run_dir, ..., flight_check=True)

While recording, any network connection opened outside a session operation
(a live LLM call, a tool body, an MCP call) raises a Python warning AND
lands in the recording as a ``warning`` event — so the run is marked
`unrecorded_io` at ingest and the reliability scoreboard shows it. The
philosophy is the same as replay divergence: never let a gap be silent.

Scope notes: detection is per-thread (a tool spawning threads that do I/O
won't be flagged), and under asyncio, coroutines interleaved with a live
call may escape detection. False *positives* are not expected — legitimate
session I/O is scoped explicitly.
"""

from __future__ import annotations

import socket
import threading
import warnings
from typing import Any

_REAL_CONNECT = socket.socket.connect

_scope = threading.local()  # depth > 0 while inside legitimate session I/O
_watchers: list["FlightCheck"] = []
_lock = threading.Lock()


class session_io:
    """Recorder wraps its own live calls in this so they aren't flagged."""

    def __enter__(self) -> "session_io":
        _scope.depth = getattr(_scope, "depth", 0) + 1
        return self

    def __exit__(self, *exc: Any) -> None:
        _scope.depth -= 1


def _sanctioned() -> bool:
    from .entropy import _in_tool

    return getattr(_scope, "depth", 0) > 0 or _in_tool()


class FlightCheck:
    def __init__(self, session: Any):
        self._session = session
        self._seen: set[str] = set()

    def flag(self, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) and address else str(address)
        host = str(host)
        if host in self._seen:
            return
        self._seen.add(host)
        detail = (
            f"network connection to {host!r} outside the session — this I/O "
            "is not in the recording and will re-execute live on replay"
        )
        warnings.warn(f"reflight flight check: {detail}", stacklevel=4)
        try:
            self._session.log.emit("warning", kind="unrecorded_io", detail=detail, host=host)
        except ValueError:
            pass  # log already closed — the warning above still fired

    def uninstall(self) -> None:
        with _lock:
            if self in _watchers:
                _watchers.remove(self)
            if not _watchers:
                socket.socket.connect = _REAL_CONNECT


def _patched_connect(sock: socket.socket, address: Any):
    if not _sanctioned():
        with _lock:
            watchers = list(_watchers)
        for watcher in watchers:
            watcher.flag(address)
    return _REAL_CONNECT(sock, address)


def install(session: Any) -> FlightCheck:
    watcher = FlightCheck(session)
    with _lock:
        _watchers.append(watcher)
        socket.socket.connect = _patched_connect
    return watcher
