"""W3C trace-context + baggage propagation helpers."""

from collections.abc import Mapping, MutableMapping

from opentelemetry import propagate
from opentelemetry.context import Context


def inject_into(headers: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Add the active trace context (and baggage) to ``headers`` and return it."""

    propagate.inject(headers)
    return headers


def extract_from(headers: Mapping[str, str]) -> Context:
    """Extract a trace context (and baggage) from HTTP-style headers."""

    return propagate.extract(headers)
