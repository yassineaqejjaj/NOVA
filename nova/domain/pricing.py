"""Cost of a model call. Prices are configuration (USD per million tokens), never hard-coded vendor tariffs.

A model absent from the price table falls back to the global input/output price; with both at 0 (the
self-hosted default) the cost of a call is 0.0, which is truthful for a model NOVA does not pay per token.
"""

from __future__ import annotations

from dataclasses import dataclass

from nova.domain.outputs import TokenUsage


@dataclass(frozen=True)
class Pricing:
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    table: dict[str, tuple[float, float]] | None = None  # model -> (input, output) per million tokens

    def estimate(self, model: str | None, usage: TokenUsage) -> float:
        in_price, out_price = self.input_per_mtok, self.output_per_mtok
        if model and self.table and model in self.table:
            in_price, out_price = self.table[model]
        return round((usage.input_tokens * in_price + usage.output_tokens * out_price) / 1_000_000, 6)
