"""Namespaced attribute-name builder.

All project-specific span attributes live under a single configurable namespace
(default ``agentmesh``) so a deployment can re-brand without editing call sites.
GenAI attributes follow the stable ``gen_ai.*`` semantic conventions and are never
namespaced (see :mod:`taraol.semconv`).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttrNames:
    """Resolved attribute keys for one namespace."""

    namespace: str

    @property
    def cost_direct_usd(self) -> str:
        # Cost of one agent's own chat call; summing these by conversation is additive.
        return f"{self.namespace}.cost.direct_usd"

    @property
    def cost_downstream_usd(self) -> str:
        # Callee-subtree cost on an a2a hop span (a per-delegation attribution, not additive).
        return f"{self.namespace}.cost.downstream_usd"

    @property
    def cost_conversation_total_usd(self) -> str:
        return f"{self.namespace}.cost.conversation_total_usd"

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

    @property
    def state_hash(self) -> str:
        return f"{self.namespace}.state.hash"

    @property
    def content_truncated(self) -> str:
        return f"{self.namespace}.content.truncated"

    def reasoning_logger(self) -> str:
        return f"{self.namespace}.reasoning"


def attrs(namespace: str) -> AttrNames:
    return AttrNames(namespace)
