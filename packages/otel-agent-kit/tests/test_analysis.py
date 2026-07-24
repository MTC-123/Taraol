from otel_agent_kit import attrs, find_cycles, find_directed_cycles, origin_of_bad_output


def test_find_cycles_detects_ping_pong() -> None:
    spans = [
        {"span_id": "1", "parent_span_id": "", "serviceName": "planner"},
        {"span_id": "2", "parent_span_id": "1", "serviceName": "writer"},
        {"span_id": "3", "parent_span_id": "2", "serviceName": "critic"},
        {"span_id": "4", "parent_span_id": "3", "serviceName": "writer"},
    ]
    cycles = find_cycles(spans)
    assert any({"writer", "critic"} <= set(c.services) for c in cycles)


def test_find_directed_cycles_across_conversations() -> None:
    edges = [("writer", "critic"), ("critic", "writer")]
    cycles = find_directed_cycles(edges, min_repeats=1)
    assert len(cycles) == 1
    assert set(cycles[0].services) == {"writer", "critic"}


def test_origin_of_bad_output_backtracks() -> None:
    names = attrs("agentmesh")
    spans = [
        {"span_id": "1", "parent_span_id": "", "serviceName": "planner"},
        {
            "span_id": "2",
            "parent_span_id": "1",
            "serviceName": "writer",
            "attributes": {names.output_flagged: True, names.output_category: "hallucination"},
        },
        {"span_id": "3", "parent_span_id": "2", "serviceName": "critic"},
    ]
    assert origin_of_bad_output(spans, names) == {
        "origin": "writer",
        "category": "hallucination",
        "consumers": ["critic"],
    }
