"""Bad-output provenance: which agent originated flagged output, and who consumed it.

Given raw SigNoz trace rows, find the shallowest span carrying
``agentmesh.output.flagged`` (the origin — the agent that produced the bad output)
and list the distinct services of its descendant spans (the consumers that ran on
the tainted output downstream).  This is a pure analysis overlay: it reads only
attributes already on the trace and never touches prompt or model-output content.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from . import semconv
from .explain import _service, _value


def _span_id(span: Mapping[str, Any]) -> str:
    return str(span.get("span_id", span.get("spanId", "")))


def _parent_id(span: Mapping[str, Any]) -> str:
    return str(span.get("parent_span_id", span.get("parentSpanId", "")) or "")


def _is_flagged(span: Mapping[str, Any]) -> bool:
    value = _value(span, semconv.AGENTMESH_OUTPUT_FLAGGED)
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _depth(span: Mapping[str, Any], by_id: dict[str, Mapping[str, Any]]) -> int:
    depth, seen, current = 0, set(), span
    while True:
        parent_id = _parent_id(current)
        if not parent_id or parent_id in seen or parent_id not in by_id:
            return depth
        seen.add(parent_id)
        current = by_id[parent_id]
        depth += 1


def origin_of_bad_output(spans: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Return the origin agent + consumers of flagged output, or ``None`` if clean."""

    rows = [dict(span) for span in spans]
    by_id = {_span_id(span): span for span in rows if _span_id(span)}
    flagged = [span for span in rows if _is_flagged(span)]
    if not flagged:
        return None

    # The origin is the flagged span closest to the root; ties break by span id for
    # determinism.  A deeper flagged span is a consumer that re-flagged, not the source.
    origin = min(flagged, key=lambda span: (_depth(span, by_id), _span_id(span)))
    origin_id = _span_id(origin)
    origin_service = _service(origin)
    category = _value(origin, semconv.AGENTMESH_OUTPUT_CATEGORY)

    # Consumers are the distinct services of the origin's descendants.
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
