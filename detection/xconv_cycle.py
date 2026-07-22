"""Cross-conversation cycle detection over aggregated agent edges.

``amr.cycle.find_cycles`` walks a single trace's parent/child span tree and cannot
see a loop that is spread across separate traces or conversations (an agent
ping-ponging with a peer a little in each of many conversations).  This module works
on an aggregated directed edge multiset instead: it enumerates elementary cycles and
keeps only those whose every edge recurs at least ``min_repeats`` times, so an
occasional benign back-edge does not trip it.

It returns the same :class:`amr.cycle.Cycle` shape so the signal/controller path is
unchanged.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable

from amr.cycle import Cycle


def find_directed_cycles(
    edges: Iterable[tuple[str, str]], min_repeats: int = 2
) -> list[Cycle]:
    """Return elementary directed cycles whose edges each recur >= ``min_repeats``."""

    edge_list = [edge for edge in edges if edge[0] and edge[1]]
    weight = Counter(edge_list)
    adjacency: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for src, target in edge_list:
        adjacency[src].add(target)
        nodes.add(src)
        nodes.add(target)

    found: dict[tuple[str, ...], Cycle] = {}

    def _record(path: list[str]) -> None:
        services = tuple(path) + (path[0],)
        cycle_edges = tuple(zip(services, services[1:], strict=False))
        if any(weight[edge] < min_repeats for edge in cycle_edges):
            return
        found.setdefault(services, Cycle(services, cycle_edges, len(services) - 1))

    def _visit(start: str, node: str, path: list[str], on_path: set[str]) -> None:
        for nxt in sorted(adjacency[node]):
            if nxt == start:
                _record(path)
            # Johnson's canonicalization: only extend to nodes ordered after the
            # start, so each elementary cycle is enumerated exactly once.
            elif nxt > start and nxt not in on_path:
                _visit(start, nxt, [*path, nxt], on_path | {nxt})

    for start in sorted(nodes):
        _visit(start, start, [start], {start})
    return list(found.values())
