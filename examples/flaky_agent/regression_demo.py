#!/usr/bin/env python3
"""Milestone demo #3 (early): every failure becomes a regression test.

    1. the agent fails a task (loop → invents "42")
    2. one command promotes the failed run into a test
    3. the test FAILS while the bug exists (via free, offline replay)
    4. we fix the agent → replay diverges → runner goes live → test PASSES
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

import yaml
from flaky_model import FlakyAnthropic
from main import run_agent
from tools import make_tools

import reflight
from reflight.testing import load_test, promote, run_test

BUGGY_SEED, FIXED_SEED = 1, 0
TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="reflight-demo-"))
    db = work / "reflight.db"

    print("── 1. the agent fails ─────────────────────────────────")
    run_dir = work / "nightly-run"
    session = reflight.record(run_dir, task=TASK, db_path=db)
    session.wrap(FlakyAnthropic(BUGGY_SEED))
    session._tools.update(make_tools(run_dir / "notes"))
    final_text, _ = run_agent(session, TASK)
    print(f"   agent answered: {final_text!r}   ← wrong\n")

    print("── 2. promote the failure to a test ──────────────────")
    test_path = promote(db, "nightly-run", tests_dir=work / "agent_tests")
    print(f"   $ reflight promote nightly-run\n   → {test_path.name}")

    test = load_test(test_path)  # "edit the assertions": state the right answer
    test["assertions"].append({"type": "final_text_contains", "value": "18,700,034"})
    test_path.write_text(yaml.safe_dump(test, sort_keys=False, allow_unicode=True))
    print('   (edited: + final_text_contains "18,700,034")\n')

    def agent(session, task):
        return run_agent(session, task)

    print("── 3. bug present → replay reproduces it, live confirms → FAIL ──")
    result = run_test(test, agent, live_client_factory=lambda: FlakyAnthropic(BUGGY_SEED),
                      tools_factory=lambda d: make_tools(d / "notes"))
    print(f"   {result}\n")
    failed_while_buggy = not result.passed

    print("── 4. model fixed → replay flags it, live re-verify → PASS ─────")
    result = run_test(test, agent, live_client_factory=lambda: FlakyAnthropic(FIXED_SEED),
                      tools_factory=lambda d: make_tools(d / "notes"))
    print(f"   {result}\n")

    if failed_while_buggy and result.passed:
        print("regression loop closed: fail → promote → fix → pass ✓")
        return 0
    print("demo did not behave as expected")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
