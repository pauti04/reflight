#!/usr/bin/env python3
"""Sprint 0 example agent: record a run, replay it deterministically, verify.

  record  "task..."  [--offline] [--run-id ID]   run the agent live, recording everything
  replay  RUN_ID     [--step]                    re-run from the recording (no network)
  verify  RUN_ID                                 replay + assert byte-identical behavior
  runs                                           list recorded runs

The agent loop below is written by hand on purpose — owning the loop is what
lets the session facade (Recorder/Replayer) sit between the agent and the world.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from agentscope import Recorder, Replayer, read_events

from fake_model import FakeAnthropic
from tools import TOOL_SPECS, make_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
MODEL = "claude-sonnet-5"
SYSTEM = (
    "You are a meticulous research assistant. Use the tools to find facts and to do "
    "arithmetic — never guess numbers. When you have the answer, state it concisely."
)
MAX_TURNS = 10


def run_agent(session, task: str) -> tuple[str | None, str]:
    """The hand-written agent loop. Identical in record and replay mode."""
    session.start(task)
    messages: list[dict] = [{"role": "user", "content": task}]
    final_text: str | None = None
    status = "max_turns_exceeded"

    for _ in range(MAX_TURNS):
        response = session.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOL_SPECS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": list(response.content)})

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    result, is_error = session.execute(block.name, dict(block.input), block.id)
                    entry = {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    if is_error:
                        entry["is_error"] = True
                    results.append(entry)
            messages.append({"role": "user", "content": results})
        else:
            final_text = "".join(b.text for b in response.content if b.type == "text")
            status = "completed"
            break

    session.end(status=status, final_text=final_text)
    return final_text, status


def cmd_record(args: argparse.Namespace) -> int:
    if args.offline:
        live = FakeAnthropic()
    elif os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        live = anthropic.Anthropic()
    else:
        print("ANTHROPIC_API_KEY is not set. Export it, or use --offline for the scripted model.")
        return 2

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / run_id
    session = Recorder(run_dir, live, make_tools(run_dir / "notes"))

    t0 = time.perf_counter()
    final_text, status = run_agent(session, args.task)
    elapsed = time.perf_counter() - t0

    events = read_events(run_dir)
    print(f"run_id:  {run_id}   ({'offline scripted model' if args.offline else MODEL})")
    print(f"status:  {status}   events: {len(events)}   elapsed: {elapsed:.2f}s")
    print(f"tokens:  {session.total_input_tokens} in / {session.total_output_tokens} out")
    print(f"answer:  {final_text}")
    return 0


def _make_replayer(run_id: str, step: bool = False) -> Replayer:
    run_dir = RUNS_DIR / run_id
    if not (run_dir / "events.jsonl").exists():
        sys.exit(f"no recording at {run_dir}")
    # Belt and braces: replay must never need the network or a key.
    os.environ["ANTHROPIC_API_KEY"] = "disabled-during-replay"
    return Replayer(run_dir, step=step)


def cmd_replay(args: argparse.Namespace) -> int:
    session = _make_replayer(args.run_id, step=args.step)
    t0 = time.perf_counter()
    final_text, status = run_agent(session, session.task)
    elapsed = time.perf_counter() - t0

    print(f"\nreplayed {args.run_id}: {len(session.replay_log)} events, "
          f"{elapsed * 1000:.0f} ms, 0 API calls, $0.00")
    print(f"status:  {status}")
    print(f"answer:  {final_text}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    session = _make_replayer(args.run_id)
    recorded = read_events(RUNS_DIR / args.run_id)
    expected = [
        (e["type"], e.get("request_hash") or e.get("input_hash"))
        for e in recorded
        if e["type"] in ("llm_call", "tool_call")
    ]

    t0 = time.perf_counter()
    final_text, status = run_agent(session, session.task)
    elapsed = time.perf_counter() - t0

    checks = {
        "event sequence identical": session.replay_log == expected,
        "final answer identical": final_text == session.recorded_final_text,
        "status identical": status == session.recorded_status,
        "replay under 2s": elapsed < 2.0,
    }
    for label, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {label}")
    print(f"  ({len(expected)} events replayed in {elapsed * 1000:.0f} ms, 0 API calls)")

    if all(checks.values()):
        print(f"PASS: {args.run_id} replays deterministically")
        return 0
    print(f"FAIL: {args.run_id} diverged")
    return 1


def cmd_runs(_args: argparse.Namespace) -> int:
    if not RUNS_DIR.exists():
        print("no runs recorded yet")
        return 0
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not (run_dir / "events.jsonl").exists():
            continue
        events = read_events(run_dir)
        end = next((e for e in events if e["type"] == "run_end"), {})
        start = next((e for e in events if e["type"] == "run_start"), {})
        errors = sum(1 for e in events if e["type"] == "tool_call" and e["is_error"])
        flag = " ⚠" if errors else ""
        print(f"{run_dir.name}  [{end.get('status', '?')}]{flag}  "
              f"{len(events)} events  — {start.get('task', '')[:60]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="run the agent and record everything")
    p_record.add_argument("task")
    p_record.add_argument("--offline", action="store_true", help="use the scripted model (no API key)")
    p_record.add_argument("--run-id", default=None)
    p_record.set_defaults(fn=cmd_record)

    p_replay = sub.add_parser("replay", help="re-run a recorded run (no network)")
    p_replay.add_argument("run_id")
    p_replay.add_argument("--step", action="store_true", help="pause at each event")
    p_replay.set_defaults(fn=cmd_replay)

    p_verify = sub.add_parser("verify", help="replay and assert identical behavior")
    p_verify.add_argument("run_id")
    p_verify.set_defaults(fn=cmd_verify)

    p_runs = sub.add_parser("runs", help="list recorded runs")
    p_runs.set_defaults(fn=cmd_runs)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
