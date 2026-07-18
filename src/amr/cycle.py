"""Span-tree cycle detection that deliberately ignores sibling fan-out."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Cycle:
    services: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    hops: int


def _attributes(span: dict[str, Any]) -> dict[str, Any]:
    attrs = span.get("attributes", {})
    return attrs if isinstance(attrs, dict) else {}


def _service(span: dict[str, Any]) -> str:
    resource = span.get("resource", {})
    if isinstance(resource, dict) and isinstance(resource.get("service.name"), str):
        return resource["service.name"]
    attrs = _attributes(span)
    for key in ("service.name", "serviceName"):
        if isinstance(span.get(key), str):
            return span[key]
        if isinstance(attrs.get(key), str):
            return attrs[key]
    return "unknown"


def _span_id(span: dict[str, Any]) -> str:
    return str(span.get("span_id", span.get("spanId", "")))


def _parent_id(span: dict[str, Any]) -> str:
    return str(span.get("parent_span_id", span.get("parentSpanId", "")) or "")


def _sort_key(span: dict[str, Any]) -> tuple[str, str]:
    return (str(span.get("timestamp", span.get("start_time", ""))), _span_id(span))


def _compress_services(chain: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    result: list[str] = []
    for span in chain:
        service = _service(span)
        if not result or result[-1] != service:
            result.append(service)
    return tuple(result)


def _edges(services: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(zip(services, services[1:], strict=False))


def _is_alternating(services: tuple[str, ...], min_length: int) -> bool:
    if len(services) < min_length or len(set(services[-min_length:])) != 2:
        return False
    tail = services[-min_length:]
    return all(tail[index] == tail[index % 2] for index in range(len(tail)))


def find_cycles(spans: Iterable[dict[str, Any]], max_repeats: int = 3) -> list[Cycle]:
    """Return unique ancestry cycles; never combine parallel sibling paths."""

    nodes = {_span_id(span): span for span in spans if _span_id(span)}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []
    for span_id, span in nodes.items():
        parent_id = _parent_id(span)
        if parent_id and parent_id in nodes and parent_id != span_id:
            children[parent_id].append(span)
        else:
            roots.append(span)
    for group in children.values():
        group.sort(key=_sort_key)

    found: dict[tuple[str, ...], Cycle] = {}

    def visit(span: dict[str, Any], path: list[dict[str, Any]]) -> None:
        path.append(span)
        services = _compress_services(path)
        repeated = len(services) != len(set(services))
        alternating = _is_alternating(services, 2 * max_repeats)
        if repeated or alternating:
            found.setdefault(services, Cycle(services, _edges(services), len(services) - 1))
        for child in children.get(_span_id(span), []):
            visit(child, path)
        path.pop()

    for root in sorted(roots, key=_sort_key):
        visit(root, [])
    return list(found.values())
