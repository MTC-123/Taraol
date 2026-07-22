"""Grounded facts for the ``amr explain`` and MCP loop-explanation surfaces.

The module deliberately receives raw SigNoz rows and does not infer missing data.
Cost is summed only from direct chat spans: A2A hop spans contain callee subtree
totals and summing them would double count a conversation.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from .cycle import find_cycles


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


def _cycle_agents(services: tuple[str, ...]) -> set[str]:
    """Remove an acyclic prefix from a detector path before naming its cycle."""

    first_seen: dict[str, int] = {}
    for index, service in enumerate(services):
        previous = first_seen.get(service)
        if previous is not None:
            return set(services[previous:index])
        first_seen[service] = index
    return set()


def explain_trace(
    trace_id: str,
    spans: Iterable[Mapping[str, Any]],
    audit_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return only values directly supported by the supplied SigNoz trace rows."""

    # Imported lazily: provenance reads this module's row helpers, so a top-level
    # import would be circular.
    from .provenance import origin_of_bad_output

    rows = [dict(span) for span in spans]
    cycles = find_cycles(rows)
    cyclic_agents = sorted(
        {service for cycle in cycles for service in _cycle_agents(cycle.services)}
    )
    # Runaway evidence: how many times a cyclic agent repeated an identical state
    # (no progress). A converging cycle produces a fresh state each iteration.
    state_counts: dict[str, dict[str, int]] = {}
    for span in rows:
        service = _service(span)
        if service not in cyclic_agents:
            continue
        state = _value(span, "agentmesh.state.hash")
        if isinstance(state, str) and state:
            bucket = state_counts.setdefault(service, {})
            bucket[state] = bucket.get(state, 0) + 1
    stalled_iterations = max(
        (count for buckets in state_counts.values() for count in buckets.values()),
        default=0,
    )
    chat_cost = 0.0
    hop_count = 0
    for span in rows:
        if span.get("name") == "a2a.call":
            hop_count += 1
        if _value(span, "gen_ai.operation.name") == "chat":
            # Sum direct chat cost only — the additive conversation total. Hop spans
            # carry downstream_usd (subtree) which would double count.
            cost = _value(span, "agentmesh.cost.direct_usd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                chat_cost += float(cost)
    pauses = [
        dict(event)
        for event in audit_events
        if _value(event, "event") == "agent_paused" or event.get("body") == "agent_paused"
    ]
    return {
        "trace_id": trace_id,
        "span_count": len(rows),
        "services": sorted({_service(span) for span in rows}),
        "cyclic_agents": cyclic_agents,
        "cycles": [
            {"agents": list(cycle.services), "edges": [list(edge) for edge in cycle.edges]}
            for cycle in cycles
        ],
        "hop_count": hop_count,
        # A cycle is only a runaway loop when a cyclic agent stalled on one state.
        "runaway_loop": stalled_iterations >= 2,
        "stalled_iterations": stalled_iterations,
        "direct_chat_cost_usd": round(chat_cost, 4),
        # A pause is an audit log, not a trace span. Never claim one from trace-only data.
        "pause_action": pauses[-1] if pauses else None,
        # None when no span carries agentmesh.output.flagged.
        "bad_output_origin": origin_of_bad_output(rows),
    }
