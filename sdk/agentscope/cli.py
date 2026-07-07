"""The `agentscope` command: query recorded runs.

    agentscope import [RUNS_DIR]     ingest run directories into the DB
    agentscope runs                  list runs (status, model, tokens, cost)
    agentscope show RUN_ID           event timeline for one run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import store


def _fmt_cost(cost: float | None) -> str:
    return f"${cost:.4f}" if cost is not None else "—"


def cmd_import(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"no such directory: {runs_dir}")
        return 1
    count = 0
    for run_dir in sorted(runs_dir.iterdir()):
        if not (run_dir / "events.jsonl").exists():
            continue
        info = store.ingest_run(args.db, run_dir)
        count += 1
        line = f"ingested {info['run_id']}  cost={_fmt_cost(info['cost_usd'])}"
        if info["problems"]:
            line += f"  ⚠ {len(info['problems'])} schema problems"
        print(line)
    print(f"{count} run(s) → {args.db}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    runs = store.list_runs(args.db)
    if not runs:
        print(f"no runs in {args.db} (try: agentscope import)")
        return 0
    for run in runs:
        errors = f" ⚠{run['tool_errors']}" if run["tool_errors"] else ""
        task = (run["task"] or "")[:50]
        print(
            f"{run['run_id']:24} [{run['status']}]{errors}  {run['model'] or '?':18} "
            f"{run['event_count']:3}ev  {run['input_tokens'] or 0}/{run['output_tokens'] or 0}tok  "
            f"{_fmt_cost(run['cost_usd']):>8}  — {task}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    events = store.get_events(args.db, args.run_id)
    if not events:
        print(f"no run {args.run_id!r} in {args.db}")
        return 1
    for event, cost in events:
        seq, event_type = event["seq"], event["type"]
        if event_type == "run_start":
            detail = f"task: {event['task']}"
        elif event_type == "llm_call":
            response = event["response"]
            usage = response.get("usage") or {}
            blocks = response.get("content", [])
            tools = [b["name"] for b in blocks if b.get("type") == "tool_use"]
            text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
            summary = f"tool_use: {', '.join(tools)}" if tools else text[:70].replace("\n", " ")
            detail = (
                f"{response.get('model')}  {usage.get('input_tokens', 0)}/"
                f"{usage.get('output_tokens', 0)}tok  {_fmt_cost(cost)}  → {summary}"
            )
        elif event_type == "tool_call":
            marker = " ⚠ ERROR" if event["is_error"] else ""
            detail = f"{event['name']}({event['input']}){marker} → {str(event['result'])[:60]}"
        elif event_type == "state_snapshot":
            detail = f"snapshot: {event['label']}"
        elif event_type == "error":
            detail = f"⚠ {event['error_type']}: {event['message']}"
        else:  # run_end
            detail = (
                f"status={event['status']}  {event['input_tokens']}/"
                f"{event['output_tokens']}tok total"
            )
        print(f"{seq:3}  {event_type:15} {detail}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    print(f"AgentScope API on http://{args.host}:{args.port}  (db: {args.db})")
    serve(args.db, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentscope", description=__doc__)
    parser.add_argument("--db", default="runs/agentscope.db", help="database path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="ingest run directories")
    p_import.add_argument("runs_dir", nargs="?", default="runs")
    p_import.set_defaults(fn=cmd_import)

    p_runs = sub.add_parser("runs", help="list recorded runs")
    p_runs.set_defaults(fn=cmd_runs)

    p_show = sub.add_parser("show", help="event timeline for one run")
    p_show.add_argument("run_id")
    p_show.set_defaults(fn=cmd_show)

    p_serve = sub.add_parser("serve", help="start the query API for the timeline UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8724)
    p_serve.set_defaults(fn=cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
