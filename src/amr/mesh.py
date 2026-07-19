"""Declarative agent topology and bounded loop controls."""

import os

BASE_EDGES: tuple[tuple[str, str], ...] = (
    ("planner", "researcher"),
    ("researcher", "writer"),
    ("writer", "critic"),
    ("critic", "router"),
)
LOOP_EDGE = ("critic", "writer")
LOOP_BOUNCES = 6
STORM_SAFETY_CAP = 24


def loop_mode() -> str:
    mode = os.environ.get("AMR_LOOP_MODE", "off").lower()
    if mode not in {"off", "on", "storm"}:
        raise ValueError("AMR_LOOP_MODE must be off, on, or storm")
    return mode


def edges() -> tuple[tuple[str, str], ...]:
    return BASE_EDGES + (() if loop_mode() == "off" else (LOOP_EDGE,))


def next_targets(agent: str) -> list[str]:
    """Return the configured direct callees for an agent in the current mode."""

    # In loop demos the critic deliberately routes back to the writer first, then
    # still notifies the router, so all five services appear in the loop trace.
    if agent == "critic" and loop_mode() in {"on", "storm"}:
        return ["writer", "router"]
    return [target for source, target in edges() if source == agent]


def max_hops() -> int:
    mode = loop_mode()
    if mode == "off":
        return len(BASE_EDGES)
    if mode == "on":
        return len(BASE_EDGES) + LOOP_BOUNCES
    return STORM_SAFETY_CAP


def path_from(start: str = "planner") -> list[str]:
    """Deterministically traverse the first target, useful for smoke tests and docs."""

    path = [start]
    for _ in range(max_hops()):
        targets = next_targets(path[-1])
        if not targets:
            break
        path.append(targets[0])
    return path
