"""Sprint 4: fork mode and the LLM judge."""

import json

import pytest

import main as example
from flaky_model import FlakyAnthropic
from tools import make_tools

import reflight
from reflight import ReplayDivergence, read_events, store
from reflight.judge import judge_run, render_transcript

TASK = "What is the population of Tokyo, and what is that number divided by 2?"


def _record_flaky(tmp_path, seed, db_path=None):
    run_dir = tmp_path / f"flaky-{seed:02d}"
    session = reflight.record(run_dir, task=TASK, db_path=db_path)
    session.wrap(FlakyAnthropic(seed))
    session._tools.update(make_tools(run_dir / "notes"))
    example.run_agent(session, TASK)
    return run_dir


# -- fork mode -----------------------------------------------------------------


def test_fork_fixes_a_failed_run(tmp_path):
    db = tmp_path / "test.db"
    source = _record_flaky(tmp_path, 2, db_path=db)  # wrong_tool_args failure

    fork_dir = tmp_path / "fixed"
    session = reflight.fork(
        source,
        1,
        client=FlakyAnthropic(0),  # the fixed model
        tools=make_tools(fork_dir / "notes"),
        out_dir=fork_dir,
        db_path=db,
    )
    final_text, status = example.run_agent(session, session.task)

    assert status == "completed"
    assert "18,700,034" in final_text

    runs = {r["run_id"]: r for r in store.list_runs(db)}
    assert runs["flaky-02"]["verdict"] == "fail"
    assert runs["fixed"]["verdict"] == "pass"

    # the fork is a complete, self-contained recording — replay it
    replay_session = reflight.replay(fork_dir)
    replayed_text, _ = example.run_agent(replay_session, replay_session.task)
    assert replayed_text == final_text


def test_fork_prefix_is_reused_not_recomputed(tmp_path):
    source = _record_flaky(tmp_path, 0)
    source_events = read_events(source)

    # fork after the first tool call: prefix (seq 0-2) replayed, rest live
    fork_dir = tmp_path / "fork3"
    session = reflight.fork(
        source,
        3,
        client=FlakyAnthropic(0),
        tools=make_tools(fork_dir / "notes"),
        out_dir=fork_dir,
    )
    example.run_agent(session, session.task)
    fork_events = read_events(fork_dir)

    # prefix identical to the source recording (same hashes)
    assert fork_events[1]["request_hash"] == source_events[1]["request_hash"]
    assert fork_events[2]["input_hash"] == source_events[2]["input_hash"]


def test_fork_detects_divergence_before_fork_point(tmp_path):
    source = _record_flaky(tmp_path, 0)
    session = reflight.fork(
        source,
        5,
        client=FlakyAnthropic(0),
        tools=make_tools(tmp_path / "notes"),
        out_dir=tmp_path / "bad-fork",
    )
    # a different task changes the very first request — before the fork point
    with pytest.raises(ReplayDivergence, match="fork at an earlier seq"):
        example.run_agent(session, "A completely different task")


# -- LLM judge -------------------------------------------------------------------


class ScriptedJudge:
    """A judge that flunks any transcript whose final answer contains '42'."""

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        from anthropic.types import Message

        transcript = kwargs["messages"][0]["content"]
        if "The answer is 42" in transcript:
            verdict = {
                "task_completed": False,
                "answer_correct": False,
                "label": "wrong_answer",
                "confidence": 0.92,
                "reasoning": "The agent got stuck in a loop and invented the answer 42.",
            }
        else:
            verdict = {
                "task_completed": True,
                "answer_correct": True,
                "label": "ok",
                "confidence": 0.95,
                "reasoning": "Search and arithmetic support the final answer.",
            }
        return Message.model_validate(
            {
                "id": "msg_judge",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": json.dumps(verdict)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 500, "output_tokens": 60},
            }
        )


def test_render_transcript_contains_the_story(tmp_path):
    events = read_events(_record_flaky(tmp_path, 1))
    transcript = render_transcript(events)
    assert "TASK:" in transcript
    assert "calculator" in transcript
    assert "The answer is 42" in transcript


def test_judge_flags_wrong_answer_and_merges_into_verdict(tmp_path):
    db = tmp_path / "test.db"
    _record_flaky(tmp_path, 1, db_path=db)

    events = [e for e, _ in store.get_events(db, "flaky-01")]
    result = judge_run(events, ScriptedJudge())
    assert result["ok"] is False
    assert result["label"] == "wrong_answer"

    end_seq = events[-1]["seq"]
    store.add_finding(
        db, "flaky-01", end_seq, "judge_wrong_answer", "fail", result["confidence"],
        result["reasoning"],
    )
    run = next(r for r in store.list_runs(db) if r["run_id"] == "flaky-01")
    assert run["verdict"] == "fail"
    assert "judge_wrong_answer" in run["labels"]


def test_judge_passes_a_clean_run(tmp_path):
    events = read_events(_record_flaky(tmp_path, 0))
    result = judge_run(events, ScriptedJudge())
    assert result["ok"] is True
