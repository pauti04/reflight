"""Consistency scoring: one run tells you the agent CAN do a task; N runs tell
you whether it reliably DOES. Reports score consistency — pass rate, failure-
mode histogram, answer stability, cost spread — and baselines turn a report
into a regression gate: fail CI when reliability drops, new failure modes
appear, or cost balloons.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .classify import classify
from .classify import verdict as verdict_of
from .events import read_events
from .executor import _run_cost, run_repeated

Agent = Callable[[Any, str], Any]


@dataclass
class ConsistencyReport:
    task: str
    n: int
    completed: int
    passes: int
    pass_rate: float
    verdicts: dict[str, int] = field(default_factory=dict)
    failure_histogram: dict[str, int] = field(default_factory=dict)
    distinct_answers: int = 0
    cost_mean: float = 0.0
    cost_min: float = 0.0
    cost_max: float = 0.0
    cost_stdev: float = 0.0
    total_cost: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConsistencyReport":
        return cls(**data)


def analyze_runs(task: str, run_dirs: list[Path | str]) -> ConsistencyReport:
    verdicts: dict[str, int] = {}
    histogram: dict[str, int] = {}
    answers: set[str] = set()
    costs: list[float] = []

    for run_dir in run_dirs:
        events = read_events(run_dir)
        findings = classify(events)
        verdict = verdict_of(findings)
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        for finding in findings:
            histogram[finding.label] = histogram.get(finding.label, 0) + 1
        end = next((e for e in events if e["type"] == "run_end"), None)
        if end and end.get("final_text"):
            answers.add(end["final_text"])
        costs.append(_run_cost(events))

    n = len(run_dirs)
    passes = verdicts.get("pass", 0)
    return ConsistencyReport(
        task=task,
        n=n,
        completed=n,
        passes=passes,
        pass_rate=passes / n if n else 0.0,
        verdicts=verdicts,
        failure_histogram=histogram,
        distinct_answers=len(answers),
        cost_mean=statistics.mean(costs) if costs else 0.0,
        cost_min=min(costs, default=0.0),
        cost_max=max(costs, default=0.0),
        cost_stdev=statistics.stdev(costs) if len(costs) > 1 else 0.0,
        total_cost=sum(costs),
    )


def measure(
    agent: Agent,
    task: str,
    n: int,
    client_factory: Callable[[int], Any],
    tools_factory: Callable[[Path], dict],
    runs_root: Path | str,
    concurrency: int = 4,
    budget_usd: float | None = None,
    db_path: Path | str | None = None,
) -> ConsistencyReport:
    """Run the task n times and score consistency."""
    summary = run_repeated(
        agent,
        task,
        n,
        client_factory=client_factory,
        tools_factory=tools_factory,
        runs_root=runs_root,
        concurrency=concurrency,
        budget_usd=budget_usd,
        db_path=db_path,
    )
    run_dirs = [r["run_dir"] for r in summary["runs"] if not r["skipped"]]
    report = analyze_runs(task, run_dirs)
    report.completed = summary["completed"]
    return report


def render(report: ConsistencyReport) -> str:
    lines = [
        f"task:          {report.task}",
        f"runs:          {report.completed}/{report.n}",
        f"pass rate:     {report.pass_rate:.0%}  ({report.passes} pass, "
        f"{report.completed - report.passes} not)",
        f"answers:       {report.distinct_answers} distinct",
        f"cost/run:      ${report.cost_mean:.4f} mean  "
        f"(${report.cost_min:.4f}–${report.cost_max:.4f}, σ ${report.cost_stdev:.4f})",
        f"total cost:    ${report.total_cost:.4f}",
    ]
    if report.failure_histogram:
        lines.append("failure modes:")
        for label, count in sorted(report.failure_histogram.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {label:22} {'█' * count} {count}")
    return "\n".join(lines)


# -- baselines --------------------------------------------------------------------


def save_baseline(report: ConsistencyReport, path: Path | str) -> None:
    Path(path).write_text(json.dumps(report.to_dict(), indent=2) + "\n")


def load_baseline(path: Path | str) -> ConsistencyReport:
    return ConsistencyReport.from_dict(json.loads(Path(path).read_text()))


def compare(
    report: ConsistencyReport,
    baseline: ConsistencyReport,
    max_pass_rate_drop: float = 0.0,
    max_cost_increase: float = 0.5,
) -> list[str]:
    """Regressions in `report` relative to `baseline` (empty = no regression)."""
    regressions = []
    if report.pass_rate < baseline.pass_rate - max_pass_rate_drop:
        regressions.append(
            f"pass rate dropped {baseline.pass_rate:.0%} → {report.pass_rate:.0%}"
        )
    new_modes = set(report.failure_histogram) - set(baseline.failure_histogram)
    if new_modes:
        regressions.append(f"new failure mode(s): {', '.join(sorted(new_modes))}")
    if baseline.cost_mean > 0 and report.cost_mean > baseline.cost_mean * (1 + max_cost_increase):
        regressions.append(
            f"mean cost/run grew ${baseline.cost_mean:.4f} → ${report.cost_mean:.4f} "
            f"(> {max_cost_increase:.0%} tolerance)"
        )
    return regressions
