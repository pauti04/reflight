"""Event log primitives shared by the recorder and the replayer.

A run is a directory containing events.jsonl — one JSON event per line, in the
order they happened. Event types: run_start, llm_call, tool_call, run_end.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def to_jsonable(obj: Any) -> Any:
    """Recursively convert pydantic models (e.g. anthropic content blocks) to plain data."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_payload(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:16]


class RunLog:
    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "events.jsonl"
        self._fh = self.path.open("w", encoding="utf-8")
        self._seq = 0

    @property
    def seq(self) -> int:
        """The seq the next emitted event will get."""
        return self._seq

    def emit(self, event_type: str, **payload: Any) -> dict:
        event = {
            "seq": self._seq,
            "schema": SCHEMA_VERSION,
            "ts": time.time(),
            "type": event_type,
            **payload,
        }
        self._fh.write(json.dumps(to_jsonable(event), ensure_ascii=False) + "\n")
        self._fh.flush()
        self._seq += 1
        return event

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


def read_events(run_dir: Path | str) -> list[dict]:
    path = Path(run_dir) / "events.jsonl"
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
