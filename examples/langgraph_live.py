#!/usr/bin/env python3
"""Adapter validation against the real world: a LangGraph create_react_agent
running on real gpt-4o-mini, recorded by Reflight, then replayed byte-identically
with the network hard-blocked.

    OPENAI_API_KEY=... uv run python examples/langgraph_live.py
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

import reflight
from reflight.adapters.langchain import instrument

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "runs" / "langgraph-live"
DB = REPO_ROOT / "runs" / "reflight.db"
TASK = "Use the add tool to compute 20758 + 16642, then answer with just the number."


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def build_agent(session):
    kwargs = {} if session.mode == "record" else {"api_key": "replay-no-key-needed"}
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0, **kwargs)
    model, tools = instrument(session, model, [add])
    return create_react_agent(model, tools)


def main() -> int:
    session = reflight.record(RUN_DIR, task=TASK, db_path=DB, agent_name="langgraph-live")
    agent = build_agent(session)
    live = agent.invoke({"messages": [("user", TASK)]})["messages"][-1].content
    session.end(final_text=live)
    print(f"live   : {live!r}  ({session.total_input_tokens}/{session.total_output_tokens} tok)")

    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted during replay")

    socket.socket = _blocked  # type: ignore[misc]
    socket.create_connection = _blocked  # type: ignore[assignment]

    session = reflight.replay(RUN_DIR)
    agent = build_agent(session)
    replayed = agent.invoke({"messages": [("user", TASK)]})["messages"][-1].content
    print(f"replay : {replayed!r}  (network blocked, $0.00)")

    if replayed != live:
        print("✗ MISMATCH")
        return 1
    print("✓ a real LangGraph agent, recorded and replayed byte-identically")
    return 0


if __name__ == "__main__":
    sys.exit(main())
