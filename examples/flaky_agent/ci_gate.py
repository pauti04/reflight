#!/usr/bin/env python3
"""CI reliability gate: block the merge when the agent gets less reliable.

    python ci_gate.py                    gate against baseline.json (exit 1 on regression)
    python ci_gate.py --degrade          simulate the bad PR (model behaves worse)
    python ci_gate.py --update-baseline  re-measure and write a new baseline

Two checks, mirroring what a real team would wire up:
  1. promoted regression suite — a golden run is recorded, promoted, and run
     (replay-first; failures re-verify live)
  2. N-run consistency vs the checked-in baseline — pass-rate drops, new
     failure modes, and cost blowups all fail the gate

Writes a markdown report to $GITHUB_STEP_SUMMARY when present (the PR checks
page), plus a human-readable report on stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

import yaml
from flaky_model import FlakyAnthropic
from main import run_agent
from tools import make_tools

import reflight
from reflight.reliability import compare, load_baseline, measure, render, save_baseline
from reflight.testing import load_test, promote, run_test

TASK = "What is the population of Tokyo, and what is that number divided by 2?"
BASELINE = Path(__file__).parent / "baseline.json"
GOLDEN_ANSWER = "18,700,034"


def _agent(session, task):
    return run_agent(session, task)


def _suite_check(work: Path, offset: int):
    """Record a run with the current model, promote it, expect the golden answer."""
    db = work / "gate.db"
    run_dir = work / "golden-run"
    session = reflight.record(run_dir, task=TASK, db_path=db)
    session.wrap(FlakyAnthropic(0 + offset))
    session._tools.update(make_tools(run_dir / "notes"))
    run_agent(session, TASK)

    test_path = promote(db, "golden-run", tests_dir=work / "agent_tests")
    test = load_test(test_path)
    test["assertions"].append({"type": "final_text_contains", "value": GOLDEN_ANSWER})
    test_path.write_text(yaml.safe_dump(test, sort_keys=False, allow_unicode=True))

    return run_test(
        test,
        _agent,
        live_client_factory=lambda: FlakyAnthropic(0 + offset),
        tools_factory=lambda d: make_tools(d / "notes"),
        live_runs_dir=work / "live",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--degrade", action="store_true", help="simulate the bad PR")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args(argv)

    offset = 1 if args.degrade else 0
    work = Path(tempfile.mkdtemp(prefix="reflight-gate-"))

    report = measure(
        _agent,
        TASK,
        args.n,
        client_factory=lambda i: FlakyAnthropic(i + offset),
        tools_factory=lambda d: make_tools(d / "notes"),
        runs_root=work / "fleet",
    )

    if args.update_baseline:
        save_baseline(report, BASELINE)
        print(f"baseline updated → {BASELINE}")
        print(render(report))
        return 0

    suite_result = _suite_check(work, offset)
    regressions = compare(report, load_baseline(BASELINE))
    if not suite_result.passed:
        regressions.insert(0, f"promoted regression suite failed: {suite_result.failures}")

    ok = not regressions
    print("── promoted regression suite ─────────────")
    print(f"   {suite_result}")
    print("\n── consistency vs baseline ───────────────")
    print(render(report))
    print("\n" + ("✓ gate PASSED — no reliability regression" if ok else "✗ gate FAILED:"))
    for regression in regressions:
        print(f"  · {regression}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        icon = "✅" if ok else "❌"
        md = [
            f"## {icon} Agent reliability gate",
            "",
            f"**Promoted suite:** {'passed' if suite_result.passed else 'FAILED'} "
            f"({suite_result.mode})",
            f"**Pass rate:** {report.pass_rate:.0%} over {report.completed} runs "
            f"(baseline {load_baseline(BASELINE).pass_rate:.0%})",
            f"**Mean cost/run:** ${report.cost_mean:.4f}",
            "",
        ]
        if report.failure_histogram:
            md += ["| failure mode | count |", "|---|---|"] + [
                f"| {label} | {count} |"
                for label, count in sorted(report.failure_histogram.items())
            ]
        if regressions:
            md += ["", "### Regressions", *[f"- {r}" for r in regressions]]
        Path(summary_path).write_text("\n".join(md) + "\n")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
