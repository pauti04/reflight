"""Streaming record/replay: the `messages.stream()` helper pattern.

Covers the dominant streaming idiom — context manager + `.text_stream` +
`.get_final_message()`. What the agent observes (the chunk sequence and the
final message) is exactly what gets recorded, so replay is faithful down to
chunk boundaries. Raw event iteration (`create(stream=True)`) and OpenAI chat
streaming remain open — tracked in NOTES.md.
"""

from __future__ import annotations

from typing import Any

from anthropic.types import Message


class RecordingStream:
    """Mirrors anthropic's MessageStreamManager while capturing what the agent saw."""

    def __init__(self, session: Any, kwargs: dict):
        self._session = session
        self._kwargs = kwargs
        self._chunks: list[str] = []
        self._final: Message | None = None

    def __enter__(self) -> "RecordingStream":
        self._manager = self._session._live.messages.stream(**self._kwargs)
        self._inner = self._manager.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.get_final_message()  # capture + emit even if the agent didn't ask
        return self._manager.__exit__(exc_type, exc, tb)

    @property
    def text_stream(self):
        for text in self._inner.text_stream:
            self._chunks.append(text)
            yield text

    def get_final_message(self) -> Message:
        if self._final is None:
            self._final = self._inner.get_final_message()
            self._session._emit_llm_call(
                self._kwargs,
                self._final.model_dump(mode="json"),
                stream_chunks=list(self._chunks),
            )
        return self._final


class ReplayStream:
    """Serves a recorded stream: same chunks, same final message, no network."""

    def __init__(self, event: dict):
        self._event = event

    def __enter__(self) -> "ReplayStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def text_stream(self):
        stream = self._event.get("stream") or {}
        chunks = stream.get("text_chunks")
        if chunks is None:
            # the recording was made non-streaming: one chunk per text block —
            # same text, coarser boundaries
            chunks = [
                block["text"]
                for block in self._event["response"].get("content", [])
                if block.get("type") == "text"
            ]
        yield from chunks

    def get_final_message(self) -> Message:
        return Message.model_validate(self._event["response"])
