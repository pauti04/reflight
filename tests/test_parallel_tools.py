"""Sprint 10: parallel tool-call replay — matching by tool_use_id, not order."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from anthropic.types import Message

import reflight
from reflight import ReplayDivergence, read_events, schema

TASK = "Compute three sums."

CALLS = [
    ("toolu_par_a", {"expression": "1 + 1"}),
    ("toolu_par_b", {"expression": "2 + 2"}),
    ("toolu_par_c", {"expression": "3 + 3"}),
]


class ParallelFakeAnthropic:
    """Turn 0: three tool_use blocks in ONE assistant message. Turn 1: final text."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        n_assistant = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        if n_assistant == 0:
            content = [
                {"type": "tool_use", "id": tid, "name": "calculator", "input": inp}
                for tid, inp in CALLS
            ]
            stop_reason = "tool_use"
        else:
            content = [{"type": "text", "text": "The sums are 2, 4, and 6."}]
            stop_reason = "end_turn"
        return Message.model_validate(
            {
                "id": f"msg_par_{n_assistant:03d}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 40},
            }
        )


def calculator(expression: str) -> str:
    return str(eval(expression))  # noqa: S307 — test-only arithmetic


def parallel_agent(session, task, order="in_order"):
    """Executes a turn's tool calls concurrently (or in a scrambled order), but
    assembles tool_result blocks in the model's block order — as a correct
    parallel agent must, to keep requests deterministic."""
    messages = [{"role": "user", "content": task}]
    for _ in range(4):
        response = session.messages.create(
            model="claude-sonnet-5", max_tokens=1024, messages=messages
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        blocks = [b for b in response.content if b.type == "tool_use"]

        def run_one(block):
            result, is_error = session.execute(block.name, dict(block.input), block.id)
            return block.id, result

        if order == "threads":
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = dict(pool.map(run_one, blocks))
        elif order == "reversed":
            results = dict(run_one(b) for b in reversed(blocks))
        else:
            results = dict(run_one(b) for b in blocks)

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": results[b.id]}
                    for b in blocks  # block order, not completion order
                ],
            }
        )
    return None


def _record(tmp_path, order="in_order"):
    run_dir = tmp_path / "run"
    session = reflight.record(
        run_dir, task=TASK, client=ParallelFakeAnthropic(), tools={"calculator": calculator}
    )
    text = parallel_agent(session, TASK, order=order)
    session.end(final_text=text)
    return run_dir, text


def test_threaded_recording_is_wellformed(tmp_path):
    run_dir, text = _record(tmp_path, order="threads")
    assert text == "The sums are 2, 4, and 6."
    events = read_events(run_dir)
    assert schema.validate_run(events) == []  # seqs contiguous despite threads
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert {e["tool_use_id"] for e in tool_events} == {tid for tid, _ in CALLS}


@pytest.mark.parametrize("replay_order", ["in_order", "reversed", "threads"])
def test_replay_matches_by_id_regardless_of_order(tmp_path, replay_order):
    run_dir, text = _record(tmp_path, order="in_order")
    session = reflight.replay(run_dir)
    assert parallel_agent(session, session.task, order=replay_order) == text


def test_threaded_recording_replays_in_any_order(tmp_path):
    run_dir, text = _record(tmp_path, order="threads")
    # whatever completion order got recorded, ordered replay still matches
    session = reflight.replay(run_dir)
    assert parallel_agent(session, session.task, order="in_order") == text


def test_id_match_verifies_arguments(tmp_path):
    run_dir, _ = _record(tmp_path)

    def lying_agent(session, task):
        response = session.messages.create(
            model="claude-sonnet-5", max_tokens=1024, messages=[{"role": "user", "content": task}]
        )
        block = next(b for b in response.content if b.type == "tool_use")
        # right id, wrong arguments
        session.execute("calculator", {"expression": "9 / 3"}, block.id)

    session = reflight.replay(run_dir)
    with pytest.raises(ReplayDivergence, match="diverged"):
        lying_agent(session, session.task)


def test_ids_do_not_match_across_turns(tmp_path):
    # two sequential single-tool turns; asking for turn-2's id during turn 1
    # must diverge, not silently time-travel
    class TwoTurns:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            n = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
            if n < 2:
                content = [
                    {
                        "type": "tool_use",
                        "id": f"toolu_turn_{n}",
                        "name": "calculator",
                        "input": {"expression": f"{n} + {n}"},
                    }
                ]
                stop = "tool_use"
            else:
                content = [{"type": "text", "text": "done"}]
                stop = "end_turn"
            return Message.model_validate(
                {
                    "id": f"msg_{n}",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5",
                    "content": content,
                    "stop_reason": stop,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 50, "output_tokens": 10},
                }
            )

    run_dir = tmp_path / "two-turns"
    session = reflight.record(
        run_dir, task="t", client=TwoTurns(), tools={"calculator": calculator}
    )
    messages = [{"role": "user", "content": "t"}]
    for _ in range(3):
        response = session.messages.create(
            model="claude-sonnet-5", max_tokens=1024, messages=messages
        )
        messages.append({"role": "assistant", "content": list(response.content)})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result, _ = session.execute(block.name, dict(block.input), block.id)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
        messages.append({"role": "user", "content": results})
    session.end()

    replay = reflight.replay(run_dir)
    replay.messages.create(
        model="claude-sonnet-5", max_tokens=1024, messages=[{"role": "user", "content": "t"}]
    )
    with pytest.raises(ReplayDivergence):
        # turn-2's id + turn-2's args during turn 1: out of window on both paths
        replay.execute("calculator", {"expression": "1 + 1"}, "toolu_turn_1")