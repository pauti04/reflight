#!/usr/bin/env python3
"""Sprint 0 formal close-out: record a run against a REAL nondeterministic API,
then replay it byte-identically with the network hard-blocked.

Uses the OpenAI-compatible path (any OPENAI_API_KEY works):

    OPENAI_API_KEY=... uv run --with openai python examples/live_api_check.py

Two sequential model calls where the second depends on the first's output —
so replay also proves ordering, not just caching.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import reflight

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "runs" / "live-openai"
DB = REPO_ROOT / "runs" / "reflight.db"
MODEL = "gpt-4o-mini"
TASK = "Two-step arithmetic via a real LLM API"


def agent(client) -> str:
    first = client.chat.completions.create(
        model=MODEL,
        max_tokens=30,
        messages=[
            {"role": "user", "content": "What is 37400068 divided by 2? Reply with only the number."}
        ],
    )
    half = first.choices[0].message.content.strip()
    second = client.chat.completions.create(
        model=MODEL,
        max_tokens=30,
        messages=[
            {"role": "user", "content": f"Add 1 to {half} and reply with only the number."}
        ],
    )
    return f"{half} → {second.choices[0].message.content.strip()}"


def main() -> int:
    from openai import OpenAI

    session = reflight.record(RUN_DIR, task=TASK, db_path=DB, agent_name="live-check")
    client = session.wrap_openai(OpenAI())
    live_answer = agent(client)
    session.end(final_text=live_answer)
    print(f"live   : {live_answer}  ({session.total_input_tokens}/{session.total_output_tokens} tok)")

    # hard-block the network, then replay the same agent code
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    socket.socket = _blocked  # type: ignore[misc]
    socket.create_connection = _blocked  # type: ignore[assignment]

    replay = reflight.replay(RUN_DIR)
    replayed_answer = agent(replay.wrap_openai())
    print(f"replay : {replayed_answer}  (network blocked, $0.00)")

    if replayed_answer != live_answer:
        print("✗ MISMATCH")
        return 1
    print("✓ byte-identical replay of a real API run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
