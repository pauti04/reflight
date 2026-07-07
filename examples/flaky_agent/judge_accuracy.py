#!/usr/bin/env python3
"""Sprint 4 close-out: judge accuracy against runs with known ground truth.

The flaky fleet's failure modes are seeded, so ground truth is free: seeds
0,3,6,9 genuinely succeed; 1,4,7 loop and invent an answer; 2,5,8 never get
the data. A real LLM judges each transcript blind; we score agreement.

    OPENAI_API_KEY=... uv run --with openai python examples/flaky_agent/judge_accuracy.py

Works through an adapter so the anthropic-shaped judge_run() drives an
OpenAI-compatible model (any provider with OPENAI_API_KEY works).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research_agent"))

from flaky_model import FlakyAnthropic
from main import run_agent
from tools import make_tools

import reflight
from reflight import read_events
from reflight.judge import judge_run

JUDGE_MODEL = "gpt-4o-mini"
TASK = "What is the population of Tokyo, and what is that number divided by 2?"
N = 12  # 4 of each ground-truth class


class OpenAIJudgeAdapter:
    """Quacks like anthropic .messages.create, speaks chat.completions."""

    def __init__(self, client, model: str = JUDGE_MODEL):
        self._client = client
        self._model = model
        self.messages = self

    def create(self, **kwargs):
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", 512),
            messages=[
                {"role": "system", "content": kwargs["system"]},
                *kwargs["messages"],
            ],
        )
        text = response.choices[0].message.content
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def main() -> int:
    from openai import OpenAI

    adapter = OpenAIJudgeAdapter(OpenAI())
    work = Path(__file__).resolve().parents[2] / "runs" / "judge-eval"

    correct = 0
    print(f"{'run':10} {'truth':6} {'judge':14} verdict")
    for seed in range(N):
        run_dir = work / f"seed-{seed:02d}"
        if not (run_dir / "events.jsonl").exists():
            session = reflight.record(run_dir, task=TASK)
            session.wrap(FlakyAnthropic(seed))
            session._tools.update(make_tools(run_dir / "notes"))
            run_agent(session, TASK)

        truth_ok = seed % 3 == 0
        result = judge_run(read_events(run_dir), adapter, model=JUDGE_MODEL)
        agree = result["ok"] == truth_ok
        correct += agree
        print(
            f"seed-{seed:02d}    {'ok' if truth_ok else 'fail':6} "
            f"{result['label']:14} {'✓' if agree else '✗ DISAGREE'}"
        )

    accuracy = correct / N
    print(f"\njudge accuracy vs seeded ground truth: {correct}/{N} = {accuracy:.0%}")
    return 0 if accuracy >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
