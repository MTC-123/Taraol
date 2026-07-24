"""Pricing and request-local cost accumulation (bundled default table).

The default price table ships inside the wheel (``data/pricing.yaml``) and is loaded
via ``importlib.resources`` — no filesystem path assumptions.  A caller overrides it
with a :class:`CostModel` built from a dict or a YAML file, or the ``OAK_PRICING_FILE``
environment variable.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

PriceTable = dict[str, dict[str, float]]


def _parse(data: object) -> PriceTable:
    models = data.get("models", {}) if isinstance(data, Mapping) else {}
    if not isinstance(models, Mapping):
        raise ValueError("pricing: models must be a mapping")
    table: PriceTable = {}
    for model, price in models.items():
        if not isinstance(model, str) or not isinstance(price, Mapping):
            raise ValueError("pricing: each model must map to a price mapping")
        try:
            table[model] = {
                "input_per_1k": float(price["input_per_1k"]),
                "output_per_1k": float(price["output_per_1k"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"pricing: invalid price for {model}") from exc
    return table


def _bundled_table() -> PriceTable:
    text = resources.files("otel_agent_kit.data").joinpath("pricing.yaml").read_text("utf-8")
    return _parse(yaml.safe_load(text))


class CostModel:
    """Resolve model prices from a dict, a YAML file, or the bundled default."""

    def __init__(
        self, table: Mapping[str, Mapping[str, float]] | None = None, *, path: str | Path | None = None
    ) -> None:
        if table is not None:
            self._table = _parse({"models": dict(table)})
        elif path is not None:
            self._table = _parse(yaml.safe_load(Path(path).read_text("utf-8")))
        else:
            self._table = _bundled_table()

    def cost_of(
        self, model: str, input_tokens: int | float, output_tokens: int | float
    ) -> tuple[float, bool]:
        """Return (USD rounded to 4dp, unpriced?) for a model's token usage."""

        price = self._table.get(model)
        if price is None:
            return 0.0, True
        usd = (float(input_tokens) / 1000) * price["input_per_1k"]
        usd += (float(output_tokens) / 1000) * price["output_per_1k"]
        return round(usd, 4), False


@dataclass
class CostAccumulator:
    """Mutable state intentionally scoped to one inbound request."""

    usd: float = 0.0

    def add(self, cost_usd: float) -> None:
        self.usd = round(self.usd + float(cost_usd), 4)


_request_cost: ContextVar[CostAccumulator | None] = ContextVar("oak_request_cost", default=None)


@contextmanager
def request_cost_scope() -> Iterator[CostAccumulator]:
    """Collect this request's direct chat cost plus returned downstream subtree cost."""

    accumulator = CostAccumulator()
    token = _request_cost.set(accumulator)
    try:
        yield accumulator
    finally:
        _request_cost.reset(token)


def add_to_request_cost(cost_usd: float) -> None:
    accumulator = _request_cost.get()
    if accumulator is not None:
        accumulator.add(cost_usd)
