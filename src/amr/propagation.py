"""Centralized W3C trace-context propagation for A2A transports."""

from collections.abc import Mapping, MutableMapping

from opentelemetry import propagate
from opentelemetry.context import Context


def inject_into(headers: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Add the active W3C trace context to ``headers`` and return it."""

    propagate.inject(headers)
    return headers


def extract_from(headers: Mapping[str, str]) -> Context:
    """Extract a W3C trace context from HTTP-style headers."""

    return propagate.extract(headers)
