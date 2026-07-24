"""Namespaced attribute-name builder.

All project-specific span attributes live under a single configurable namespace
(default ``agentmesh``) so a deployment can re-brand without editing call sites.
GenAI attributes follow the stable ``gen_ai.*`` semantic conventions and are never
namespaced (see :mod:`otel_agent_kit.semconv`).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttrNames:
    """Resolved attribute keys for one namespace."""

    namespace: str

    @property
    def cost_usd(self) -> str:
        return f"{self.namespace}.cost.usd"

    @property
    def cost_unpriced(self) -> str:
        return f"{self.namespace}.cost.unpriced"

    @property
    def src(self) -> str:
        return f"{self.namespace}.src"

    @property
    def taint(self) -> str:
        return f"{self.namespace}.taint"

    @property
    def taint_category(self) -> str:
        return f"{self.namespace}.taint.category"

    @property
    def taint_origin(self) -> str:
        return f"{self.namespace}.taint.origin"

    @property
    def taint_hops(self) -> str:
        return f"{self.namespace}.taint.hops"

    @property
    def breaker_state(self) -> str:
        return f"{self.namespace}.breaker.state"

    @property
    def breaker_edge(self) -> str:
        return f"{self.namespace}.breaker.edge"

    @property
    def output_flagged(self) -> str:
        return f"{self.namespace}.output.flagged"

    @property
    def output_category(self) -> str:
        return f"{self.namespace}.output.category"

    def reasoning_logger(self) -> str:
        return f"{self.namespace}.reasoning"


def attrs(namespace: str) -> AttrNames:
    return AttrNames(namespace)
