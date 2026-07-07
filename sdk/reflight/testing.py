"""Every failure becomes a regression test.

`promote()` turns a recorded run into an editable YAML test case. The runner
executes each test by **replaying** the agent against the test's recording —
fast, free, offline. Two paths lead to a live run:

- the agent's code/prompt changed → replay diverges → run live
- replay FAILS → the failure is re-verified live (the recording may pin stale
  model behavior; a model-side fix never shows up in replay)

So passing tests cost $0.00, and only failures (or behavior changes) spend
live tokens. A test promoted from a failure keeps failing while the bug
reproduces and passes once the agent — code or model — is actually fixed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from . import store
from .classify import FAIL, classify
from .events import read_events
from .pricing import cost_usd
from .recorder import Recorder
from .replayer import ReplayDivergence, Replayer

Agent = Callable[[Any, str], Any]  # agent(session, task)


# -- promote ---------------------------------------------------------------------


def promote(db_path: Path | str, run_id: str, tests_dir: Path | str = "agent_tests") -> Path:
    """One command: recorded run → editable regression test."""
    run = next((r for r in store.list_runs(db_path) if r["run_id"] == run_id), None)
    if run is None:
        raise ValueError(f"no run {run_id!r} in {db_path}")

    assertions: list[dict] = [{"type": "status", "equals": "completed"}, {"type": "no_findings"}]
    final_text = run["final_text"]
    if final_text and run["verdict"] == "pass":
        # regression pin: the agent must keep producing this exact answer
        assertions.append({"type": "final_text_equals", "value": final_text})
    elif final_text:
        # the recorded answer was wrong — never produce it again
        assertions.append({"type": "final_text_not_equals", "value": final_text})

    test = {
        "name": run_id,
        "source_run": run["run_dir"],
        "task": run["task"],
        "promoted_from_verdict": run["verdict"],
        "assertions": assertions,
        "judge": None,
    }

    tests_dir = Path(tests_dir)
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / f"{run_id}.yaml"
    header = (
        f"# Promoted from run {run_id!r} (verdict: {run['verdict']}).\n"
        "# Edit the assertions to state what SHOULD happen — e.g. add\n"
        '#   - type: final_text_contains\n#     value: "the correct answer"\n'
        "# Assertion types: status, no_findings, final_text_equals,\n"
        "# final_text_not_equals, final_text_contains, final_text_not_contains,\n"
        "# max_cost_usd.\n"
    )
    path.write_text(header + yaml.safe_dump(test, sort_keys=False, allow_unicode=True))
    return path


def load_test(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text())


# -- assertions --------------------------------------------------------------------


def _outcome(events: list[dict]) -> tuple[str | None, str | None, float | None]:
    end = next((e for e in events if e["type"] == "run_end"), None)
    cost = None
    for event in events:
        if event["type"] == "llm_call":
            c = cost_usd(event["response"].get("model"), event["response"].get("usage") or {})
            if c is not None:
                cost = (cost or 0.0) + c
    return (end["status"] if end else None, end["final_text"] if end else None, cost)


def check_assertions(test: dict, events: list[dict]) -> list[str]:
    status, final_text, cost = _outcome(events)
    final_text = final_text or ""
    findings = classify(events)
    failures = []
    for a in test.get("assertions") or []:
        kind = a["type"]
        if kind == "status" and status != a["equals"]:
            failures.append(f"status is {status!r}, expected {a['equals']!r}")
        elif kind == "no_findings":
            bad = [f.label for f in findings if f.severity == FAIL]
            if bad:
                failures.append(f"classifier findings: {', '.join(bad)}")
        elif kind == "final_text_equals" and final_text != a["value"]:
            failures.append(f"final answer changed: {final_text[:80]!r}")
        elif kind == "final_text_not_equals" and final_text == a["value"]:
            failures.append("final answer is the recorded-bad answer again")
        elif kind == "final_text_contains" and a["value"] not in final_text:
            failures.append(f"final answer does not contain {a['value']!r}")
        elif kind == "final_text_not_contains" and a["value"] in final_text:
            failures.append(f"final answer contains forbidden {a['value']!r}")
        elif kind == "max_cost_usd" and cost is not None and cost > a["value"]:
            failures.append(f"cost ${cost:.4f} exceeds ${a['value']}")
        elif kind not in (
            "status",
            "no_findings",
            "final_text_equals",
            "final_text_not_equals",
            "final_text_contains",
            "final_text_not_contains",
            "max_cost_usd",
        ):
            failures.append(f"unknown assertion type {kind!r}")
    return failures


# -- runner -----------------------------------------------------------------------


@dataclass
class TestResult:
    name: str
    passed: bool
    mode: str  # replay | live | diverged
    failures: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    seconds: float = 0.0

    def __str__(self) -> str:
        icon = "✓" if self.passed else "✗"
        cost = f", ${self.cost_usd:.4f}" if self.cost_usd else ", $0.00"
        line = f"{icon} {self.name}  ({self.mode}, {self.seconds * 1000:.0f}ms{cost})"
        for failure in self.failures:
            line += f"\n    · {failure}"
        return line


def _run_live(
    test: dict,
    agent: Agent,
    live_client_factory: Callable[[], Any],
    tools_factory: Callable[[Path], dict] | None,
    live_runs_dir: Path | str | None,
) -> tuple[list[dict], float | None]:
    parent = Path(live_runs_dir) if live_runs_dir else Path(test["source_run"]).parent
    run_dir = parent / f"{test['name']}-live-{int(time.time() * 1000)}"
    tools = tools_factory(run_dir) if tools_factory else {}
    session = Recorder(run_dir, live_client_factory(), tools)
    try:
        agent(session, test["task"])
    except Exception as agent_exc:
        session.record_error(agent_exc)
        session.end(status="error", final_text=None)
    events = read_events(run_dir)
    _, _, run_cost = _outcome(events)
    return events, run_cost


def run_test(
    test: dict,
    agent: Agent,
    live_client_factory: Callable[[], Any] | None = None,
    tools_factory: Callable[[Path], dict] | None = None,
    live_runs_dir: Path | str | None = None,
) -> TestResult:
    source = Path(test["source_run"])
    t0 = time.perf_counter()
    mode = "replay"
    run_cost: float | None = None
    try:
        session = Replayer(source)
        agent(session, test["task"])
        events = read_events(source)
    except ReplayDivergence as exc:
        if live_client_factory is None:
            return TestResult(
                test["name"],
                False,
                "diverged",
                [f"behavior changed since the recording and no live client was provided ({exc})"],
                None,
                time.perf_counter() - t0,
            )
        mode = "live"
        events, run_cost = _run_live(test, agent, live_client_factory, tools_factory, live_runs_dir)

    failures = check_assertions(test, events)

    # A replay failure proves the bug against *recorded* reality — but the
    # model may have changed since. Re-verify live before declaring failure.
    if failures and mode == "replay" and live_client_factory is not None:
        mode = "replay→live"
        events, run_cost = _run_live(test, agent, live_client_factory, tools_factory, live_runs_dir)
        failures = check_assertions(test, events)

    return TestResult(
        test["name"], not failures, mode, failures, run_cost, time.perf_counter() - t0
    )


def run_suite(
    tests_dir: Path | str,
    agent: Agent,
    live_client_factory: Callable[[], Any] | None = None,
    tools_factory: Callable[[Path], dict] | None = None,
    live_runs_dir: Path | str | None = None,
    quiet: bool = False,
) -> list[TestResult]:
    paths = sorted(Path(tests_dir).glob("*.yaml"))
    results = []
    for path in paths:
        result = run_test(
            load_test(path),
            agent,
            live_client_factory=live_client_factory,
            tools_factory=tools_factory,
            live_runs_dir=live_runs_dir,
        )
        results.append(result)
        if not quiet:
            print(result)
    if not quiet:
        passed = sum(r.passed for r in results)
        print(f"\n{passed}/{len(results)} passed")
    return results
