"""Default pricing table for cost estimation.

Maps model names to per-token pricing (input rate / output rate in USD).
Users can override in config.json via the cost_table section.
"""

from __future__ import annotations

DEFAULT_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-4-opus": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-4.6-opus": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-4.6-opus-high": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-4-sonnet": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-3.5-sonnet": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-3.5-haiku": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.0 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gpt-4.1": {"input": 2.0 / 1_000_000, "output": 8.0 / 1_000_000},
    "gpt-4.1-mini": {"input": 0.40 / 1_000_000, "output": 1.60 / 1_000_000},
    "gemini-2.5-pro": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    "gemini-2.5-flash": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "o3": {"input": 10.0 / 1_000_000, "output": 40.0 / 1_000_000},
    "o3-mini": {"input": 1.10 / 1_000_000, "output": 4.40 / 1_000_000},
    "o4-mini": {"input": 1.10 / 1_000_000, "output": 4.40 / 1_000_000},
}


def estimate_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_table: dict[str, dict[str, float]] | None = None,
) -> float | None:
    """Estimate cost in USD for a token usage record.

    Returns None if the model is not in the pricing table.
    """
    table = cost_table or DEFAULT_COST_TABLE
    if model is None or model not in table:
        return None

    rates = table[model]
    return (input_tokens * rates["input"]) + (output_tokens * rates["output"])
