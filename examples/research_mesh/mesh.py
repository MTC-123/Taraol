"""Topology + loop controls for the research-mesh example (planner→…→router).

Demo-specific — NOT part of the kit. Shows how an app defines its own agent graph;
the kit only instruments it. ``MESH_LOOP_MODE`` (off|on|storm) drives the writer↔critic
loop that the kit's detection watcher catches.
"""

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


def loop_mode(mode: str | None = None) -> str:
    """Resolve the loop mode. An explicit ``mode`` (per-conversation, e.g. from an AgentLab
    variant) wins; otherwise fall back to the ``MESH_LOOP_MODE`` env default."""

    value = (mode or os.environ.get("MESH_LOOP_MODE", "off")).lower()
    if value not in {"off", "on", "storm"}:
        raise ValueError("loop mode must be off, on, or storm")
    return value


def edges(mode: str | None = None) -> tuple[tuple[str, str], ...]:
    return BASE_EDGES + (() if loop_mode(mode) == "off" else (LOOP_EDGE,))


def next_targets(agent: str, mode: str | None = None) -> list[str]:
    if agent == "critic" and loop_mode(mode) in {"on", "storm"}:
        return ["writer", "router"]
    return [target for source, target in edges(mode) if source == agent]


def max_hops(mode: str | None = None) -> int:
    resolved = loop_mode(mode)
    if resolved == "off":
        return len(BASE_EDGES)
    if resolved == "on":
        return len(BASE_EDGES) + LOOP_BOUNCES
    return STORM_SAFETY_CAP


def target_url(target: str) -> str:
    return os.environ.get(f"{target.upper()}_A2A_URL", f"http://{target}:8000/a2a")
