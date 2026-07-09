"""Scripted model for the refund agent — varied orders, seeded behaviors.

Runs come in pairs on the same order (task strings identical within a pair)
so a pass and its failing sibling diff cleanly: identical prefix, divergence
exactly at the refund call.

    MODES[seed]: pass | wrong_args (amount sent as "$X.YZ") | pending (gateway
    never settles; endless=True removes the give-up for the governor demo)
"""

from __future__ import annotations

from typing import Any

from anthropic.types import Message

ORDERS = [
    ("CUST-4816", "ORD-7351", 49.99, "the stoneware mug set arrived shattered"),
    ("CUST-2210", "ORD-8102", 129.00, "the espresso grinder died after two days"),
    ("CUST-9034", "ORD-6644", 18.50, "the tea towels arrived stained"),
]

MODES = ["pass", "wrong_args", "pass", "pending", "pass", "wrong_args"]


def order_for(seed: int) -> tuple[str, str, float, str]:
    return ORDERS[(seed // 2) % len(ORDERS)]


def task_for(seed: int) -> str:
    customer, order_id, _, issue = order_for(seed)
    return (
        f"Customer {customer} reports that {issue} (order {order_id}). "
        "Verify the order, check policy, and process the appropriate refund."
    )


def _tool(name: str, tool_input: dict, lead: str | None = None) -> dict:
    step = {"kind": "tool", "name": name, "input": tool_input}
    if lead:
        step["lead"] = lead
    return step


def _final(text: str) -> dict:
    return {"kind": "final", "text": text}


def _script(seed: int, endless: bool) -> list[dict]:
    mode = "pending" if endless else MODES[seed % len(MODES)]
    customer, order_id, total, issue = order_for(seed)

    prefix = [
        _tool(
            "lookup_order",
            {"order_id": order_id},
            lead=f"A damage claim from {customer}. Let me verify the order first.",
        ),
        _tool(
            "refund_policy",
            {"reason": "damaged item"},
            lead=f"Order confirmed: ${total:.2f}, delivered. Checking what policy allows.",
        ),
    ]

    if mode == "wrong_args":
        bad = _tool(
            "issue_refund",
            {"order_id": order_id, "amount_usd": f"${total:.2f}"},
            lead="Policy allows a full refund. Issuing it now.",
        )
        return prefix + [
            bad,
            _tool(
                "issue_refund",
                {"order_id": order_id, "amount_usd": f"${total:.2f}"},
                lead="The API rejected that. Trying the refund again.",
            ),
            _tool("issue_refund", {"order_id": order_id, "amount_usd": f"${total:.2f}"}),
            _final(
                f"I verified the claim for {order_id}, but the refund API rejected "
                "every attempt. Escalating to a human agent."
            ),
        ]

    if mode == "pending":
        retry = _tool("issue_refund", {"order_id": order_id, "amount_usd": total})
        first = _tool(
            "issue_refund",
            {"order_id": order_id, "amount_usd": total},
            lead="Policy allows a full refund. Issuing it now.",
        )
        if endless:
            return prefix + [first] + [retry] * 10_000
        return prefix + [first, retry, retry, retry, retry] + [
            _final(
                f"The ${total:.2f} refund for {order_id} is stuck in PENDING at "
                "the payment gateway after five attempts. Escalating."
            )
        ]

    return prefix + [
        _tool(
            "issue_refund",
            {"order_id": order_id, "amount_usd": total},
            lead="Policy allows a full refund. Issuing it now.",
        ),
        _tool(
            "notify_customer",
            {
                "message": f"We're sorry about your order {order_id}. A full refund "
                f"of ${total:.2f} was issued to your original payment method "
                "(5-10 business days)."
            },
        ),
        _final(
            f"Verified the damage claim for {order_id}, confirmed policy allows a "
            f"full refund, and issued ${total:.2f} (refund RFD-2209). Customer "
            "notified."
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

        if step["kind"] == "tool":
            content: list[dict] = []
            if step.get("lead"):
                content.append({"type": "text", "text": step["lead"]})
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_refund_{self._seed}_{n:04d}",
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
