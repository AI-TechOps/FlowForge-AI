"""Token cost estimation.

Phase 2 records a per-call estimate so the audit trail is complete from the
start; Phase 5 formalizes the pricing table and aggregates it into metrics.
Local models cost nothing — that is the point of the local-first build (D11).
"""

# USD per 1M tokens (input, output). Unknown models fall back to free so a
# missing entry never inflates a cost figure — Phase 5 adds the real table.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def estimate_cost(model: str, tokens_in: int | None, tokens_out: int | None) -> float:
    if model.startswith(("fake:", "ollama:")) or "/" not in model and ":" in model:
        # Ollama tags look like "llama3.1:8b"; fake is prefixed. Both are free.
        return 0.0
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    return round(
        ((tokens_in or 0) * price_in + (tokens_out or 0) * price_out) / 1_000_000, 6
    )
