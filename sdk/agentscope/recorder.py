"""Record mode: pass every LLM call and tool call through to the real thing,
logging each request/response pair to the run's events.jsonl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .events import RunLog, hash_payload, to_jsonable

ToolFn = Callable[..., str]


class _RecordingMessages:
    def __init__(self, session: "Recorder"):
        self._session = session

    def create(self, **kwargs: Any):
        return self._session._llm_create(**kwargs)


class Recorder:
    """Session facade the agent talks to: .messages.create(...) and .execute(...).

    The agent code is identical in record and replay mode — only the session
    object changes. That symmetry is what makes deterministic replay possible.
    """

    mode = "record"

    def __init__(self, run_dir: Path | str, live_client: Any, tools: dict[str, ToolFn]):
        self.log = RunLog(run_dir)
        self._live = live_client
        self._tools = tools
        self.messages = _RecordingMessages(self)
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def start(self, task: str) -> None:
        self.log.emit("run_start", task=task)

    def _llm_create(self, **kwargs: Any):
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

    def execute(self, name: str, tool_input: dict, tool_use_id: str) -> tuple[str, bool]:
        fn = self._tools.get(name)
        if fn is None:
            result, is_error = f"UnknownTool: no tool named {name!r}", True
        else:
            try:
                result, is_error = fn(**tool_input), False
            except Exception as exc:  # tool failures are data to record, not crashes
                result, is_error = f"{type(exc).__name__}: {exc}", True
        self.log.emit(
            "tool_call",
            name=name,
            input=to_jsonable(tool_input),
            input_hash=hash_payload(tool_input),
            tool_use_id=tool_use_id,
            result=result,
            is_error=is_error,
        )
        return result, is_error

    def end(self, status: str, final_text: str | None) -> None:
        self.log.emit(
            "run_end",
            status=status,
            final_text=final_text,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
        )
        self.log.close()
