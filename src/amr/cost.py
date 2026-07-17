"""Pricing and request-local cost accumulation for Agent Mesh Radar.

Prices are deliberately configuration data: update ``config/pricing.yaml`` when a
provider changes a model's rate.  The accumulator is request-local so a server can
return exactly its own chat/tool cost plus the costs returned by downstream agents.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PRICE_FILE = Path(__file__).resolve().parents[2] / "config" / "pricing.yaml"


@lru_cache(maxsize=1)
def _prices() -> dict[str, dict[str, float]]:
    """Load the price table once per process."""

    data = yaml.safe_load(PRICE_FILE.read_text(encoding="utf-8")) or {}
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise ValueError("config/pricing.yaml: models must be a mapping")
    prices: dict[str, dict[str, float]] = {}
    for model, price in models.items():
        if not isinstance(model, str) or not isinstance(price, dict):
            raise ValueError("config/pricing.yaml: each model must have a price mapping")
        try:
            prices[model] = {
                "input_per_1k": float(price["input_per_1k"]),
                "output_per_1k": float(price["output_per_1k"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"config/pricing.yaml: invalid price for {model}") from exc
    return prices


def cost_of(
    model: str, input_tokens: int | float, output_tokens: int | float
) -> tuple[float, bool]:
    """Return USD cost rounded to four decimals and whether the model is unpriced."""

    price = _prices().get(model)
    if price is None:
        return 0.0, True
    usd = (float(input_tokens) / 1000) * price["input_per_1k"]
    usd += (float(output_tokens) / 1000) * price["output_per_1k"]
    return round(usd, 4), False


@dataclass
class CostAccumulator:
    """Mutable state intentionally scoped to one inbound A2A request."""

    usd: float = 0.0

    def add(self, cost_usd: float) -> None:
        self.usd = round(self.usd + float(cost_usd), 4)


_request_cost: ContextVar[CostAccumulator | None] = ContextVar("amr_request_cost", default=None)


@contextmanager
def request_cost_scope() -> Iterator[CostAccumulator]:
    """Collect this request's direct chat cost and returned downstream subtree costs."""

    accumulator = CostAccumulator()
    token = _request_cost.set(accumulator)
    try:
        yield accumulator
    finally:
        _request_cost.reset(token)


def add_to_request_cost(cost_usd: float) -> None:
    """Add cost if execution is currently inside an inbound A2A request."""

    accumulator = _request_cost.get()
    if accumulator is not None:
        accumulator.add(cost_usd)
