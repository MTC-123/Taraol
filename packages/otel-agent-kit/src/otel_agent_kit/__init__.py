"""otel-agent-kit — drop-in OpenTelemetry instrumentation for multi-agent systems.

Three lines to full observability::

    from otel_agent_kit import instrument
    kit = instrument("planner")                       # OTel wired, zero config
    with kit.agent("planner", conversation_id) as _a, kit.chat("gpt-4.1-mini") as c:
        c.record(input_tokens=n_in, output_tokens=n_out)   # gen_ai span + cost rollup

Security/quality overlays are one extra call: ``kit.mark_injection(...)``,
``kit.taint_scope(...)``, ``kit.flag_output(...)``. Analysis helpers
(``find_cycles``, ``find_directed_cycles``, ``origin_of_bad_output``) and the
per-edge circuit breaker (``get_registry``) are exported for detectors.
"""

from . import assets, breaker, guardrail, provenance, quality, taint
from .attributes import AttrNames, attrs
from .config import Settings
from .cost import CostAccumulator, CostModel, add_to_request_cost, request_cost_scope
from .cycle import Cycle, find_cycles, find_directed_cycles
from .facade import ChatSpan, Instrument, current_conversation_id
from .propagation import extract_from, inject_into
from .provenance import origin_of_bad_output
from .setup import configure, instrument

__version__ = "0.1.0"

__all__ = [
    "instrument",
    "configure",
    "Instrument",
    "ChatSpan",
    "Settings",
    "AttrNames",
    "attrs",
    "CostModel",
    "CostAccumulator",
    "request_cost_scope",
    "add_to_request_cost",
    "Cycle",
    "find_cycles",
    "find_directed_cycles",
    "origin_of_bad_output",
    "current_conversation_id",
    "inject_into",
    "extract_from",
    "assets",
    "breaker",
    "guardrail",
    "quality",
    "taint",
    "provenance",
    "__version__",
]
