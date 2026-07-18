from detection.cycle import find_cycles


def _span(span_id: str, parent: str, service: str, timestamp: int) -> dict[str, object]:
    return {
        "span_id": span_id,
        "parent_span_id": parent,
        "timestamp": timestamp,
        "resource": {"service.name": service},
    }


def test_ping_pong_ancestry_is_a_cycle() -> None:
    spans = [
        _span("1", "", "planner", 1),
        _span("2", "1", "writer", 2),
        _span("3", "2", "critic", 3),
        _span("4", "3", "writer", 4),
        _span("5", "4", "critic", 5),
        _span("6", "5", "writer", 6),
        _span("7", "6", "critic", 7),
    ]
    cycles = find_cycles(spans, max_repeats=3)
    assert cycles
    assert ("critic", "writer") in cycles[0].edges


def test_parallel_retries_are_not_joined_into_a_cycle() -> None:
    spans = [_span("root", "", "planner", 0)]
    spans.extend(_span(str(index), "root", "researcher", index) for index in range(1, 6))
    assert find_cycles(spans) == []


def test_deep_acyclic_chain_is_not_a_cycle() -> None:
    services = ["planner", "researcher", "writer", "critic", "router", "reviewer"]
    spans = [
        _span(str(index), "" if index == 0 else str(index - 1), service, index)
        for index, service in enumerate(services)
    ]
    assert find_cycles(spans) == []
