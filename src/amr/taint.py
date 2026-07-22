"""Injection-taint marking that rides W3C baggage across agent hops.

When a guardrail flags an agent's input or output, we (a) stamp content-free
``agentmesh.taint*`` attributes on the active span and (b) place a taint marker in
OpenTelemetry **baggage**.  Because baggage is injected into outbound headers by the
same propagator that carries ``traceparent`` (see :mod:`amr.otel_setup`), every
downstream A2A hop automatically carries the taint; each receiving agent reads it at
handler entry and re-stamps its own spans.  The set of services with a tainted span
in a trace is the injection **blast radius**.

Baggage values must be strings, so the marker is encoded ``"category:origin:hops"``.
No prompt or model-output text is ever placed in baggage or on a span.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import baggage, context

from . import semconv

_BAGGAGE_KEY = "agentmesh.taint"


@dataclass(frozen=True, slots=True)
class Taint:
    category: str
    origin: str
    hops: int = 0


def _encode(taint: Taint) -> str:
    # origin is a service name (no colons); category is a closed enum.
    return f"{taint.category}:{taint.origin}:{taint.hops}"


def _decode(raw: str) -> Taint | None:
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    category, origin, hops = parts
    try:
        return Taint(category, origin, int(hops))
    except ValueError:
        return None


def mark_taint(span: object, taint: Taint) -> None:
    """Stamp content-free taint attributes on ``span``."""

    span.set_attribute(semconv.AGENTMESH_TAINT, True)  # type: ignore[attr-defined]
    span.set_attribute(semconv.AGENTMESH_TAINT_CATEGORY, taint.category)  # type: ignore[attr-defined]
    span.set_attribute(semconv.AGENTMESH_TAINT_ORIGIN, taint.origin)  # type: ignore[attr-defined]
    span.set_attribute(semconv.AGENTMESH_TAINT_HOPS, taint.hops)  # type: ignore[attr-defined]


def taint_from_baggage() -> Taint | None:
    """Return the taint marker carried in the current context, if any."""

    raw = baggage.get_baggage(_BAGGAGE_KEY)
    if not isinstance(raw, str):
        return None
    return _decode(raw)


@contextmanager
def taint_scope(taint: Taint) -> Iterator[None]:
    """Attach a taint marker to the current context for the enclosed work.

    Outbound A2A hops made inside this scope inject the marker into their headers,
    so downstream agents inherit the taint automatically.
    """

    ctx = baggage.set_baggage(_BAGGAGE_KEY, _encode(taint))
    token = context.attach(ctx)
    try:
        yield
    finally:
        context.detach(token)
