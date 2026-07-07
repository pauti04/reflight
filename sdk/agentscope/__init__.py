"""AgentScope — flight recorder for AI agents (Sprint 0 spike).

Record an agent run (every LLM call and tool call), then replay it
deterministically: same code path, all external I/O served from the recording.
"""

from .events import RunLog, hash_payload, read_events, to_jsonable
from .recorder import Recorder
from .replayer import ReplayDivergence, Replayer

__all__ = [
    "Recorder",
    "Replayer",
    "ReplayDivergence",
    "RunLog",
    "read_events",
    "hash_payload",
    "to_jsonable",
]
