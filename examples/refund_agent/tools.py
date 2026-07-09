"""Tools for the refund agent — the shape of a real support-automation stack.

Deterministic and offline; `pending=True` simulates a payment gateway that
never settles (the runaway scenario).
"""

from __future__ import annotations

import json

TOOL_SPECS = [
    {
        "name": "lookup_order",
        "description": "Fetch an order by id: items, total, status, customer.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "refund_policy",
        "description": "Company refund policy for a given claim reason.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "issue_refund",
        "description": "Issue a refund to the order's original payment method. "
        "amount_usd must be a number, not a formatted string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount_usd": {"type": "number"},
            },
            "required": ["order_id", "amount_usd"],
        },
    },
    {
        "name": "notify_customer",
        "description": "Send the customer a status update email.",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]

_ORDERS = {
    "ORD-7351": {
        "order_id": "ORD-7351",
        "customer_id": "CUST-4816",
        "status": "delivered",
        "total_usd": 49.99,
        "items": [{"sku": "MUG-STONE-11", "name": "Stoneware mug, set of 2", "qty": 1}],
    },
    "ORD-8102": {
        "order_id": "ORD-8102",
        "customer_id": "CUST-2210",
        "status": "delivered",
        "total_usd": 129.00,
        "items": [{"sku": "GRND-ESP-02", "name": "Conical burr espresso grinder", "qty": 1}],
    },
    "ORD-6644": {
        "order_id": "ORD-6644",
        "customer_id": "CUST-9034",
        "status": "delivered",
        "total_usd": 18.50,
        "items": [{"sku": "TWL-LIN-04", "name": "Linen tea towels, set of 4", "qty": 1}],
    },
}


def make_tools(pending: bool = False) -> dict:
    def lookup_order(order_id: str) -> str:
        if order_id not in _ORDERS:
            raise ValueError(f"no such order: {order_id}")
        return json.dumps(_ORDERS[order_id])

    def refund_policy(reason: str) -> str:
        del reason
        return (
            "Damaged or defective items: full refund to the original payment "
            "method, no approval needed up to $500. Refund must not exceed the "
            "order total."
        )

    def issue_refund(order_id: str, amount_usd: float) -> str:
        if not isinstance(amount_usd, (int, float)):
            raise TypeError(
                f"amount_usd must be a number, got {type(amount_usd).__name__} "
                f"{amount_usd!r}"
            )
        if order_id not in _ORDERS:
            raise ValueError(f"no such order: {order_id}")
        if amount_usd > _ORDERS[order_id]["total_usd"]:
            raise ValueError(
                f"refund ${amount_usd:.2f} exceeds order total "
                f"${_ORDERS[order_id]['total_usd']:.2f}"
            )
        if pending:
            return json.dumps(
                {"status": "PENDING", "detail": "gateway settlement delayed — retry later"}
            )
        return json.dumps(
            {"refund_id": "RFD-2209", "status": "issued", "amount_usd": amount_usd}
        )

    def notify_customer(message: str) -> str:
        del message
        return json.dumps({"delivered": True})

    return {
        "lookup_order": lookup_order,
        "refund_policy": refund_policy,
        "issue_refund": issue_refund,
        "notify_customer": notify_customer,
    }
