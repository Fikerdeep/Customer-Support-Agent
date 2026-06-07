"""Token pricing + cost helper for trace cost tracking.

Rates are USD per 1,000,000 tokens (OpenAI). ``cache_read`` is the discounted rate
for cached input tokens; OpenAI does not charge a separate cache-write fee, so
``cache_write`` is 0. Edit/extend this table for whatever model you set in
``AGENT_MODEL`` — unknown models fall back to the gpt-4o rate.
"""
from __future__ import annotations

PRICING_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": 0.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.0},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "cache_read": 0.50, "cache_write": 0.0},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cache_read": 0.10, "cache_write": 0.0},
}

_FALLBACK = PRICING_PER_MILLION["gpt-4o"]


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return the USD cost of a single model call's token usage."""
    rates = PRICING_PER_MILLION.get(model, _FALLBACK)
    total = (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_read_tokens * rates["cache_read"]
        + cache_write_tokens * rates["cache_write"]
    )
    return round(total / 1_000_000, 6)
