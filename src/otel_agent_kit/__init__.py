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

from . import assets, breaker, capture, guardrail, llm, provenance, quality, replay, taint
from .attributes import AttrNames, attrs
from .config import Settings
from .cost import CostAccumulator, CostModel, add_to_request_cost, request_cost_scope
from .cycle import Cycle, find_cycles, find_directed_cycles
from .decorators import agent, chat, record_chat, record_chat_content, tool
from .experiments import (
    Experiment,
    ExperimentMetadata,
    HealthScore,
    RunResult,
    Variant,
    experiment,
    variant,
)
from .facade import (
    ChatSpan,
    ExperimentContext,
    Instrument,
    ToolSpan,
    current_conversation_id,
    current_experiment,
    use_experiment,
)
from .propagation import extract_from, inject_into
from .provenance import origin_of_bad_output
from .replay import Step, ToolCall, build_steps
from .setup import configure, instrument

__version__ = "0.1.0"

__all__ = [
    "AttrNames",
    "ChatSpan",
    "CostAccumulator",
    "CostModel",
    "Cycle",
    "Experiment",
    "ExperimentContext",
    "ExperimentMetadata",
    "HealthScore",
    "Instrument",
    "RunResult",
    "Settings",
    "Step",
    "ToolCall",
    "ToolSpan",
    "Variant",
    "__version__",
    "add_to_request_cost",
    "agent",
    "assets",
    "attrs",
    "breaker",
    "build_steps",
    "capture",
    "chat",
    "configure",
    "current_conversation_id",
    "current_experiment",
    "experiment",
    "extract_from",
    "find_cycles",
    "find_directed_cycles",
    "guardrail",
    "inject_into",
    "instrument",
    "llm",
    "origin_of_bad_output",
    "provenance",
    "quality",
    "record_chat",
    "record_chat_content",
    "replay",
    "request_cost_scope",
    "taint",
    "tool",
    "use_experiment",
    "variant",
]
