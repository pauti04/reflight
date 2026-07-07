"""LLM-judge classification: the fuzzy failures rules can't catch.

The rule classifiers see structure (loops, bad args, crashes). The judge reads
the transcript and answers the question rules can't: did the agent actually
accomplish the task, and is the final answer right?

The client is injected so tests use a scripted judge; live use takes a real
anthropic.Anthropic(). Model per PROJECT_PLAN: Sonnet judges, it's cheap and
good enough.
"""

from __future__ import annotations

import json
from typing import Any

JUDGE_MODEL = "claude-sonnet-5"

_SYSTEM = """You judge recorded AI-agent runs. You get the task and a transcript of \
every model turn and tool call. Decide whether the agent completed the task and \
whether its final answer is correct. Be strict: a confident wrong answer is worse \
than an honest failure.

Reply with ONLY a JSON object, no other text:
{"task_completed": bool, "answer_correct": bool or null, "label": "ok" | \
"wrong_answer" | "incomplete" | "hallucination", "confidence": 0.0-1.0, \
"reasoning": "one or two sentences"}"""


def render_transcript(events: list[dict], max_chars: int = 6000) -> str:
    lines = []
    for event in events:
        if event["type"] == "run_start":
            lines.append(f"TASK: {event['task']}")
        elif event["type"] == "llm_call":
            for block in event["response"].get("content", []):
                if block.get("type") == "tool_use":
                    lines.append(
                        f"[{event['seq']}] assistant → {block['name']}({json.dumps(block['input'])})"
                    )
                elif block.get("type") == "text":
                    lines.append(f"[{event['seq']}] assistant: {block['text']}")
        elif event["type"] == "tool_call":
            marker = " (ERROR)" if event["is_error"] else ""
            lines.append(f"[{event['seq']}] {event['name']} result{marker}: {event['result']}")
        elif event["type"] == "error":
            lines.append(f"[{event['seq']}] CRASH: {event['error_type']}: {event['message']}")
        elif event["type"] == "run_end":
            lines.append(f"OUTCOME: status={event['status']}, final answer: {event['final_text']}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars // 2] + "\n…(transcript truncated)…\n" + text[-max_chars // 2 :]
    return text


def _parse_verdict(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"judge returned no JSON: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def judge_run(events: list[dict], client: Any, model: str = JUDGE_MODEL) -> dict:
    """Returns {"ok": bool, "label": str, "confidence": float, "reasoning": str}."""
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": render_transcript(events)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    verdict = _parse_verdict(text)
    # The label is the judge's conclusion — trust it. (task_completed alone is
    # too lenient: an honest "I couldn't find the data" completes the
    # *conversation* without accomplishing the task.)
    ok = (
        str(verdict.get("label", "ok")) == "ok"
        and bool(verdict.get("task_completed"))
        and verdict.get("answer_correct") is not False
    )
    return {
        "ok": ok,
        "label": str(verdict.get("label", "ok")),
        "confidence": float(verdict.get("confidence", 0.5)),
        "reasoning": str(verdict.get("reasoning", "")),
    }
