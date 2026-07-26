"""Bad-output provenance: origin agent + downstream consumers (content-free)."""

from collections.abc import Iterable, Mapping
from typing import Any

from .attributes import AttrNames


def _attrs(span: Mapping[str, Any]) -> Mapping[str, Any]:
    value = span.get("attributes")
    return value if isinstance(value, Mapping) else {}


def _value(span: Mapping[str, Any], name: str) -> Any:
    return span.get(name, _attrs(span).get(name))


def _service(span: Mapping[str, Any]) -> str:
    resource = span.get("resource")
    if isinstance(resource, Mapping) and isinstance(resource.get("service.name"), str):
        return resource["service.name"]
    for name in ("service.name", "serviceName"):
        value = _value(span, name)
        if isinstance(value, str):
            return value
    return "unknown"


def _span_id(span: Mapping[str, Any]) -> str:
    return str(span.get("span_id", span.get("spanId", "")))


def _parent_id(span: Mapping[str, Any]) -> str:
    return str(span.get("parent_span_id", span.get("parentSpanId", "")) or "")


def _depth(span: Mapping[str, Any], by_id: dict[str, Mapping[str, Any]]) -> int:
    depth, seen, current = 0, set(), span
    while True:
        parent_id = _parent_id(current)
        if not parent_id or parent_id in seen or parent_id not in by_id:
            return depth
        seen.add(parent_id)
        current = by_id[parent_id]
        depth += 1


def origin_of_bad_output(
    spans: Iterable[Mapping[str, Any]], names: AttrNames
) -> dict[str, Any] | None:
    """Return the origin agent + consumer services of flagged output, or ``None``."""

    def flagged(span: Mapping[str, Any]) -> bool:
        value = _value(span, names.output_flagged)
        return value is True or (isinstance(value, str) and value.lower() == "true")

    rows = [dict(span) for span in spans]
    by_id = {_span_id(span): span for span in rows if _span_id(span)}
    hits = [span for span in rows if flagged(span)]
    if not hits:
        return None

    origin = min(hits, key=lambda span: (_depth(span, by_id), _span_id(span)))
    origin_id = _span_id(origin)
    origin_service = _service(origin)
    category = _value(origin, names.output_category)

    consumers: list[str] = []
    for span in rows:
        current, seen = span, set()
        while True:
            parent_id = _parent_id(current)
            if not parent_id or parent_id in seen or parent_id not in by_id:
                break
            seen.add(parent_id)
            if parent_id == origin_id:
                service = _service(span)
                if service != origin_service and service not in consumers:
                    consumers.append(service)
                break
            current = by_id[parent_id]

    return {
        "origin": origin_service,
        "category": category if isinstance(category, str) else None,
        "consumers": sorted(consumers),
    }
