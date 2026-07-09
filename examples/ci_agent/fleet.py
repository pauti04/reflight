#!/usr/bin/env python3
"""CI-triage agent fleet: investigate a red build, post a review.

Self-contained scenario (tools + scripted model + runner). Behaviors:

    pass        fetch log, read the right file, run tests, post review
    loop        reads a path that does not exist and retries it verbatim
    wrong_args  posts the review with `comment=` where the API wants `note=`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from anthropic.types import Message

import reflight
from reflight import store

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
DB = RUNS_DIR / "reflight.db"

PRS = [204, 211, 219, 226, 233, 240]
MODES = ["pass", "loop", "wrong_args", "pass", "loop", "wrong_args"]

GOOD_PATH = "src/payments/capture.py"
BAD_PATH = "services/payments/capture.py"

SYSTEM = (
    "You are a CI triage agent for the payments-service repo. Diagnose the "
    "failing test from the logs, verify against source, and post a review."
)

TOOL_SPECS = [
    {
        "name": "fetch_ci_log",
        "description": "Fetch the failing CI log for a pull request.",
        "input_schema": {
            "type": "object",
            "properties": {"pr_number": {"type": "integer"}},
            "required": ["pr_number"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a source file from the repository at HEAD.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_tests",
        "description": "Run a pytest target and return the summary.",
        "input_schema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    },
    {
        "name": "post_review",
        "description": "Post a review to the PR. Requires pr_number, verdict, note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer"},
                "verdict": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["pr_number", "verdict", "note"],
        },
    },
]


def make_tools() -> dict:
    def fetch_ci_log(pr_number: int) -> str:
        return (
            f"PR #{pr_number} · job payments-service/test · FAILED\n"
            "tests/payments/test_capture.py::test_capture_refund_idempotency\n"
            "AssertionError: duplicate capture recorded for idempotency key\n"
            f"  at {GOOD_PATH}:88 (missing idempotency check before insert)"
        )

    def read_file(path: str) -> str:
        if path != GOOD_PATH:
            raise FileNotFoundError(f"no such file: {path} — repo root is src/, not services/")
        return (
            "def capture(payment, key):\n"
            "    # BUG: no lookup on idempotency key before insert\n"
            "    ledger.insert(payment, key)\n"
        )

    def run_tests(target: str) -> str:
        return json.dumps({"target": target, "failed": 1, "passed": 41})

    def post_review(pr_number: int, verdict: str, note: str) -> str:
        return json.dumps({"pr": pr_number, "verdict": verdict, "posted": True, "note_len": len(note)})

    return {
        "fetch_ci_log": fetch_ci_log,
        "read_file": read_file,
        "run_tests": run_tests,
        "post_review": post_review,
    }


def _tool(name: str, tool_input: dict, lead: str | None = None) -> dict:
    return {"kind": "tool", "name": name, "input": tool_input, "lead": lead}


def _script(seed: int) -> list[dict]:
    mode = MODES[seed % len(MODES)]
    pr = PRS[seed % len(PRS)]
    log = _tool(
        "fetch_ci_log",
        {"pr_number": pr},
        lead=f"Pulling the failing log for PR #{pr}.",
    )
    if mode == "loop":
        bad = _tool("read_file", {"path": BAD_PATH})
        return [
            log,
            _tool(
                "read_file",
                {"path": BAD_PATH},
                lead="The trace points at the capture module. Reading it.",
            ),
            bad,
            bad,
            bad,
            {
                "kind": "final",
                "text": f"I found the failing test on PR #{pr} but could not open "
                "the capture module to verify the fix. Giving up.",
            },
        ]
    if mode == "wrong_args":
        wrong = _tool(
            "post_review",
            {
                "pr_number": pr,
                "verdict": "request_changes",
                "comment": "capture() inserts without checking the idempotency key.",
            },
        )
        return [
            log,
            _tool(
                "read_file",
                {"path": GOOD_PATH},
                lead="The trace points at capture(). Verifying against source.",
            ),
            _tool(
                "post_review",
                {
                    "pr_number": pr,
                    "verdict": "request_changes",
                    "comment": "capture() inserts without checking the idempotency key.",
                },
                lead="Confirmed: no idempotency lookup before insert. Posting the review.",
            ),
            wrong,
            {
                "kind": "final",
                "text": f"Diagnosed PR #{pr} (missing idempotency check in capture()) "
                "but the review API kept rejecting my request. Escalating.",
            },
        ]
    return [
        log,
        _tool(
            "read_file",
            {"path": GOOD_PATH},
            lead="The trace points at capture(). Verifying against source.",
        ),
        _tool("run_tests", {"target": "tests/payments"}),
        _tool(
            "post_review",
            {
                "pr_number": pr,
                "verdict": "request_changes",
                "note": "capture() inserts without checking the idempotency key first; "
                "add a ledger lookup on key before insert (see test_capture_refund_idempotency).",
            },
            lead="Confirmed the missing idempotency check. Posting the review.",
        ),
        {
            "kind": "final",
            "text": f"PR #{pr}: test_capture_refund_idempotency fails because capture() "
            "inserts without an idempotency lookup. Posted request_changes with the fix.",
        },
    ]


class CiAnthropic:
    def __init__(self, seed: int):
        self._seed = seed
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        n = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        script = _script(self._seed)
        step = script[min(n, len(script) - 1)]
        if step["kind"] == "tool":
            content: list[dict] = []
            if step.get("lead"):
                content.append({"type": "text", "text": step["lead"]})
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_ci_{self._seed}_{n:04d}",
                    "name": step["name"],
                    "input": step["input"],
                }
            )
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": step["text"]}]
            stop = "end_turn"
        return Message.model_validate(
            {
                "id": f"msg_ci_{self._seed}_{n:04d}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 310 + 40 * n, "output_tokens": 70},
            }
        )


def run_agent(session, task: str) -> None:
    messages: list[dict] = [{"role": "user", "content": task}]
    for _ in range(12):
        response = session.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOL_SPECS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            final = "".join(b.text for b in response.content if b.type == "text")
            session.end(status="completed", final_text=final)
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result, is_error = session.execute(block.name, dict(block.input), block.id)
                entry = {"type": "tool_result", "tool_use_id": block.id, "content": result}
                if is_error:
                    entry["is_error"] = True
                results.append(entry)
        messages.append({"role": "user", "content": results})
    session.end(status="max_turns_exceeded", final_text=None)


def main() -> int:
    for seed in range(len(MODES)):
        pr = PRS[seed % len(PRS)]
        task = (
            f"CI is red on PR #{pr} in payments-service. Find the failing test, "
            "diagnose the cause, and post a review."
        )
        session = reflight.record(
            RUNS_DIR / f"ci-{pr}",
            task=task,
            client=CiAnthropic(seed),
            tools=make_tools(),
            db_path=DB,
            agent_name="ci-triage-agent",
        )
        run_agent(session, task)

    for run in store.list_runs(DB):
        if run["run_id"].startswith("ci-"):
            print(f"{run['run_id']:10} {run['verdict']:6} {run['labels']}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
