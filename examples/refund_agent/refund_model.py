"""Scripted model for the refund agent — three behaviors, seed-selected.

    seed % 3 == 0   correct: lookup, policy, refund 49.99, notify, done
    seed % 3 == 1   formats the amount as a string ("$49.99"), retries the
                    identical broken call, gives up
    seed % 3 == 2   correct call, but the gateway answers PENDING — the agent
                    retries the same call again and again (pair with
                    make_tools(pending=True); unbounded when patient=False is
                    off, so the governor demo uses this seed too)
"""

from __future__ import annotations

from typing import Any

from anthropic.types import Message

TASK = (
    "Customer CUST-4816 reports order ORD-7351 arrived damaged. "
    "Verify the order, check policy, and process the appropriate refund."
)


def _tool(name: str, tool_input: dict) -> dict:
    return {"type": "tool_use", "name": name, "input": tool_input}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _script(seed: int, endless: bool) -> list[dict]:
    mode = seed % 3
    lookup = _tool("lookup_order", {"order_id": "ORD-7351"})
    policy = _tool("refund_policy", {"reason": "damaged item"})
    if mode == 1:
        bad = _tool("issue_refund", {"order_id": "ORD-7351", "amount_usd": "$49.99"})
        return [
            lookup,
            policy,
            bad,
            bad,
            bad,
            _text(
                "I verified the damaged-item claim for ORD-7351 but the refund "
                "API keeps rejecting my request. I could not process the refund."
            ),
        ]
    if mode == 2:
        retry = _tool("issue_refund", {"order_id": "ORD-7351", "amount_usd": 49.99})
        if endless:
            return [lookup, policy] + [retry] * 10_000
        return [
            lookup,
            policy,
            retry,
            retry,
            retry,
            retry,
            retry,
            _text(
                "The refund for ORD-7351 is stuck in PENDING at the payment "
                "gateway after several attempts. Escalating to a human agent."
            ),
        ]
    return [
        lookup,
        policy,
        _tool("issue_refund", {"order_id": "ORD-7351", "amount_usd": 49.99}),
        _tool(
            "notify_customer",
            {
                "message": "We're sorry about the damaged mugs. A full refund of "
                "$49.99 for order ORD-7351 was issued to your original payment "
                "method (5-10 business days)."
            },
        ),
        _text(
            "Verified the damaged-item claim for ORD-7351, confirmed policy "
            "allows a full refund, and issued $49.99 to the original payment "
            "method (refund RFD-2209). Customer notified."
        ),
    ]


class _Messages:
    def __init__(self, seed: int, endless: bool):
        self._seed = seed
        self._endless = endless

    def create(self, **kwargs: Any) -> Message:
        n = sum(1 for m in kwargs["messages"] if m["role"] == "assistant")
        script = _script(self._seed, self._endless)
        step = script[min(n, len(script) - 1)]
        if step["type"] == "tool_use":
            content = [{**step, "id": f"toolu_refund_{self._seed}_{n:04d}"}]
            stop = "tool_use"
        else:
            content = [step]
            stop = "end_turn"
        return Message.model_validate(
            {
                "id": f"msg_refund_{self._seed}_{n:04d}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 240 + 30 * n, "output_tokens": 55},
            }
        )


class RefundAnthropic:
    def __init__(self, seed: int, endless: bool = False):
        self.messages = _Messages(seed, endless)
