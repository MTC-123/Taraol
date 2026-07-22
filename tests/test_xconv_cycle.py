from detection.xconv_cycle import find_directed_cycles


def test_detects_split_two_cycle_across_conversations() -> None:
    # writer->critic seen in one conversation, critic->writer in another.
    edges = [("writer", "critic"), ("critic", "writer")]
    cycles = find_directed_cycles(edges, min_repeats=1)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert set(cycle.services) == {"writer", "critic"}
    assert cycle.hops == 2
    assert ("writer", "critic") in cycle.edges
    assert ("critic", "writer") in cycle.edges


def test_ignores_acyclic_pipeline() -> None:
    edges = [
        ("planner", "researcher"),
        ("researcher", "writer"),
        ("writer", "critic"),
        ("critic", "router"),
    ]
    assert find_directed_cycles(edges, min_repeats=1) == []


def test_min_repeats_suppresses_single_occurrence_cycles() -> None:
    edges = [("writer", "critic"), ("critic", "writer")]
    assert find_directed_cycles(edges, min_repeats=2) == []
    # Each edge now seen twice -> reported.
    doubled = edges * 2
    assert len(find_directed_cycles(doubled, min_repeats=2)) == 1


def test_three_node_cycle_enumerated_once() -> None:
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    cycles = find_directed_cycles(edges, min_repeats=1)
    assert len(cycles) == 1
    assert cycles[0].hops == 3
