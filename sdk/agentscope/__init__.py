"""AgentScope — flight recorder for AI agents.

Record an agent run (every LLM call and tool call), replay it
deterministically, and query recorded runs by cost, status, and failure mode.

Quickstart — instrument an existing agent in 3 added lines:

    session = agentscope.record("runs/my-run", db_path="runs/agentscope.db")  # 1
    client = session.wrap(anthropic.Anthropic())                              # 2
    my_tool = session.tool(my_tool)                                           # 3 (or @session.tool)
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .events import RunLog, hash_payload, read_events, to_jsonable
from .fork import ForkSession
from .governor import Governor, GovernorKill
from .recorder import Recorder
from .replayer import ReplayDivergence, ReplayedToolError, Replayer

__all__ = [
    "Recorder",
    "Replayer",
    "ForkSession",
    "Governor",
    "GovernorKill",
    "ReplayDivergence",
    "ReplayedToolError",
    "RunLog",
    "read_events",
    "hash_payload",
    "to_jsonable",
    "record",
    "recording",
    "replay",
    "fork",
]


def record(
    run_dir: Path | str,
    task: str = "",
    client: Any = None,
    tools: dict | None = None,
    db_path: Path | str | None = None,
    governor: Any = None,
    agent_name: str | None = None,
) -> Recorder:
    """Create a recording session. Sugar over Recorder(...) + start()."""
    session = Recorder(
        run_dir, tools=tools, db_path=db_path, governor=governor, agent_name=agent_name
    )
    if client is not None:
        session.wrap(client)
    session.start(task)
    return session


@contextmanager
def recording(
    run_dir: Path | str,
    task: str = "",
    client: Any = None,
    tools: dict | None = None,
    db_path: Path | str | None = None,
):
    """Context-manager form of record(): crashes become error events and the
    run is always closed (and ingested into the DB) on exit."""
    session = record(run_dir, task=task, client=client, tools=tools, db_path=db_path)
    try:
        yield session
    except Exception as exc:
        session.record_error(exc)
        session.end(status="error", final_text=None)
        raise
    else:
        session.end()  # no-op if the agent already called session.end(...)


def replay(run_dir: Path | str, step: bool = False) -> Replayer:
    """Open a recorded run for deterministic replay."""
    return Replayer(run_dir, step=step)


def fork(
    run_dir: Path | str,
    at_seq: int,
    client: Any = None,
    tools: dict | None = None,
    out_dir: Path | str | None = None,
    db_path: Path | str | None = None,
) -> ForkSession:
    """Replay a recording up to at_seq, then go live — for testing a fix
    mid-run. The fork writes a complete new recording of its own."""
    session = ForkSession(
        run_dir, at_seq, live_client=None, tools=tools, out_dir=out_dir, db_path=db_path
    )
    if client is not None:
        session.wrap(client)
    session.start(session.task or "")
    return session
