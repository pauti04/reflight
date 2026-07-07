"""Model pricing for cost-at-ingest. USD per million tokens.

Source: platform.claude.com pricing (cached 2026-06). Sonnet 5 has an
introductory $2/$10 rate through 2026-08-31; we bill at the $3/$15 sticker so
cost estimates don't silently drop when the promo ends. Unknown models get
cost None rather than a guess.
"""

from __future__ import annotations

# model-id prefix -> (input $/MTok, output $/MTok)
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute TTL writes


def resolve(model: str) -> tuple[float, float] | None:
    """Prefix match so date-suffixed IDs (claude-haiku-4-5-20251001) resolve too."""
    for prefix, prices in PRICES.items():
        if model.startswith(prefix):
            return prices
    return None


def cost_usd(model: str | None, usage: dict) -> float | None:
    """Cost of one LLM call from its usage block. None if the model is unknown."""
    prices = resolve(model or "")
    if prices is None:
        return None
    input_price, output_price = prices
    cost = (usage.get("input_tokens") or 0) / 1e6 * input_price
    cost += (usage.get("output_tokens") or 0) / 1e6 * output_price
    cost += (usage.get("cache_read_input_tokens") or 0) / 1e6 * input_price * CACHE_READ_MULTIPLIER
    cost += (
        (usage.get("cache_creation_input_tokens") or 0)
        / 1e6
        * input_price
        * CACHE_WRITE_MULTIPLIER
    )
    return cost
