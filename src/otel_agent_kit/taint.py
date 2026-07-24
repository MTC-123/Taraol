"""Injection-taint marking carried across hops via W3C baggage (content-free)."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import baggage, context

from .attributes import AttrNames


@dataclass(frozen=True, slots=True)
class Taint:
    category: str
    origin: str
    hops: int = 0


def _baggage_key(names: AttrNames) -> str:
    return names.taint


def _encode(taint: Taint) -> str:
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


def mark_taint(span: object, taint: Taint, names: AttrNames) -> None:
    span.set_attribute(names.taint, True)  # type: ignore[attr-defined]
    span.set_attribute(names.taint_category, taint.category)  # type: ignore[attr-defined]
    span.set_attribute(names.taint_origin, taint.origin)  # type: ignore[attr-defined]
    span.set_attribute(names.taint_hops, taint.hops)  # type: ignore[attr-defined]


def taint_from_baggage(names: AttrNames) -> Taint | None:
    raw = baggage.get_baggage(_baggage_key(names))
    if not isinstance(raw, str):
        return None
    return _decode(raw)


@contextmanager
def taint_scope(taint: Taint, names: AttrNames) -> Iterator[None]:
    """Attach a taint marker so outbound hops in this scope carry it downstream."""

    ctx = baggage.set_baggage(_baggage_key(names), _encode(taint))
    token = context.attach(ctx)
    try:
        yield
    finally:
        context.detach(token)
