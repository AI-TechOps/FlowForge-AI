"""Token cost estimation.

Phase 2 records a per-call estimate so the audit trail is complete from the
start; Phase 5 formalizes the pricing table and aggregates it into metrics.
Local models cost nothing — that is the point of the local-first build (D11).
"""

# USD per 1M tokens (input, output), as published 2026-08-16.
#
# Versioned in code rather than config (D19 decision 7). An unset config table
# silently reports $0, and the cost figure is the one most likely to be quoted
# out loud in a demo — so it should be the one most visible in review. A stale
# price here shows up in a diff; a stale price in an env var shows up nowhere.
#
# Unknown models fall back to free, which keeps a missing entry from inflating
# a figure. That cuts the other way too: a new model priced at zero under-
# reports until it is added here. Every cost in this system is labelled an
# estimate for exactly that reason.
PRICING_AS_OF = "2026-08-16"
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}


def estimate_cost(model: str, tokens_in: int | None, tokens_out: int | None) -> float:
    if model.startswith(("fake:", "ollama:")) or "/" not in model and ":" in model:
        # Ollama tags look like "llama3.1:8b"; fake is prefixed. Both are free.
        return 0.0
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    return round(((tokens_in or 0) * price_in + (tokens_out or 0) * price_out) / 1_000_000, 6)
